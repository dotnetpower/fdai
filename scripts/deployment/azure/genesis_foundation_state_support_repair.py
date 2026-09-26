#!/usr/bin/env python3
"""Repair missing source support for a claimed Foundation handoff without remigration."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import (
    read_private_bytes,
    write_private_bytes,
    write_private_output,
)
from genesis_bastion import BastionTunnel
from genesis_foundation_state_archive import RUNNER_SUPPORT_FILES

SUPPORT_REPAIR_CLAIM_NAME = "foundation-state-support-repair-claim.json"
SUPPORT_REPAIR_MANIFEST_NAME = "foundation-state-support-repair-manifest.json"
SUPPORT_REPAIR_RECEIPT_NAME = "foundation-state-support-repair-receipt.json"
REMOTE_SUPPORT_REPAIR_NAME = "support-repair.json"
REMOTE_VERIFIER_RELATIVE = "support-repair/migrate-foundation-state.py"
INSTALLED_MIGRATION_PROGRAM = ("/usr/local/sbin/fdai-migrate-foundation-state",)

_DIGEST = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_MAX_SUPPORT_BYTES = 16 * 1024 * 1024


class SourceContext(Protocol):
    """Immutable source identity required by a support repair."""

    @property
    def root(self) -> Path: ...

    @property
    def commit(self) -> str: ...


class RecoveryContext(Protocol):
    """Recovery inputs required by the bounded support-repair transition."""

    @property
    def directory(self) -> Path: ...

    @property
    def source(self) -> SourceContext: ...

    def verify_configuration(self) -> None: ...

    def require_approval(self) -> str: ...


@dataclass(frozen=True, slots=True)
class SupportFile:
    """One exact current-source support file and its remote execution mode."""

    path: Path
    content: bytes
    digest: str
    executable: bool


@dataclass(frozen=True, slots=True)
class RemoteFile:
    """One independently observed regular remote file."""

    digest: str
    executable: bool


@dataclass(frozen=True, slots=True)
class RemoteSupportStatus:
    """Archive membership, current files, and optional repair overlay."""

    base_files: dict[str, object]
    actual_files: dict[str, RemoteFile | None]
    verifier: RemoteFile | None
    repair_manifest: dict[str, object] | None


def repair_claimed_support(
    tunnel: BastionTunnel,
    *,
    recovery: RecoveryContext,
    state_claim: dict[str, object],
    directory: Path,
    remote_work: str,
    username: str,
    work_id: str,
    archive_digest: str,
    timeout: int,
) -> tuple[tuple[str, ...], str | None]:
    """Repair only an old archive with no support closure and return its verifier.

    A complete archive remains on the installed verifier. An incomplete archive
    receives a separately claimed overlay only after exact current human approval.
    Existing files are never overwritten, and every repaired byte is read back.
    """

    recovery.verify_configuration()
    source_commit = _source_commit(recovery)
    support = _load_configuration_support(recovery.directory)
    verifier = _read_source_file(
        recovery.source.root / "infra/genesis-runner-image/migrate-foundation-state.py"
    )
    expected_files = _support_manifest(support)
    expected_verifier = _file_manifest(verifier)
    status = _inspect_remote_support(
        tunnel,
        directory=directory,
        remote_work=remote_work,
        username=username,
        work_id=work_id,
        timeout=timeout,
    )
    base_members = {
        name: status.base_files.get(f"genesis-runner-image/{name}") for name in RUNNER_SUPPORT_FILES
    }
    if all(
        _manifest_entry_matches(base_members[name], expected_files[name])
        for name in RUNNER_SUPPORT_FILES
    ):
        if status.repair_manifest is not None or status.verifier is not None:
            raise ValueError("Foundation support repair overlaps a complete base archive")
        _require_exact_remote_files(status.actual_files, expected_files)
        recovery.verify_configuration()
        return INSTALLED_MIGRATION_PROGRAM, None
    if any(value is not None for value in base_members.values()):
        raise ValueError("Foundation base archive contains partial or different support files")
    _require_missing_or_exact_remote_files(status.actual_files, expected_files)
    _require_missing_or_exact_remote_file(status.verifier, expected_verifier)

    claim_path = directory / SUPPORT_REPAIR_CLAIM_NAME
    manifest_path = directory / SUPPORT_REPAIR_MANIFEST_NAME
    receipt_path = directory / SUPPORT_REPAIR_RECEIPT_NAME
    repair_claim = _load_optional_private_json(claim_path)
    repair_source_commit = (
        source_commit
        if repair_claim is None
        else _required_commit(repair_claim.get("repair_source_commit"), "retained repair source")
    )
    expected_context: dict[str, object] = {
        "work_id": work_id,
        "archive_digest": archive_digest,
        "state_claim_digest": canonical_digest(state_claim),
        "prior_migration_source_commit": _required_commit(
            state_claim.get("migration_source_commit"), "prior migration source"
        ),
        "repair_source_commit": repair_source_commit,
        "support_files": expected_files,
        "verifier": expected_verifier,
    }
    if repair_claim is None:
        if status.repair_manifest is not None:
            raise ValueError("Foundation remote support repair lacks its local immutable claim")
        actor_digest = recovery.require_approval()
        repair_claim = {
            "schema_version": "fdai.genesis-foundation-support-repair-claim.v1",
            **expected_context,
            "actor_digest": actor_digest,
            "mutation_performed": False,
            "subscription_ready": False,
        }
        repair_claim["claim_digest"] = canonical_digest(repair_claim)
        write_private_output(
            claim_path,
            json.dumps(repair_claim, sort_keys=True, separators=(",", ":")) + "\n",
        )
    _validate_repair_claim(repair_claim, expected_context)

    remote_manifest = {
        "schema_version": "fdai.genesis-foundation-remote-support-repair.v1",
        **expected_context,
        "repair_claim_digest": repair_claim["claim_digest"],
        "mutation_performed": False,
        "subscription_ready": False,
    }
    remote_manifest["manifest_digest"] = canonical_digest(remote_manifest)
    persisted_manifest = _load_optional_private_json(manifest_path)
    if persisted_manifest is None:
        write_private_output(
            manifest_path,
            json.dumps(remote_manifest, sort_keys=True, separators=(",", ":")) + "\n",
        )
    elif persisted_manifest != remote_manifest:
        raise ValueError("Foundation persisted support repair manifest differs")

    if status.repair_manifest is None:
        _ensure_remote_directory(tunnel, f"{remote_work}/genesis-runner-image", username, timeout)
        for index, name in enumerate(RUNNER_SUPPORT_FILES):
            if status.actual_files[name] is None:
                _install_remote_file(
                    tunnel,
                    source=support[name],
                    local_directory=directory,
                    remote_destination=f"{remote_work}/genesis-runner-image/{name}",
                    remote_temporary=(
                        f"/home/{username}/.fdai-transfer-{work_id[:24]}-support-{index}"
                    ),
                    username=username,
                    timeout=timeout,
                )
        _ensure_remote_directory(tunnel, f"{remote_work}/support-repair", username, timeout)
        if status.verifier is None:
            _install_remote_file(
                tunnel,
                source=verifier,
                local_directory=directory,
                remote_destination=f"{remote_work}/{REMOTE_VERIFIER_RELATIVE}",
                remote_temporary=(
                    f"/home/{username}/.fdai-transfer-{work_id[:24]}-support-verifier"
                ),
                username=username,
                timeout=timeout,
            )
        _install_remote_file(
            tunnel,
            source=_private_support_file(manifest_path),
            local_directory=directory,
            remote_destination=f"{remote_work}/{REMOTE_SUPPORT_REPAIR_NAME}",
            remote_temporary=f"/home/{username}/.fdai-transfer-{work_id[:24]}-support-manifest",
            username=username,
            timeout=timeout,
        )
    elif status.repair_manifest != remote_manifest:
        raise ValueError("Foundation remote support repair manifest differs")

    verified = _inspect_remote_support(
        tunnel,
        directory=directory,
        remote_work=remote_work,
        username=username,
        work_id=work_id,
        timeout=timeout,
    )
    if any(
        verified.base_files.get(f"genesis-runner-image/{name}") is not None
        for name in RUNNER_SUPPORT_FILES
    ):
        raise ValueError("Foundation support repair changed base archive membership")
    if verified.repair_manifest != remote_manifest:
        raise ValueError("Foundation remote support repair readback differs")
    _require_exact_remote_files(verified.actual_files, expected_files)
    _require_exact_remote_file(verified.verifier, expected_verifier)
    recovery.verify_configuration()

    receipt = _load_optional_private_json(receipt_path)
    receipt_context = {
        "schema_version": "fdai.genesis-foundation-support-repair-receipt.v1",
        "state": "verified",
        **expected_context,
        "repair_claim_digest": repair_claim["claim_digest"],
        "remote_manifest_digest": remote_manifest["manifest_digest"],
        "effect_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    if receipt is None:
        receipt = dict(receipt_context)
        receipt["receipt_digest"] = canonical_digest(receipt)
        write_private_output(
            receipt_path,
            json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        )
    _validate_repair_receipt(receipt, receipt_context)
    return (
        ("/usr/bin/python3", f"{remote_work}/{REMOTE_VERIFIER_RELATIVE}"),
        str(remote_manifest["manifest_digest"]),
    )


def _load_configuration_support(directory: Path) -> dict[str, SupportFile]:
    root = directory / "source/infra/genesis-runner-image"
    return {name: _read_source_file(root / name) for name in RUNNER_SUPPORT_FILES}


def _read_source_file(path: Path) -> SupportFile:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or not 0 < before.st_size <= _MAX_SUPPORT_BYTES
        ):
            raise PermissionError("Foundation support source is not a bounded owned regular file")
        content = stream.read(_MAX_SUPPORT_BYTES + 1)
        after = os.fstat(stream.fileno())
    if (
        len(content) != before.st_size
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or after.st_ctime_ns != before.st_ctime_ns
    ):
        raise ValueError("Foundation support source changed while being read")
    return SupportFile(
        path=path,
        content=content,
        digest=hashlib.sha256(content).hexdigest(),
        executable=bool(before.st_mode & stat.S_IXUSR),
    )


def _private_support_file(path: Path) -> SupportFile:
    content = read_private_bytes(path, max_bytes=_MAX_SUPPORT_BYTES)
    return SupportFile(
        path=path,
        content=content,
        digest=hashlib.sha256(content).hexdigest(),
        executable=False,
    )


def _support_manifest(support: dict[str, SupportFile]) -> dict[str, object]:
    return {
        name: {"sha256": item.digest, "executable": item.executable}
        for name, item in support.items()
    }


def _file_manifest(item: SupportFile) -> dict[str, object]:
    return {"sha256": item.digest, "executable": item.executable}


def _inspect_remote_support(
    tunnel: BastionTunnel,
    *,
    directory: Path,
    remote_work: str,
    username: str,
    work_id: str,
    timeout: int,
) -> RemoteSupportStatus:
    base = _retrieve_remote_json(
        tunnel,
        remote_path=f"{remote_work}/manifest.json",
        directory=directory,
        username=username,
        work_id=work_id,
        label="base-manifest",
        timeout=timeout,
        required=True,
    )
    if base is None:
        raise ValueError("Foundation base archive manifest is unavailable")
    manifest_digest = base.pop("manifest_digest", None)
    files = base.get("files")
    if (
        base.get("schema_version") != "fdai.genesis-foundation-state-archive.v1"
        or manifest_digest != canonical_digest(base)
        or not isinstance(files, dict)
    ):
        raise ValueError("Foundation base archive manifest is invalid")
    base["manifest_digest"] = manifest_digest
    actual = {
        name: _remote_file(
            tunnel,
            f"{remote_work}/genesis-runner-image/{name}",
            username,
            timeout,
        )
        for name in RUNNER_SUPPORT_FILES
    }
    verifier = _remote_file(
        tunnel,
        f"{remote_work}/{REMOTE_VERIFIER_RELATIVE}",
        username,
        timeout,
    )
    repair = _retrieve_remote_json(
        tunnel,
        remote_path=f"{remote_work}/{REMOTE_SUPPORT_REPAIR_NAME}",
        directory=directory,
        username=username,
        work_id=work_id,
        label="repair-manifest",
        timeout=timeout,
        required=False,
    )
    return RemoteSupportStatus(files, actual, verifier, repair)


def _retrieve_remote_json(
    tunnel: BastionTunnel,
    *,
    remote_path: str,
    directory: Path,
    username: str,
    work_id: str,
    label: str,
    timeout: int,
    required: bool,
) -> dict[str, object] | None:
    remote = _remote_file(tunnel, remote_path, username, timeout)
    if remote is None:
        if required:
            raise ValueError(f"Foundation remote {label} is unavailable")
        return None
    if remote.executable:
        raise ValueError(f"Foundation remote {label} has an unsafe mode")
    local = directory / f".support-{label}-{work_id[:12]}-{secrets.token_hex(8)}.json"
    try:
        tunnel.copy_from(remote_path, local, timeout=min(timeout, 300))
        content = read_private_bytes(local, max_bytes=_MAX_SUPPORT_BYTES)
        if hashlib.sha256(content).hexdigest() != remote.digest:
            raise ValueError(f"Foundation remote {label} changed during readback")
        value = json.loads(content)
        if not isinstance(value, dict):
            raise ValueError(f"Foundation remote {label} must be an object")
        return value
    finally:
        _unlink_private(local)


def _remote_file(
    tunnel: BastionTunnel, path: str, username: str, timeout: int
) -> RemoteFile | None:
    details = tunnel.ssh(
        ("/usr/bin/stat", "--format=%F,%h,%a,%U", path),
        timeout=min(timeout, 60),
    )
    if details.returncode != 0:
        return None
    parts = details.stdout.strip().split(",")
    if len(parts) != 4 or parts[0] != "regular file" or parts[1] != "1" or parts[3] != username:
        raise ValueError("Foundation remote support path is not a safe owned regular file")
    if parts[2] not in {"600", "700"}:
        raise ValueError("Foundation remote support path mode is invalid")
    digest = tunnel.ssh(("/usr/bin/sha256sum", path), timeout=min(timeout, 60))
    token = digest.stdout.strip().split(maxsplit=1)
    if digest.returncode != 0 or len(token) != 2 or _DIGEST.fullmatch(token[0]) is None:
        raise ValueError("Foundation remote support digest readback failed")
    return RemoteFile(token[0], parts[2] == "700")


def _ensure_remote_directory(tunnel: BastionTunnel, path: str, username: str, timeout: int) -> None:
    details = tunnel.ssh(
        ("/usr/bin/stat", "--format=%F,%a,%U", path),
        timeout=min(timeout, 60),
    )
    if details.returncode != 0:
        created = tunnel.ssh(("/usr/bin/mkdir", "-m", "0700", path), timeout=min(timeout, 60))
        if created.returncode != 0:
            raise ValueError("Foundation remote support directory creation failed")
        details = tunnel.ssh(
            ("/usr/bin/stat", "--format=%F,%a,%U", path),
            timeout=min(timeout, 60),
        )
    if details.returncode != 0 or details.stdout.strip() != f"directory,700,{username}":
        raise ValueError("Foundation remote support directory is unsafe")


def _install_remote_file(
    tunnel: BastionTunnel,
    *,
    source: SupportFile,
    local_directory: Path,
    remote_destination: str,
    remote_temporary: str,
    username: str,
    timeout: int,
) -> None:
    local = local_directory / f".support-transfer-{secrets.token_hex(8)}"
    write_private_bytes(local, source.content)
    remote_temporary_present = False
    try:
        tunnel.copy_to(local, remote_temporary, timeout=min(timeout, 300))
        remote_temporary_present = True
        mode = "0700" if source.executable else "0600"
        changed = tunnel.ssh(
            ("/usr/bin/chmod", mode, remote_temporary),
            timeout=min(timeout, 60),
        )
        if changed.returncode != 0:
            raise ValueError("Foundation remote support staging mode failed")
        tunnel.ssh(
            ("/usr/bin/ln", remote_temporary, remote_destination),
            timeout=min(timeout, 60),
        )
        _remove_remote_temporary(tunnel, remote_temporary, timeout)
        remote_temporary_present = False
        observed = _remote_file(tunnel, remote_destination, username, timeout)
        if observed != RemoteFile(source.digest, source.executable):
            raise ValueError("Foundation remote support install readback differs")
    finally:
        _unlink_private(local)
        if remote_temporary_present:
            _remove_remote_temporary(tunnel, remote_temporary, timeout)


def _remove_remote_temporary(tunnel: BastionTunnel, remote_temporary: str, timeout: int) -> None:
    removed = tunnel.ssh(
        ("/usr/bin/rm", "-f", "--", remote_temporary),
        timeout=min(timeout, 60),
    )
    if removed.returncode != 0:
        raise ValueError("Foundation remote support transfer cleanup failed")


def _manifest_entry_matches(value: object, expected: object) -> bool:
    return isinstance(value, dict) and value == expected


def _require_exact_remote_files(
    actual: dict[str, RemoteFile | None], expected: dict[str, object]
) -> None:
    for name in RUNNER_SUPPORT_FILES:
        entry = expected[name]
        if not isinstance(entry, dict):
            raise ValueError("Foundation support manifest entry is invalid")
        expected_file = RemoteFile(str(entry["sha256"]), bool(entry["executable"]))
        if actual.get(name) != expected_file:
            raise ValueError("Foundation remote support files differ from current source")


def _require_missing_or_exact_remote_files(
    actual: dict[str, RemoteFile | None], expected: dict[str, object]
) -> None:
    for name in RUNNER_SUPPORT_FILES:
        observed = actual.get(name)
        if observed is None:
            continue
        entry = expected[name]
        if not isinstance(entry, dict) or observed != RemoteFile(
            str(entry["sha256"]), bool(entry["executable"])
        ):
            raise ValueError("Foundation existing remote support file differs")


def _require_exact_remote_file(actual: RemoteFile | None, expected: object) -> None:
    if not isinstance(expected, dict) or actual != RemoteFile(
        str(expected["sha256"]), bool(expected["executable"])
    ):
        raise ValueError("Foundation remote repair verifier differs from current source")


def _require_missing_or_exact_remote_file(actual: RemoteFile | None, expected: object) -> None:
    if actual is not None:
        _require_exact_remote_file(actual, expected)


def _validate_repair_claim(claim: dict[str, object], expected_context: dict[str, object]) -> None:
    digest = claim.get("claim_digest")
    unsigned = {key: value for key, value in claim.items() if key != "claim_digest"}
    if (
        set(claim)
        != {
            "schema_version",
            *expected_context,
            "actor_digest",
            "mutation_performed",
            "subscription_ready",
            "claim_digest",
        }
        or claim.get("schema_version") != "fdai.genesis-foundation-support-repair-claim.v1"
        or any(claim.get(key) != value for key, value in expected_context.items())
        or _DIGEST.fullmatch(str(claim.get("actor_digest", ""))) is None
        or claim.get("mutation_performed") is not False
        or claim.get("subscription_ready") is not False
        or digest != canonical_digest(unsigned)
    ):
        raise ValueError("Foundation support repair claim differs")


def _validate_repair_receipt(
    receipt: dict[str, object], expected_context: dict[str, object]
) -> None:
    digest = receipt.get("receipt_digest")
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    if (
        set(receipt) != {*expected_context, "receipt_digest"}
        or any(receipt.get(key) != value for key, value in expected_context.items())
        or digest != canonical_digest(unsigned)
    ):
        raise ValueError("Foundation support repair receipt differs")


def _load_optional_private_json(path: Path) -> dict[str, object] | None:
    if not path.exists() and not path.is_symlink():
        return None
    value = json.loads(read_private_bytes(path, max_bytes=_MAX_SUPPORT_BYTES))
    if not isinstance(value, dict):
        raise ValueError("Foundation support repair record must be an object")
    return value


def retained_repair_source_commit(directory: Path) -> str | None:
    """Return the immutable source of an existing repair claim after self-verification."""

    claim = _load_optional_private_json(directory / SUPPORT_REPAIR_CLAIM_NAME)
    if claim is None:
        return None
    digest = claim.get("claim_digest")
    unsigned = {key: value for key, value in claim.items() if key != "claim_digest"}
    if (
        claim.get("schema_version") != "fdai.genesis-foundation-support-repair-claim.v1"
        or claim.get("mutation_performed") is not False
        or claim.get("subscription_ready") is not False
        or digest != canonical_digest(unsigned)
    ):
        raise ValueError("Foundation retained support repair claim is invalid")
    return _required_commit(claim.get("repair_source_commit"), "retained repair source")


def _source_commit(recovery: RecoveryContext) -> str:
    return _required_commit(recovery.source.commit, "repair source")


def _required_commit(value: object, label: str) -> str:
    if not isinstance(value, str) or _COMMIT.fullmatch(value) is None:
        raise ValueError(f"Foundation {label} commit is invalid")
    return value


def _unlink_private(path: Path) -> None:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.geteuid()
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_nlink != 1
    ):
        raise PermissionError("Foundation temporary support file is unsafe")
    path.unlink()

#!/usr/bin/env python3
"""Migrate one exact local Foundation state to a private AzureRM backend."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

_DIGEST = re.compile(r"[0-9a-f]{64}")
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{1,62}")
_ACCOUNT = re.compile(r"[a-z0-9]{3,24}")
_CONTAINER = re.compile(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?")
_KEY = re.compile(r"[A-Za-z0-9._/-]{1,256}")
_MAX_FILES = 4096
_MAX_BYTES = 1024 * 1024 * 1024
_AZURE_CLI = "/usr/bin/az"
_TERRAFORM = "/usr/local/bin/terraform"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("migrate", "verify", "observe", "cleanup"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-digest", required=True)
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--principal-id", required=True)
    parser.add_argument("--state-account-id", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--account-name", required=True)
    parser.add_argument("--container-name", required=True)
    parser.add_argument("--backend-key", required=True)
    parser.add_argument("--expected-state-digest", required=True)
    return parser


def main() -> int:
    """Execute one migration or verification-only continuation."""

    args = _parser().parse_args()
    try:
        _validate(args)
        home = Path.home()
        base = home / ".fdai-state-handoff"
        base.mkdir(mode=0o700, exist_ok=True)
        _require_directory(base)
        work = base / args.work_id[:24]
        cleanup_marker = base / f"cleanup-{args.work_id[:24]}.json"
        if args.mode == "cleanup":
            _cleanup_remote_state(args, base, work, cleanup_marker)
            print(f"state_handoff_cleanup_complete work_ref={args.work_id[:24]}")
            return 0
        if args.mode == "observe":
            _observe_remote_authority(args, cleanup_marker)
            print(f"state_handoff_observation_complete work_ref={args.work_id[:24]}")
            return 0
        if args.mode == "migrate":
            if work.exists() or work.is_symlink():
                raise ValueError("Foundation state migration work already exists")
            work.mkdir(mode=0o700)
            archive_digest = _extract_archive(args.archive, work)
            if archive_digest != args.archive_digest:
                raise ValueError("Foundation state handoff archive digest differs")
            _verify_tree(work, migrated=False)
            state = work / "root/terraform.tfstate"
            if _digest_file(state) != args.expected_state_digest:
                raise ValueError("Foundation local state digest differs before migration")
            shutil.copyfile(state, work / "local-state.json")
            (work / "local-state.json").chmod(0o600)
            _write_json(
                work / "remote-claim.json",
                {
                    "schema_version": "fdai.genesis-foundation-remote-state-claim.v1",
                    "work_id": args.work_id,
                    "archive_digest": args.archive_digest,
                    "expected_state_digest": args.expected_state_digest,
                    "mutation_performed": False,
                    "subscription_ready": False,
                },
            )
        else:
            _require_directory(work)
            claim = _read_json(work / "remote-claim.json")
            if (
                claim.get("schema_version") != "fdai.genesis-foundation-remote-state-claim.v1"
                or claim.get("work_id") != args.work_id
                or claim.get("archive_digest") != args.archive_digest
                or claim.get("expected_state_digest") != args.expected_state_digest
            ):
                raise ValueError("Foundation remote state claim context differs")
            _verify_tree(work, migrated=True)

        environment = _terraform_environment(work, args)
        _managed_identity_login(work, args)
        root = work / "root"
        if args.mode == "migrate":
            _run(
                (
                    _TERRAFORM,
                    "init",
                    "-input=false",
                    "-migrate-state",
                    "-force-copy",
                    "-lockfile=readonly",
                    f"-backend-config=resource_group_name={args.resource_group}",
                    f"-backend-config=storage_account_name={args.account_name}",
                    f"-backend-config=container_name={args.container_name}",
                    f"-backend-config=key={args.backend_key}",
                    "-backend-config=use_azuread_auth=true",
                ),
                cwd=root,
                env=environment,
                timeout=900,
                reason="Foundation backend migration failed; automatic retry is blocked",
            )
            _write_json(
                work / "migration-complete.json",
                {
                    "schema_version": "fdai.genesis-foundation-remote-state-effect.v1",
                    "work_id": args.work_id,
                    "archive_digest": args.archive_digest,
                    "mutation_performed": True,
                    "subscription_ready": False,
                },
            )

        remote_state = _capture(
            (_TERRAFORM, "state", "pull"),
            cwd=root,
            env=environment,
            timeout=180,
            reason="Foundation remote state pull failed",
            max_bytes=64 * 1024 * 1024,
        )
        _write_bytes(work / "remote-state.json", remote_state)
        plan_path = work / "remote-zero.tfplan"
        completed = subprocess.run(  # noqa: S603 - fixed Terraform command
            (
                _TERRAFORM,
                "plan",
                "-input=false",
                "-no-color",
                "-detailed-exitcode",
                "-var-file=../variables.auto.tfvars.json",
                f"-out={plan_path}",
            ),
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=900,
            check=False,
        )
        if completed.returncode != 0:
            raise ValueError("Foundation remote plan is not zero-change")
        plan_json = _capture(
            (_TERRAFORM, "show", "-json", str(plan_path)),
            cwd=root,
            env=environment,
            timeout=180,
            reason="Foundation remote plan inspection failed",
            max_bytes=64 * 1024 * 1024,
        )
        _write_bytes(work / "remote-plan.json", plan_json)
        _verify_backend(args, environment)
        result = {
            "schema_version": "fdai.genesis-foundation-remote-state-observation.v1",
            "state": "verified",
            "work_id": args.work_id,
            "archive_digest": args.archive_digest,
            "remote_state_digest": hashlib.sha256(remote_state).hexdigest(),
            "remote_plan_digest": hashlib.sha256(plan_json).hexdigest(),
            "managed_identity_verified": True,
            "backend_protection_verified": True,
            "backend_blob_verified": True,
            "zero_change_verified": True,
            "mutation_performed": True,
            "subscription_ready": False,
        }
        _write_json(work / "observation.json", result)
        print(f"state_handoff_complete work_ref={args.work_id[:24]}")
        return 0
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
        tarfile.TarError,
    ) as exc:
        print(f"fdai-migrate-foundation-state: {exc}", file=os.sys.stderr)
        return 3


def _observe_remote_authority(args: argparse.Namespace, cleanup_marker: Path) -> None:
    marker = _read_json(cleanup_marker)
    if (
        marker.get("schema_version") != "fdai.genesis-foundation-remote-state-cleanup.v1"
        or marker.get("work_id") != args.work_id
        or marker.get("archive_digest") != args.archive_digest
        or marker.get("raw_transient_deleted") is not True
    ):
        raise ValueError("Foundation state authority observation lacks cleanup evidence")
    _require_cleanup_absence(Path.home() / ".fdai-state-handoff" / args.work_id[:24], args.archive)
    work = Path.home() / ".fdai-state-observe" / args.work_id[:24]
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(mode=0o700, parents=True)
    try:
        (work / "mirror").mkdir(mode=0o700)
        environment = _terraform_environment(work, args)
        _managed_identity_login(work, args)
        (work / "root").mkdir(mode=0o700)
        _write_bytes(work / "root/main.tf", b'terraform { backend "azurerm" {} }\n')
        _run(
            (
                _TERRAFORM,
                "-chdir=root",
                "init",
                "-input=false",
                f"-backend-config=resource_group_name={args.resource_group}",
                f"-backend-config=storage_account_name={args.account_name}",
                f"-backend-config=container_name={args.container_name}",
                f"-backend-config=key={args.backend_key}",
                "-backend-config=use_azuread_auth=true",
            ),
            cwd=work,
            env=environment,
            timeout=300,
            reason="Foundation remote state observation initialization failed",
        )
        remote_state = _capture(
            (_TERRAFORM, "-chdir=root", "state", "pull"),
            cwd=work,
            env=environment,
            timeout=180,
            reason="Foundation remote state observation pull failed",
            max_bytes=64 * 1024 * 1024,
        )
        remote_value = json.loads(remote_state)
        if (
            not isinstance(remote_value, dict)
            or _canonical_digest(remote_value) != args.expected_state_digest
        ):
            raise ValueError("Foundation remote state observation digest differs")
        _verify_backend(args, environment)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _cleanup_remote_state(
    args: argparse.Namespace, base: Path, work: Path, completed: Path
) -> None:
    intent = base / f"cleanup-intent-{args.work_id[:24]}.json"
    intent_value = {
        "schema_version": "fdai.genesis-foundation-remote-state-cleanup-intent.v1",
        "work_id": args.work_id,
        "archive_digest": args.archive_digest,
        "cleanup_authorized": True,
    }
    completed_value = {
        "schema_version": "fdai.genesis-foundation-remote-state-cleanup.v1",
        "work_id": args.work_id,
        "archive_digest": args.archive_digest,
        "raw_transient_deleted": True,
    }
    if completed.exists():
        if _read_json(completed) != completed_value:
            raise ValueError("Foundation state cleanup marker context differs")
        _require_cleanup_absence(work, args.archive)
        intent.unlink(missing_ok=True)
        return
    if intent.exists():
        if _read_json(intent) != intent_value:
            raise ValueError("Foundation state cleanup intent context differs")
    else:
        _require_directory(work)
        observation = _read_json(work / "observation.json")
        claim = _read_json(work / "remote-claim.json")
        if (
            observation.get("schema_version")
            != "fdai.genesis-foundation-remote-state-observation.v1"
            or observation.get("state") != "verified"
            or observation.get("work_id") != args.work_id
            or observation.get("archive_digest") != args.archive_digest
            or observation.get("managed_identity_verified") is not True
            or observation.get("backend_protection_verified") is not True
            or observation.get("backend_blob_verified") is not True
            or observation.get("zero_change_verified") is not True
            or claim.get("schema_version") != "fdai.genesis-foundation-remote-state-claim.v1"
            or claim.get("work_id") != args.work_id
            or claim.get("archive_digest") != args.archive_digest
            or claim.get("expected_state_digest") != args.expected_state_digest
        ):
            raise ValueError("Foundation state cleanup lacks verified authority")
        _write_json(intent, intent_value)
    if work.is_symlink():
        raise ValueError("Foundation state cleanup work path is unsafe")
    if work.exists():
        shutil.rmtree(work)
    args.archive.unlink(missing_ok=True)
    _require_cleanup_absence(work, args.archive)
    _write_json(completed, completed_value)
    intent.unlink(missing_ok=True)


def _require_cleanup_absence(work: Path, archive: Path) -> None:
    if work.exists() or work.is_symlink() or archive.exists() or archive.is_symlink():
        raise ValueError("Foundation state cleanup residue remains")


def _validate(args: argparse.Namespace) -> None:
    for value in (
        args.archive_digest,
        args.work_id,
        args.expected_state_digest,
    ):
        if _DIGEST.fullmatch(value) is None:
            raise ValueError("Foundation state handoff digest is invalid")
    for value in (
        args.subscription_id,
        args.tenant_id,
        args.client_id,
        args.principal_id,
    ):
        if _GUID.fullmatch(value) is None:
            raise ValueError("Foundation state handoff identity is invalid")
    if _NAME.fullmatch(args.resource_group) is None:
        raise ValueError("Foundation state resource group is invalid")
    if _ACCOUNT.fullmatch(args.account_name) is None:
        raise ValueError("Foundation state account name is invalid")
    if _CONTAINER.fullmatch(args.container_name) is None:
        raise ValueError("Foundation state container name is invalid")
    if _KEY.fullmatch(args.backend_key) is None or ".." in args.backend_key.split("/"):
        raise ValueError("Foundation backend key is invalid")
    expected_account = (
        f"/subscriptions/{args.subscription_id}/resourceGroups/{args.resource_group}/"
        f"providers/Microsoft.Storage/storageAccounts/{args.account_name}"
    )
    if args.state_account_id.casefold() != expected_account.casefold():
        raise ValueError("Foundation state account identity is invalid")
    expected_archive = Path.home() / f".fdai-transfer-{args.work_id[:24]}.tar.gz"
    if args.archive != expected_archive:
        raise ValueError("Foundation state archive path is invalid")


def _extract_archive(archive: Path, destination: Path) -> str:
    descriptor = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or details.st_uid != os.geteuid():
            raise ValueError("Foundation state archive must be an owned regular file")
        if not 0 < details.st_size <= _MAX_BYTES:
            raise ValueError("Foundation state archive exceeds its size bound")
        os.fchmod(stream.fileno(), 0o600)
        checksum = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
        digest = checksum.hexdigest()
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode="r:gz") as bundle:
            members = bundle.getmembers()
            if not 1 <= len(members) <= _MAX_FILES:
                raise ValueError("Foundation state archive member count is invalid")
            total = 0
            for member in members:
                relative = PurePosixPath(member.name)
                if (
                    relative.is_absolute()
                    or not relative.parts
                    or any(part in {"", ".", ".."} for part in relative.parts)
                    or not (member.isdir() or member.isfile())
                ):
                    raise ValueError("Foundation state archive contains an unsafe member")
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(mode=0o700, parents=True, exist_ok=True)
                    continue
                total += member.size
                if total > _MAX_BYTES:
                    raise ValueError("Foundation state archive expands beyond its size bound")
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise ValueError("Foundation state archive file cannot be read")
                output = os.open(
                    target,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                )
                with source, os.fdopen(output, "wb") as sink:
                    shutil.copyfileobj(source, sink, length=1024 * 1024)
    archive.unlink()
    return digest


def _verify_tree(work: Path, *, migrated: bool) -> None:
    manifest = _read_json(work / "manifest.json")
    manifest_digest = manifest.pop("manifest_digest", None)
    files = manifest.get("files")
    if (
        not isinstance(manifest_digest, str)
        or _canonical_digest(manifest) != manifest_digest
        or manifest.get("schema_version") != "fdai.genesis-foundation-state-archive.v1"
        or not isinstance(files, dict)
        or not 1 <= len(files) <= _MAX_FILES
    ):
        raise ValueError("Foundation state archive manifest is invalid")
    expected: dict[str, dict[str, object]] = {}
    for key, value in files.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise ValueError("Foundation state archive file manifest is invalid")
        if set(value) != {"sha256", "executable"}:
            raise ValueError("Foundation state archive file manifest is invalid")
        digest = value.get("sha256")
        executable = value.get("executable")
        if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
            raise ValueError("Foundation state archive file digest is invalid")
        if type(executable) is not bool:
            raise ValueError("Foundation state archive executable marker is invalid")
        expected[key] = {"sha256": digest, "executable": executable}
    if migrated:
        expected.pop("root/terraform.tfstate", None)
        if _digest_file(work / "local-state.json") != manifest.get("state_digest"):
            raise ValueError("Foundation retained local state digest differs")
    actual: dict[str, dict[str, object]] = {}
    for path in sorted(work.rglob("*")):
        relative = path.relative_to(work).as_posix()
        if migrated and (
            relative.startswith(("root/.terraform/", "azure/"))
            or relative.startswith("root/terraform.tfstate.backup")
        ):
            continue
        details = path.lstat()
        if stat.S_ISDIR(details.st_mode):
            continue
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise ValueError("Foundation state archive tree contains an unsafe file")
        if relative == "manifest.json":
            continue
        if relative in {"remote-claim.json", "migration-complete.json"}:
            continue
        if relative in {
            "local-state.json",
            "remote-plan.json",
            "remote-state.json",
            "remote-zero.tfplan",
            "observation.json",
            "offline.tfrc",
        }:
            continue
        if migrated and relative == "root/terraform.tfstate":
            continue
        executable = bool(expected.get(relative, {}).get("executable", False))
        path.chmod(0o700 if executable else 0o600)
        actual[relative] = {
            "sha256": _digest_file(path),
            "executable": executable,
        }
    if expected != actual:
        raise ValueError("Foundation state archive file digests differ")


def _canonical_digest(value: dict[str, object]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _managed_identity_login(work: Path, args: argparse.Namespace) -> None:
    azure = work / "azure"
    if azure.exists():
        shutil.rmtree(azure)
    azure.mkdir(mode=0o700)
    environment = {**os.environ, "AZURE_CONFIG_DIR": str(azure)}
    _run(
        (
            _AZURE_CLI,
            "login",
            "--identity",
            "--client-id",
            args.client_id,
            "--allow-no-subscriptions",
            "--output",
            "none",
            "--only-show-errors",
        ),
        cwd=work,
        env=environment,
        timeout=60,
        reason="Foundation state managed identity login failed",
    )
    _run(
        (
            _AZURE_CLI,
            "account",
            "set",
            "--subscription",
            args.subscription_id,
            "--only-show-errors",
        ),
        cwd=work,
        env=environment,
        timeout=30,
        reason="Foundation state Azure subscription selection failed",
    )
    account = json.loads(
        _capture(
            (
                _AZURE_CLI,
                "account",
                "show",
                "--query",
                "[id,tenantId]",
                "--output",
                "json",
            ),
            cwd=work,
            env=environment,
            timeout=30,
            reason="Foundation state Azure target readback failed",
        )
    )
    if (
        not isinstance(account, list)
        or len(account) != 2
        or str(account[0]).casefold() != args.subscription_id.casefold()
        or str(account[1]).casefold() != args.tenant_id.casefold()
    ):
        raise ValueError("Foundation state Azure target readback differs")
    token = (
        _capture(
            (
                _AZURE_CLI,
                "account",
                "get-access-token",
                "--resource",
                "https://management.azure.com/",
                "--query",
                "accessToken",
                "--output",
                "tsv",
                "--only-show-errors",
            ),
            cwd=work,
            env=environment,
            timeout=30,
            reason="Foundation state identity token readback failed",
            max_bytes=32 * 1024,
        )
        .decode()
        .strip()
    )
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Foundation state identity token is invalid")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload))
    if str(claims.get("oid", "")).casefold() != args.principal_id.casefold():
        raise ValueError("Foundation state managed identity principal differs")


def _terraform_environment(work: Path, args: argparse.Namespace) -> dict[str, str]:
    if any(
        key.startswith("TF_CLI_ARGS")
        or key in {"TF_WORKSPACE", "TF_DATA_DIR", "TF_CLI_CONFIG_FILE"}
        for key in os.environ
    ):
        raise ValueError("ambient Terraform control variables are not accepted")
    cli_config = work / "offline.tfrc"
    cli_config.write_text(
        "provider_installation {\n"
        "  filesystem_mirror {\n"
        f'    path = "{work / "mirror"}"\n'
        '    include = ["*/*"]\n'
        "  }\n"
        "  direct {\n"
        '    exclude = ["*/*"]\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    cli_config.chmod(0o600)
    return {
        **os.environ,
        "AZURE_CONFIG_DIR": str(work / "azure"),
        "TF_DATA_DIR": str(work / "root/.terraform"),
        "TF_CLI_CONFIG_FILE": str(cli_config),
        "TF_IN_AUTOMATION": "1",
        "ARM_USE_MSI": "true",
        "ARM_USE_AZUREAD": "true",
        "ARM_CLIENT_ID": args.client_id,
        "ARM_SUBSCRIPTION_ID": args.subscription_id,
        "ARM_TENANT_ID": args.tenant_id,
        "ARM_RESOURCE_PROVIDER_REGISTRATIONS": "none",
    }


def _verify_backend(args: argparse.Namespace, environment: dict[str, str]) -> None:
    account = json.loads(
        _capture(
            (
                _AZURE_CLI,
                "resource",
                "show",
                "--ids",
                args.state_account_id,
                "--api-version",
                "2023-05-01",
                "--query",
                "{public:properties.publicNetworkAccess,key:properties.allowSharedKeyAccess,tls:properties.minimumTlsVersion}",
                "--output",
                "json",
                "--only-show-errors",
            ),
            cwd=Path.home(),
            env=environment,
            timeout=60,
            reason="Foundation backend protection readback failed",
        )
    )
    if account != {"public": "Disabled", "key": False, "tls": "TLS1_2"}:
        raise ValueError("Foundation backend protection differs")
    blob_service = json.loads(
        _capture(
            (
                _AZURE_CLI,
                "resource",
                "show",
                "--ids",
                f"{args.state_account_id}/blobServices/default",
                "--api-version",
                "2023-05-01",
                "--query",
                "{versioning:properties.isVersioningEnabled,blobDelete:properties.deleteRetentionPolicy.enabled,containerDelete:properties.containerDeleteRetentionPolicy.enabled}",
                "--output",
                "json",
                "--only-show-errors",
            ),
            cwd=Path.home(),
            env=environment,
            timeout=60,
            reason="Foundation backend Blob protection readback failed",
        )
    )
    if blob_service != {
        "versioning": True,
        "blobDelete": True,
        "containerDelete": True,
    }:
        raise ValueError("Foundation backend Blob protection differs")
    _run(
        (
            _AZURE_CLI,
            "storage",
            "blob",
            "show",
            "--auth-mode",
            "login",
            "--account-name",
            args.account_name,
            "--container-name",
            args.container_name,
            "--name",
            args.backend_key,
            "--output",
            "none",
            "--only-show-errors",
        ),
        cwd=Path.home(),
        env=environment,
        timeout=60,
        reason="Foundation backend Blob readback failed",
    )


def _run(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    reason: str,
) -> None:
    completed = subprocess.run(  # noqa: S603 - fixed reviewed executable commands
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(reason)


def _capture(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    reason: str,
    max_bytes: int = 1024 * 1024,
) -> bytes:
    completed = subprocess.run(  # noqa: S603 - fixed reviewed executable commands
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0 or not 0 < len(completed.stdout) <= max_bytes:
        raise ValueError(reason)
    return completed.stdout


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(_read_bytes(path, 16 * 1024 * 1024))
    if not isinstance(value, dict):
        raise ValueError("Foundation state handoff JSON is invalid")
    return {str(key): item for key, item in value.items()}


def _write_json(path: Path, value: dict[str, object]) -> None:
    _write_bytes(path, json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n")


def _write_bytes(path: Path, value: bytes) -> None:
    temporary = path.parent / f".{path.name}.tmp"
    temporary.unlink(missing_ok=True)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    path.chmod(0o600)


def _read_bytes(path: Path, max_bytes: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or not 0 < details.st_size <= max_bytes:
            raise ValueError("Foundation state handoff file is invalid")
        return stream.read(max_bytes + 1)


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_directory(path: Path) -> None:
    details = path.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.geteuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise PermissionError("Foundation state handoff directory must be owner-only")


if __name__ == "__main__":
    raise SystemExit(main())

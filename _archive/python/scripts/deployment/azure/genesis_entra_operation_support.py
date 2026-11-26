#!/usr/bin/env python3
"""Private context, output, and filesystem support for Entra-only orchestration."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.entra_profiles import EntraControlProfile, EntraTargetProfile
from fdai_deployment_cli.identity_profile import IdentityProfileObservation
from genesis_entra_records import OperationContext

_DIGEST = re.compile(r"[0-9a-f]{64}")


def operation_context(
    *,
    source_commit: str,
    target: EntraTargetProfile,
    controls: EntraControlProfile,
    snapshot_digest: str,
) -> OperationContext:
    executor_digest = hashlib.sha256(target.executor_object_id.casefold().encode()).hexdigest()
    run_binding = canonical_digest(
        {
            "operation": "entra-only",
            "environment": target.environment,
            "source_commit": source_commit,
            "target_binding": target.target_binding,
            "target_profile_digest": target.digest,
            "control_profile_digest": controls.digest,
            "snapshot_digest": snapshot_digest,
            "executor_digest": executor_digest,
        }
    )
    return OperationContext(
        source_commit=source_commit,
        executor_object_id=target.executor_object_id,
        environment=target.environment,
        target_binding=target.target_binding,
        target_profile_digest=target.digest,
        control_profile_digest=controls.digest,
        snapshot_digest=snapshot_digest,
        executor_digest=executor_digest,
        run_binding=run_binding,
    )


def result_from_receipt(
    observation: IdentityProfileObservation,
    receipt: dict[str, object],
) -> dict[str, object]:
    return public_result(
        state="applied",
        environment=str(receipt["environment"]),
        observation=observation,
        plan=receipt["plan"],
        effects=receipt["effects"],
        receipt_digest=str(receipt["receipt_digest"]),
        mutation_performed=True,
        approval_verified=True,
        claim_recorded=True,
        readback_verified=True,
    )


def public_result(
    *,
    state: str,
    environment: str,
    observation: IdentityProfileObservation,
    plan: object,
    blockers: tuple[str, ...] = (),
    effects: object | None = None,
    receipt_digest: str | None = None,
    mutation_performed: bool = False,
    approval_verified: bool = False,
    claim_recorded: bool = False,
    readback_verified: bool = False,
) -> dict[str, object]:
    all_blockers = tuple(dict.fromkeys((*observation.blockers, *blockers)))
    result: dict[str, object] = {
        "schema_version": "fdai.genesis-entra-only-result.v2",
        "state": state,
        "environment": environment,
        "identity_profile": observation.to_mapping(),
        "plan": plan,
        "effects": effects,
        "blockers": list(all_blockers),
        "approval_verified": approval_verified,
        "claim_recorded": claim_recorded,
        "readback_verified": readback_verified,
        "provider_admin_consent_granted": False,
        "runner_directory_authority_granted": False,
        "foundation_invoked": False,
        "application_invoked": False,
        "mutation_performed": mutation_performed,
        "subscription_ready": False,
    }
    if receipt_digest is not None:
        result["receipt_digest"] = receipt_digest
    return result


def require_private_directory(path: Path) -> None:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Entra work directory MUST be an absolute non-link path")
    details = path.stat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.geteuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise PermissionError("Entra work directory MUST be current-UID mode 0700")


@contextmanager
def operation_lock(work_dir: Path) -> Iterator[None]:
    path = work_dir / "entra-only.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.geteuid()
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_nlink != 1
        ):
            raise PermissionError("Entra operation lock is unsafe")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another Entra-only operation holds the target lock") from exc
        yield
    finally:
        os.close(descriptor)


def remove_stale_approval(path: Path) -> None:
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
        raise PermissionError("retained Entra approval is unsafe")
    path.unlink()


def descriptor_from_environment(name: str) -> int:
    value = os.environ.pop(name, "")
    if not value.isascii() or not value.isdecimal():
        raise ValueError("private Entra profile descriptor is unavailable")
    descriptor = int(value)
    if descriptor < 3:
        raise ValueError("private Entra profile descriptor is invalid")
    return descriptor


def snapshot_from_environment() -> tuple[Path, str]:
    raw_path = os.environ.pop("FDAI_ENTRA_SNAPSHOT_DIRECTORY", "")
    digest = os.environ.pop("FDAI_ENTRA_SNAPSHOT_DIGEST", "")
    os.environ.pop("FDAI_ENTRA_SNAPSHOT_ROOT", None)
    path = Path(raw_path)
    if not path.is_absolute() or _DIGEST.fullmatch(digest) is None:
        raise ValueError("private Entra snapshot context is invalid")
    return path, digest

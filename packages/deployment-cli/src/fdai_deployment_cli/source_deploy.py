"""Prepare connected source deployments without constructing or trusting a release kit."""

from __future__ import annotations

import fcntl
import os
import re
import stat
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.source_input import inspect_source
from fdai_deployment_cli.source_snapshot import materialize_source, verify_source_snapshot


def prepare_source_deployment(
    *,
    source_root: Path,
    work_dir: Path,
    runtime_profile: RuntimeDeploymentProfile,
    region: str,
    monthly_cost_ceiling: int,
) -> dict[str, object]:
    """Seal and reverify one connected dev source run without cloud access or execution.

    A mode-specific work directory cannot adopt kit state, another source or runtime
    profile. A partial snapshot is retained and blocked rather than silently replaced.
    The receipt proves local preparation only and never grants apply or Trial authority.
    """
    if (
        runtime_profile.runtime_platform.value != "aks"
        or runtime_profile.database_placement.value != "postgres-flex"
    ):
        raise ValueError("source deployment currently requires AKS with postgres-flex")
    if re.fullmatch(r"[a-z][a-z0-9]+", region) is None:
        raise ValueError("source deployment region is invalid")
    if type(monthly_cost_ceiling) is not int or monthly_cost_ceiling <= 0:
        raise ValueError("source deployment cost review ceiling must be positive")
    source = inspect_source(source_root)
    work_dir = work_dir.absolute()
    if work_dir.resolve().is_relative_to(source.root):
        raise ValueError("source deployment work directory must be outside the selected checkout")
    work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    details = work_dir.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.geteuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise ValueError("source work directory must be a private owned directory")
    from fdai_deployment_cli.private_output import _open_private_parent

    parent = _open_private_parent(work_dir / "source.lock")
    try:
        lock = os.open(
            "source.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=parent,
        )
    finally:
        os.close(parent)
    try:
        lock_stat = os.fstat(lock)
        if (
            not stat.S_ISREG(lock_stat.st_mode)
            or lock_stat.st_uid != os.geteuid()
            or lock_stat.st_nlink != 1
            or stat.S_IMODE(lock_stat.st_mode) != 0o600
        ):
            raise ValueError("source deployment lock identity is invalid")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("source deployment preparation is already active") from None
        intent = {
            "schema_version": "fdai.source-deployment-intent.v1",
            "source": source.to_mapping(),
            "source_input_digest": source.digest,
            "runtime_profile": runtime_profile.to_mapping(),
            "environment": "dev",
            "region": region,
            "monthly_cost_ceiling": monthly_cost_ceiling,
        }
        intent_path = work_dir / "source-intent.json"
        if intent_path.exists():
            prior = load_json_object(
                read_private_bytes(intent_path, max_bytes=65_536), label="source intent"
            )
            if prior != intent:
                raise ValueError(
                    "retained source deployment intent differs; preserve the existing run"
                )
        else:
            if {path.name for path in work_dir.iterdir()} != {"source.lock"}:
                raise ValueError("source deployment cannot adopt existing or partial work state")
            write_private_bytes(intent_path, canonical_bytes(intent))
        receipt_path = work_dir / "source-preparation.json"
        snapshot = work_dir / "source-snapshot"
        if receipt_path.exists():
            receipt = load_json_object(
                read_private_bytes(receipt_path, max_bytes=65_536), label="source preparation"
            )
            digest = receipt.pop("receipt_digest", None)
            if canonical_digest(receipt) != digest or receipt.get(
                "intent_digest"
            ) != canonical_digest(intent):
                raise ValueError("source preparation receipt binding is invalid")
            snapshot_digest = receipt.get("source_snapshot_digest")
            if not isinstance(snapshot_digest, str):
                raise ValueError("source snapshot digest is unavailable")
            if (
                verify_source_snapshot(snapshot, expected_digest=snapshot_digest)
                != source.to_mapping()
            ):
                raise ValueError("source snapshot differs from the selected checkout")
        else:
            if snapshot.exists() or snapshot.is_symlink():
                raise ValueError(
                    "incomplete source snapshot requires review; no automatic replacement"
                )
            snapshot_digest = materialize_source(source, snapshot)
        result: dict[str, object] = {
            "schema_version": "fdai.source-deployment-preparation.v1",
            "state": "prepared",
            "provenance": "operator-selected-source",
            "source_commit": source.commit,
            "source_input_digest": source.digest,
            "source_snapshot_digest": snapshot_digest,
            "intent_digest": canonical_digest(intent),
            "runtime_profile_digest": runtime_profile.digest,
            "release_signature_verified": False,
            "apply_authorized": False,
            "mutation_performed": False,
            "deployment_ready": False,
            "subscription_ready": False,
        }
        result["receipt_digest"] = canonical_digest(result)
        source.reverify()
        if not receipt_path.exists():
            write_private_bytes(receipt_path, canonical_bytes(result))
        elif read_private_bytes(receipt_path, max_bytes=65_536) != canonical_bytes(result):
            raise ValueError("retained source preparation receipt differs")
        return result
    finally:
        os.close(lock)

"""Run a bounded local rollup, archive, and restore certification exercise."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

from fdai.core.ontology_platform.archive_manifest import (
    ArchiveManifest,
    ArchiveVerificationReceipt,
    build_archive_manifest,
    verify_archive_manifest,
)
from fdai.core.ontology_platform.archive_retention import (
    ArchiveRestoreReceipt,
    evaluate_restore_sample,
)
from fdai.core.ontology_platform.semantic_rollup import (
    RollupFactKind,
    RollupObservation,
    SemanticRollup,
    SemanticRollupPolicy,
    build_semantic_rollup,
)
from fdai.delivery.inventory_rollup import semantic_rollup_to_archive_partition
from fdai.delivery.operational_instance_certification import (
    OperationalCertificationSnapshot,
)


class OperationalArchiveEvidenceStore(Protocol):
    """Persist immutable archive evidence without exposing purge authority."""

    async def put_manifest(self, manifest: ArchiveManifest) -> bool: ...

    async def append_verification(self, receipt: ArchiveVerificationReceipt) -> bool: ...

    async def append_restore(self, receipt: ArchiveRestoreReceipt) -> bool: ...


@dataclass(frozen=True, slots=True)
class LocalArchiveExerciseReceipt:
    """Record the verified local exercise without granting archive authority."""

    rollup_digest: str
    manifest_digest: str
    verification_digest: str
    restore_digest: str
    artifact_digest: str
    passed: bool
    observation_authority: Literal[False]
    mutation_authority: Literal[False]
    execution_authority: Literal[False]
    digest: str


async def run_local_archive_exercise(
    start: OperationalCertificationSnapshot,
    end: OperationalCertificationSnapshot,
    *,
    artifact_path: Path,
    store: OperationalArchiveEvidenceStore,
) -> LocalArchiveExerciseReceipt:
    """Archive one exact storage gauge rollup and verify a real artifact restore.

    Persistence is append-only and replay-idempotent. A stage failure can leave inert prerequisite
    evidence, but this function emits no exercise receipt until manifest, verification, and restore
    writes all complete successfully.
    """

    if start.ontology_release_digest != end.ontology_release_digest:
        raise ValueError("archive exercise snapshots MUST bind the same ontology release")
    if end.measured_at <= start.measured_at:
        raise ValueError("archive exercise window MUST be positive")
    if end.database_bytes is None:
        raise ValueError("archive exercise database size is unavailable")
    rollup = _build_storage_rollup(start, end)
    artifact = _rollup_artifact(rollup)
    encoded = _canonical_json(artifact).encode("utf-8") + b"\n"
    _write_private_artifact(artifact_path, encoded)
    observed = artifact_path.read_bytes()
    artifact_digest = _sha256_bytes(observed)
    if observed != encoded:
        raise ValueError("archive exercise artifact bytes changed after write")
    partition = semantic_rollup_to_archive_partition(
        rollup,
        partition_id=f"oi12-storage-{rollup.digest[7:39]}",
        schema_version="semantic-rollup-1.0.0",
    )
    creation_receipt_digest = _sha256(
        {
            "artifact_digest": artifact_digest,
            "created_at": end.measured_at.astimezone(UTC).isoformat(),
            "rollup_digest": rollup.digest,
        }
    )
    manifest = build_archive_manifest(
        (partition,),
        archive_content_digest=artifact_digest,
        compression_profile="none",
        encryption_profile="filesystem-mode-0600",
        destination_class="local-private-artifact",
        retention_class="oi12-certification",
        creation_receipt_digest=creation_receipt_digest,
        created_at=end.measured_at,
    )
    verification = verify_archive_manifest(
        manifest,
        observed_archive_content_digest=_sha256_bytes(artifact_path.read_bytes()),
        observed_source_partition_digests=(rollup.digest,),
        observed_source_schema_versions=("semantic-rollup-1.0.0",),
        observed_ontology_release_digests=(rollup.ontology_release_digest,),
        verified_at=end.measured_at,
    )
    restored = json.loads(artifact_path.read_text(encoding="utf-8"))
    restored_digest = restored.get("rollup_digest") if isinstance(restored, dict) else None
    restore = evaluate_restore_sample(
        manifest,
        verification,
        sampled_partition_digests=(rollup.digest,),
        observed_partition_digests=((restored_digest,) if isinstance(restored_digest, str) else ()),
        restored_object_count=1 if restored_digest == rollup.digest else 0,
        restored_relationship_count=0,
        failure_code=None if restored_digest == rollup.digest else "artifact_invalid",
        sampled_at=end.measured_at,
    )
    await store.put_manifest(manifest)
    await store.append_verification(verification)
    await store.append_restore(restore)
    body = {
        "rollup_digest": rollup.digest,
        "manifest_digest": manifest.digest,
        "verification_digest": verification.digest,
        "restore_digest": restore.digest,
        "artifact_digest": artifact_digest,
        "passed": verification.verified and restore.passed,
        "observation_authority": False,
        "mutation_authority": False,
        "execution_authority": False,
    }
    return LocalArchiveExerciseReceipt(
        rollup_digest=rollup.digest,
        manifest_digest=manifest.digest,
        verification_digest=verification.digest,
        restore_digest=restore.digest,
        artifact_digest=artifact_digest,
        passed=verification.verified and restore.passed,
        observation_authority=False,
        mutation_authority=False,
        execution_authority=False,
        digest=_sha256(body),
    )


def _build_storage_rollup(
    start: OperationalCertificationSnapshot,
    end: OperationalCertificationSnapshot,
) -> SemanticRollup:
    database_bytes = end.database_bytes
    if database_bytes is None:
        raise ValueError("archive exercise database size is unavailable")
    elapsed_seconds = max(1, math.ceil((end.measured_at - start.measured_at).total_seconds()))
    policy = SemanticRollupPolicy(
        semantic_id="operational.database.bytes",
        revision="oi12-local-v1",
        ontology_release_digest=end.ontology_release_digest,
        fact_kind=RollupFactKind.GAUGE,
        expected_interval_seconds=elapsed_seconds,
        statistics=("count", "sum", "minimum", "maximum", "average"),
    )
    observation = RollupObservation(
        observation_id=end.digest,
        semantic_id=policy.semantic_id,
        fact_kind=policy.fact_kind,
        source_id="postgres-aggregate",
        source_revision="oi12-local-v1",
        source_partition_digest=end.digest,
        generation_ref=f"oi12:{start.digest[7:23]}:{end.digest[7:23]}",
        ontology_release_digest=end.ontology_release_digest,
        interval_start=start.measured_at,
        interval_end=end.measured_at,
        effective_at=end.measured_at,
        event_at=end.measured_at,
        recorded_at=end.measured_at,
        value=Decimal(database_bytes),
        complete=True,
        conflict_count=0,
    )
    return build_semantic_rollup(
        policy,
        (observation,),
        window_start=start.measured_at,
        window_end=end.measured_at,
    )


def _rollup_artifact(rollup: SemanticRollup) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "kind": "oi12-storage-rollup",
        "semantic_id": rollup.semantic_id,
        "ontology_release_digest": rollup.ontology_release_digest,
        "window_start": rollup.window_start.astimezone(UTC).isoformat(),
        "window_end": rollup.window_end.astimezone(UTC).isoformat(),
        "statistics": json.loads(rollup.statistics_json),
        "complete": rollup.complete,
        "rollup_digest": rollup.digest,
    }


def _write_private_artifact(path: Path, encoded: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


__all__ = [
    "LocalArchiveExerciseReceipt",
    "OperationalArchiveEvidenceStore",
    "run_local_archive_exercise",
]

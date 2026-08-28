"""Governed producer for O7 live-shadow evidence batches."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from fdai.core.measurement import (
    OperationalPromotionBatch,
    OperationalPromotionRecord,
    PromotionEvidenceCohort,
)
from fdai.delivery.measurement.operational_promotion_evidence import (
    OperationalPromotionEvidenceManifest,
)

_MAX_OUTPUT_BYTES = 16 * 1024 * 1024


class OperationalPromotionLiveRecordSource(Protocol):
    """Deployment-owned read source for already audited live observations."""

    async def load_records(
        self,
        *,
        action_type_name: str,
        fdai_revision: str,
        scenario_set_version: str,
    ) -> Sequence[OperationalPromotionRecord]: ...


@dataclass(frozen=True, slots=True)
class OperationalPromotionBatchArtifact:
    """Materialized batch and manifest consumed by the existing O7 runner."""

    batch: OperationalPromotionBatch
    batch_path: Path
    manifest_path: Path
    manifest: OperationalPromotionEvidenceManifest


class GovernedLiveBatchProducer:
    """Seal live-shadow records without modifying promotion authority.

    Records are read from an injected, deployment-owned source and are
    restricted to the declared ActionType, revision, scenario, and live-shadow
    cohort. The producer writes only evidence files; it never calls an
    ActionPromotionRegistry or changes execution mode.
    """

    def __init__(
        self,
        *,
        source: OperationalPromotionLiveRecordSource,
        output_dir: Path,
        benchmark_records: Sequence[OperationalPromotionRecord] = (),
        clock: object = None,
    ) -> None:
        self._source = source
        self._output_dir = output_dir
        self._benchmark_records = tuple(benchmark_records)
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def produce(
        self,
        *,
        action_type_name: str,
        action_type_version: str,
        action_type_digest: str,
        fdai_revision: str,
        scenario_set_version: str,
    ) -> OperationalPromotionBatchArtifact:
        """Read, validate, seal, and publish one exact-digest live batch."""
        live_records = tuple(
            await self._source.load_records(
                action_type_name=action_type_name,
                fdai_revision=fdai_revision,
                scenario_set_version=scenario_set_version,
            )
        )
        if not live_records:
            raise ValueError("live operational promotion batch MUST contain records")
        if any(record.cohort is not PromotionEvidenceCohort.LIVE_SHADOW for record in live_records):
            raise ValueError("live operational promotion batch MUST contain live-shadow records")
        if not self._benchmark_records:
            raise ValueError(
                "live operational promotion batch requires immutable benchmark records"
            )
        if any(
            record.cohort is not PromotionEvidenceCohort.FROZEN_BENCHMARK
            for record in self._benchmark_records
        ):
            raise ValueError("benchmark records MUST use the frozen-benchmark cohort")
        records = (*self._benchmark_records, *live_records)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        stem = _safe_name(action_type_name)
        batch_path = self._output_dir / f"{stem}.batch.json"
        manifest_path = self._output_dir / f"{stem}.manifest.json"
        with _publish_lock(self._output_dir, stem):
            # A retry (same identity, re-run after a transient failure) MUST
            # reuse the sealed_at an already-published batch pinned instead
            # of recomputing a fresh timestamp: otherwise every retry mints
            # byte-different content and the exclusive publish below treats
            # its own prior attempt as an unrelated conflict.
            sealed_at = _existing_sealed_at(batch_path) or _aware_now(self._clock)
            batch = OperationalPromotionBatch(
                fdai_revision=fdai_revision,
                scenario_set_version=scenario_set_version,
                action_type_name=action_type_name,
                action_type_version=action_type_version,
                action_type_digest=action_type_digest,
                sealed_at=sealed_at,
                records=records,
            )
            batch_mapping = _batch_mapping(batch)
            batch_bytes = json.dumps(batch_mapping, separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            )
            if len(batch_bytes) > _MAX_OUTPUT_BYTES:
                raise ValueError("live operational promotion batch exceeds its byte limit")
            manifest_mapping = _manifest_mapping(batch, batch_path.name)
            manifest_bytes = json.dumps(
                manifest_mapping, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
            # Published as a locked pair: the batch and the manifest that
            # attests it become durable together (each write is itself an
            # atomic rename), and the lock stops a concurrent publish for
            # the same ActionType from observing one half without the other.
            _publish_exclusive(batch_path, batch_bytes, kind="batch")
            _publish_exclusive(manifest_path, manifest_bytes, kind="manifest")
        manifest = OperationalPromotionEvidenceManifest.load(manifest_path)
        return OperationalPromotionBatchArtifact(
            batch=batch,
            batch_path=batch_path,
            manifest_path=manifest_path,
            manifest=manifest,
        )


def _batch_mapping(batch: OperationalPromotionBatch) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "fdai_revision": batch.fdai_revision,
        "scenario_set_version": batch.scenario_set_version,
        "action_type_name": batch.action_type_name,
        "action_type_version": batch.action_type_version,
        "action_type_digest": batch.action_type_digest,
        "sealed_at": batch.sealed_at.astimezone(UTC).isoformat(),
        "records": [_record_mapping(record) for record in batch.records],
    }


def _record_mapping(record: OperationalPromotionRecord) -> dict[str, object]:
    causal = record.causal_receipt
    return {
        "sample_id": record.sample_id,
        "measurement_unit_id": record.measurement_unit_id,
        "audit_sequence": record.audit_sequence,
        "action_type_name": record.action_type_name,
        "action_type_version": record.action_type_version,
        "action_type_digest": record.action_type_digest,
        "fdai_revision": record.fdai_revision,
        "scenario_set_version": record.scenario_set_version,
        "scenario_case_id": record.scenario_case_id,
        "cohort": record.cohort.value,
        "observed_at": record.observed_at.astimezone(UTC).isoformat(),
        "correct": record.correct,
        "policy_escape": record.policy_escape,
        "executed": record.executed,
        "rolled_back": record.rolled_back,
        "recurrence_window_complete": record.recurrence_window_complete,
        "recurrence": record.recurrence,
        "causal_receipt": {
            "hypothesis_id": causal.hypothesis_id,
            "hypothesis_revision_digest": causal.hypothesis_revision_digest,
            "evidence_grade": causal.evidence_grade.value,
            "status": causal.status,
            "closure": causal.closure,
        },
        "simulation_requires_review": record.simulation_requires_review,
        "evidence_refs": list(record.evidence_refs),
    }


def _manifest_mapping(batch: OperationalPromotionBatch, batch_name: str) -> dict[str, object]:
    records = batch.records
    unit_refs: dict[str, tuple[str, ...]] = {}
    for record in records:
        prior = unit_refs.setdefault(record.measurement_unit_id, record.evidence_refs)
        if prior != record.evidence_refs:
            raise ValueError(
                "live operational promotion corrections MUST preserve evidence references"
            )
    return {
        "schema_version": "1.0.0",
        "batches": [
            {
                "action_type_name": batch.action_type_name,
                "path": batch_name,
                "content_digest": batch.content_digest,
            }
        ],
        "causal_receipt_digests": [record.causal_receipt.content_digest for record in records],
        "unit_evidence_refs": {unit_id: list(refs) for unit_id, refs in unit_refs.items()},
    }


def _publish_exclusive(path: Path, content: bytes, *, kind: str) -> None:
    """Publish ``content`` at ``path`` with an atomic same-filesystem rename.

    Existing byte-identical content is treated as an already-completed
    publish (idempotent retry, no-op). Existing content that differs is a
    real conflict - a different logical batch, not merely a retried
    timestamp - and fails closed instead of silently overwriting evidence.
    """
    if path.exists():
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"live operational promotion {kind} path is not a plain file")
        if path.read_bytes() == content:
            return
        raise ValueError(f"live operational promotion {kind} already exists with different content")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _existing_sealed_at(batch_path: Path) -> datetime | None:
    """Read a previously published batch's ``sealed_at`` for retry reuse."""
    if not batch_path.is_file() or batch_path.is_symlink():
        return None
    try:
        raw = json.loads(batch_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    sealed_at = raw.get("sealed_at")
    if not isinstance(sealed_at, str):
        return None
    try:
        parsed = datetime.fromisoformat(sealed_at)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


@contextmanager
def _publish_lock(output_dir: Path, stem: str) -> Iterator[None]:
    """Serialize concurrent batch+manifest publishes for one ActionType."""
    output_dir.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output_dir / f".{stem}.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _safe_name(value: str) -> str:
    if not value or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for character in value
    ):
        raise ValueError("action_type_name MUST be a safe file identifier")
    return value


def _aware_now(clock: object) -> datetime:
    value = clock()  # type: ignore[operator]
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("live batch clock MUST return a timezone-aware datetime")
    return value.astimezone(UTC)


__all__ = [
    "GovernedLiveBatchProducer",
    "OperationalPromotionBatchArtifact",
    "OperationalPromotionLiveRecordSource",
]

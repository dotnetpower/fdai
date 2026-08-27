"""Governed producer for O7 live-shadow evidence batches."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
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
        batch = OperationalPromotionBatch(
            fdai_revision=fdai_revision,
            scenario_set_version=scenario_set_version,
            action_type_name=action_type_name,
            action_type_version=action_type_version,
            action_type_digest=action_type_digest,
            sealed_at=_aware_now(self._clock),
            records=records,
        )
        self._output_dir.mkdir(parents=True, exist_ok=True)
        stem = _safe_name(action_type_name)
        batch_path = self._output_dir / f"{stem}.batch.json"
        manifest_path = self._output_dir / f"{stem}.manifest.json"
        batch_mapping = _batch_mapping(batch)
        manifest_mapping = _manifest_mapping(batch, batch_path.name)
        batch_bytes = json.dumps(batch_mapping, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        if len(batch_bytes) > _MAX_OUTPUT_BYTES:
            raise ValueError("live operational promotion batch exceeds its byte limit")
        _write_exclusive(batch_path, batch_bytes)
        manifest_bytes = json.dumps(manifest_mapping, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        _write_exclusive(manifest_path, manifest_bytes)
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


def _write_exclusive(path: Path, content: bytes) -> None:
    if path.exists():
        if not path.is_file() or path.is_symlink() or path.read_bytes() != content:
            raise ValueError(
                "live operational promotion artifact already exists with different content"
            )
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(content)
    finally:
        if descriptor >= 0:
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

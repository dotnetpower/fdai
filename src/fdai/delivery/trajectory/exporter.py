"""Deterministic streaming JSONL trajectory exporter."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import AsyncIterable, Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from fdai.core.trajectory.models import TRAJECTORY_SCHEMA_VERSION, TrajectoryEnvelope
from fdai.core.trajectory.scanning import ScanFinding, scan_envelope
from fdai.core.trajectory.serialization import canonical_json_bytes, envelope_to_mapping
from fdai.core.trajectory.versioning import TrajectoryVersionPolicy


class ExportStatus(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class ExportQuarantineRecord:
    dataset_id: str
    trajectory_id: str
    findings: tuple[ScanFinding, ...]


class ExportQuarantineStore(Protocol):
    async def put(self, record: ExportQuarantineRecord) -> None: ...


@dataclass(frozen=True, slots=True)
class TrajectoryExportResult:
    dataset_id: str
    status: ExportStatus
    record_count: int
    dataset_checksum: str | None = None
    manifest_checksum: str | None = None


class TrajectoryJsonlExporter:
    """Stream canonical records and atomically publish data plus manifest."""

    def __init__(self, *, quarantine: ExportQuarantineStore) -> None:
        self._quarantine = quarantine

    async def export(
        self,
        *,
        dataset_id: str,
        records: AsyncIterable[TrajectoryEnvelope],
        output_path: Path,
        purpose: str,
        principal_scope_digest: str,
        is_cancelled: Callable[[], bool] = lambda: False,
    ) -> TrajectoryExportResult:
        if not output_path.name.endswith(".trajectory.jsonl"):
            raise ValueError("trajectory export path MUST end with .trajectory.jsonl")
        partial_path = output_path.with_name(output_path.name + ".partial")
        manifest_path = output_path.with_name(output_path.name + ".manifest.json")
        manifest_partial = manifest_path.with_name(manifest_path.name + ".partial")
        if output_path.exists() or manifest_path.exists():
            raise FileExistsError("trajectory export final path already exists")
        _cleanup(partial_path, manifest_partial)
        dataset_hasher = hashlib.sha256()
        outcomes: Counter[str] = Counter()
        record_count = 0
        data_published = False
        try:
            with partial_path.open("xb") as stream:
                async for record in records:
                    if is_cancelled():
                        return _cancelled(dataset_id, record_count, partial_path, manifest_partial)
                    TrajectoryVersionPolicy().require_current(record.schema_version)
                    if record.governance.purpose != purpose:
                        raise ValueError("trajectory record purpose does not match export purpose")
                    if record.principal_scope_digest != principal_scope_digest:
                        raise ValueError("trajectory record scope does not match export scope")
                    findings = scan_envelope(record)
                    if findings:
                        await self._quarantine.put(
                            ExportQuarantineRecord(dataset_id, record.trajectory_id, findings)
                        )
                        _cleanup(partial_path, manifest_partial)
                        return TrajectoryExportResult(
                            dataset_id, ExportStatus.QUARANTINED, record_count
                        )
                    record_raw = envelope_to_mapping(record)
                    checksum = hashlib.sha256(canonical_json_bytes(record_raw)).hexdigest()
                    line = (
                        canonical_json_bytes({"checksum": checksum, "record": record_raw}) + b"\n"
                    )
                    stream.write(line)
                    dataset_hasher.update(line)
                    outcomes[record.completion_status.value] += 1
                    record_count += 1
            if is_cancelled():
                return _cancelled(dataset_id, record_count, partial_path, manifest_partial)
            if record_count == 0:
                _cleanup(partial_path, manifest_partial)
                raise ValueError("trajectory export MUST contain at least one record")
            manifest = {
                "dataset_id": dataset_id,
                "schema_version": TRAJECTORY_SCHEMA_VERSION,
                "purpose": purpose,
                "principal_scope_digest": principal_scope_digest,
                "record_count": record_count,
                "outcome_counts": dict(sorted(outcomes.items())),
                "dataset_checksum": dataset_hasher.hexdigest(),
            }
            manifest_checksum = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
            manifest["manifest_checksum"] = manifest_checksum
            manifest_partial.write_bytes(canonical_json_bytes(manifest) + b"\n")
            partial_path.replace(output_path)
            data_published = True
            manifest_partial.replace(manifest_path)
            return TrajectoryExportResult(
                dataset_id,
                ExportStatus.COMPLETED,
                record_count,
                dataset_hasher.hexdigest(),
                manifest_checksum,
            )
        except BaseException:
            _cleanup(partial_path, manifest_partial)
            if data_published:
                _cleanup(output_path)
            raise


def _cancelled(
    dataset_id: str,
    record_count: int,
    partial_path: Path,
    manifest_partial: Path,
) -> TrajectoryExportResult:
    _cleanup(partial_path, manifest_partial)
    return TrajectoryExportResult(dataset_id, ExportStatus.CANCELLED, record_count)


def _cleanup(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


__all__ = [
    "ExportQuarantineRecord",
    "ExportQuarantineStore",
    "ExportStatus",
    "TrajectoryExportResult",
    "TrajectoryJsonlExporter",
]

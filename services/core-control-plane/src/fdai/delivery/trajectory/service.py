"""End-to-end trajectory JSONL export and metadata persistence."""

from __future__ import annotations

from collections.abc import AsyncIterable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fdai.core.trajectory import TRAJECTORY_SCHEMA_VERSION, TrajectoryEnvelope
from fdai.delivery.trajectory.exporter import (
    ExportStatus,
    TrajectoryExportResult,
    TrajectoryJsonlExporter,
)
from fdai.shared.providers.trajectory import (
    TrajectoryDatasetRecord,
    TrajectoryDatasetState,
    TrajectoryDatasetStore,
)


@dataclass(frozen=True, slots=True)
class TrajectoryDatasetExportRequest:
    dataset_id: str
    purpose: str
    access_scope: str
    principal_scope_digest: str
    output_path: Path
    created_at: datetime
    retention_until: datetime
    deletion_due_at: datetime
    legal_hold: bool = False
    legal_hold_ref: str | None = None


class TrajectoryDatasetExportService:
    """Publish one dataset and persist its terminal metadata exactly once."""

    def __init__(
        self,
        *,
        exporter: TrajectoryJsonlExporter,
        store: TrajectoryDatasetStore,
    ) -> None:
        self._exporter = exporter
        self._store = store

    async def export(
        self,
        request: TrajectoryDatasetExportRequest,
        *,
        records: AsyncIterable[TrajectoryEnvelope],
        is_cancelled: Callable[[], bool] = lambda: False,
    ) -> TrajectoryDatasetRecord:
        result = await self._exporter.export(
            dataset_id=request.dataset_id,
            records=records,
            output_path=request.output_path,
            purpose=request.purpose,
            principal_scope_digest=request.principal_scope_digest,
            is_cancelled=is_cancelled,
        )
        record = _metadata(request, result)
        try:
            return await self._store.put(record)
        except BaseException:
            if result.status is ExportStatus.COMPLETED:
                _cleanup_published(request.output_path)
            raise


def _metadata(
    request: TrajectoryDatasetExportRequest,
    result: TrajectoryExportResult,
) -> TrajectoryDatasetRecord:
    completed = result.status is ExportStatus.COMPLETED
    return TrajectoryDatasetRecord(
        dataset_id=request.dataset_id,
        purpose=request.purpose,
        access_scope=request.access_scope,
        principal_scope_digest=request.principal_scope_digest,
        state=TrajectoryDatasetState(result.status.value),
        schema_version=TRAJECTORY_SCHEMA_VERSION,
        storage_ref=str(request.output_path) if completed else None,
        record_count=result.record_count,
        dataset_checksum=result.dataset_checksum,
        manifest_checksum=result.manifest_checksum,
        created_at=request.created_at,
        retention_until=request.retention_until,
        deletion_due_at=request.deletion_due_at,
        legal_hold=request.legal_hold,
        legal_hold_ref=request.legal_hold_ref,
    )


def _cleanup_published(output_path: Path) -> None:
    output_path.unlink(missing_ok=True)
    output_path.with_name(output_path.name + ".manifest.json").unlink(missing_ok=True)


__all__ = ["TrajectoryDatasetExportRequest", "TrajectoryDatasetExportService"]

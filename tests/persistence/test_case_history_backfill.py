from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.case_history import CaseHistoryMaterializer, CaseSourceRecord
from fdai.core.case_history.testing import (
    InMemoryCaseHistoryArtifactStore,
    InMemoryCaseHistoryMetadataStore,
)
from fdai.delivery.persistence.case_history_backfill import CaseHistoryBackfillService
from tests.core.case_history.test_operational_case import _case_input
from tests.core.case_history.test_service import _outcome

NOW = datetime(2026, 7, 23, tzinfo=UTC)


class _Source:
    def __init__(self, records: tuple[object, ...]) -> None:
        self._records = records
        self._read = False

    async def page_after(self, *, cursor: str | None, limit: int):  # type: ignore[no-untyped-def]
        del cursor, limit
        if self._read:
            return (), None
        self._read = True
        return self._records, "case-history:latest:last"


class _Destination(InMemoryCaseHistoryMetadataStore):
    def __init__(self) -> None:
        super().__init__()
        self.mismatch_count: int | None = None

    async def record_backfill_result(self, *, mismatch_count: int, verified_at: datetime) -> None:
        assert verified_at == NOW
        self.mismatch_count = mismatch_count

    async def backfill_tombstone(self, record):  # type: ignore[no-untyped-def]
        self._records.setdefault(record.case_id, []).append(record)
        return True


async def test_backfill_reconstructs_full_revision_chain_and_verifies_parity() -> None:
    source_metadata = InMemoryCaseHistoryMetadataStore()
    artifacts = InMemoryCaseHistoryArtifactStore()
    materializer = CaseHistoryMaterializer(metadata=source_metadata, artifacts=artifacts)
    outcome = _outcome()
    first = await materializer.seal_forecast_outcome(
        outcome,
        purpose="forecast-error-analysis",
        redaction_policy_version="1.0.0",
        retention_until=outcome.closed_at + timedelta(days=30),
        deletion_due_at=outcome.closed_at + timedelta(days=60),
    )
    source = CaseSourceRecord(
        record_type="postmortem",
        record_id="review-1",
        record_digest="e" * 64,
        occurred_at=outcome.closed_at + timedelta(hours=1),
        payload={"finding": "seasonal mismatch"},
    )
    latest = await materializer.seal_forecast_outcome(
        outcome,
        purpose="forecast-error-analysis",
        redaction_policy_version="1.0.0",
        retention_until=outcome.closed_at + timedelta(days=30),
        deletion_due_at=outcome.closed_at + timedelta(days=60),
        additional_sources=(source,),
    )
    assert latest.revision == first.revision + 1
    destination = _Destination()
    report = await CaseHistoryBackfillService(
        source=_Source((latest,)),  # type: ignore[arg-type]
        destination=destination,  # type: ignore[arg-type]
        artifacts=artifacts,
    ).run(now=NOW)
    assert report.scanned == report.migrated == 1
    assert report.mismatches == 0
    assert destination.mismatch_count == 0
    assert (
        await destination.latest(latest.case_id, access_scope_digest=latest.access_scope_digest)
        == latest
    )


async def test_deleted_case_tombstone_is_preserved_for_cutover() -> None:
    artifacts = InMemoryCaseHistoryArtifactStore()
    destination = _Destination()
    deleted = replace(
        (await _seed_latest(artifacts)),
        storage_ref=None,
        artifact_size=0,
        deleted_at=NOW,
    )
    report = await CaseHistoryBackfillService(
        source=_Source((deleted,)),  # type: ignore[arg-type]
        destination=destination,  # type: ignore[arg-type]
        artifacts=artifacts,
    ).run(now=NOW)
    assert report.migrated == 1
    assert report.excluded == 0
    assert report.mismatches == 0
    assert destination.mismatch_count == 0
    assert (
        await destination.latest(deleted.case_id, access_scope_digest=deleted.access_scope_digest)
        == deleted
    )


async def test_backfill_preserves_operational_metadata_without_forecast_placeholders() -> None:
    source_metadata = InMemoryCaseHistoryMetadataStore()
    artifacts = InMemoryCaseHistoryArtifactStore()
    materializer = CaseHistoryMaterializer(metadata=source_metadata, artifacts=artifacts)
    case_input = _case_input()
    latest = (
        await materializer.seal_operational_case(
            case_input,
            retention_until=case_input.event_time_cutoff + timedelta(days=30),
            deletion_due_at=case_input.event_time_cutoff + timedelta(days=60),
        )
    ).record
    destination = _Destination()

    report = await CaseHistoryBackfillService(
        source=_Source((latest,)),  # type: ignore[arg-type]
        destination=destination,  # type: ignore[arg-type]
        artifacts=artifacts,
    ).run(now=NOW)

    assert report.mismatches == 0
    mirrored = await destination.latest(
        latest.case_id,
        access_scope_digest=latest.access_scope_digest,
    )
    assert mirrored == latest
    assert mirrored is not None
    assert mirrored.detector_id is mirrored.detector_version is mirrored.metric is None
    assert dict(mirrored.metadata)["action_type"] == "ops.restart-service"


async def _seed_latest(artifacts: InMemoryCaseHistoryArtifactStore):  # type: ignore[no-untyped-def]
    metadata = InMemoryCaseHistoryMetadataStore()
    outcome = _outcome()
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    return await materializer.seal_forecast_outcome(
        outcome,
        purpose="forecast-error-analysis",
        redaction_policy_version="1.0.0",
        retention_until=outcome.closed_at + timedelta(days=10),
        deletion_due_at=NOW,
    )

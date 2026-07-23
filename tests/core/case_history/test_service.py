from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from fdai.core.case_history import (
    CaseHistoryMaterializer,
    CaseHistoryRetentionService,
    CaseSourceRecord,
)
from fdai.core.case_history.testing import (
    InMemoryCaseHistoryArtifactStore,
    InMemoryCaseHistoryMetadataStore,
)
from fdai.shared.contracts.models import ForecastOutcome
from fdai.shared.providers.case_history import CaseHistoryRevisionRecord

T0 = datetime(2026, 7, 1, tzinfo=UTC)
SCOPE = "a" * 64


def _outcome(**overrides: object) -> ForecastOutcome:
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "outcome_id": UUID(int=1),
        "idempotency_key": "forecast-outcome-1",
        "correlation_id": "corr-1",
        "prediction_id": UUID(int=2),
        "detector_id": "capacity-linear",
        "detector_version": "1.0.0",
        "access_scope_digest": SCOPE,
        "target_digest": "b" * 64,
        "metric": "capacity_percent",
        "feature_cutoff": T0,
        "horizon_started_at": T0,
        "horizon_ended_at": T0 + timedelta(hours=1),
        "direction": "rising",
        "threshold": 90.0,
        "predicted_value": 95.0,
        "interval_lower": 91.0,
        "interval_upper": 99.0,
        "observed_value": 70.0,
        "actual_breach_at": None,
        "label": "false_positive",
        "evidence_refs": ["metric-window:1"],
        "telemetry_completeness": "complete",
        "closed_at": T0 + timedelta(hours=2),
        "mode": "shadow",
    }
    payload.update(overrides)
    return ForecastOutcome.model_validate(payload)


async def _seal(
    service: CaseHistoryMaterializer,
    *,
    sources: tuple[CaseSourceRecord, ...] = (),
) -> CaseHistoryRevisionRecord:
    return await service.seal_forecast_outcome(
        _outcome(),
        purpose="forecast-error-analysis",
        redaction_policy_version="1.0.0",
        retention_until=T0 + timedelta(days=30),
        deletion_due_at=T0 + timedelta(days=60),
        additional_sources=sources,
    )


async def test_duplicate_delivery_reuses_one_revision() -> None:
    metadata = InMemoryCaseHistoryMetadataStore()
    artifacts = InMemoryCaseHistoryArtifactStore()
    service = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    first = await _seal(service)
    second = await _seal(service)
    assert first == second
    assert second.revision == 1
    assert first.storage_ref is not None
    assert await artifacts.get(first.storage_ref) is not None


async def test_same_prediction_isolated_by_purpose() -> None:
    metadata = InMemoryCaseHistoryMetadataStore()
    service = CaseHistoryMaterializer(
        metadata=metadata,
        artifacts=InMemoryCaseHistoryArtifactStore(),
    )
    first = await _seal(service)
    second = await service.seal_forecast_outcome(
        _outcome(),
        purpose="forecast-governance-review",
        redaction_policy_version="1.0.0",
        retention_until=T0 + timedelta(days=30),
        deletion_due_at=T0 + timedelta(days=60),
    )
    assert first.case_id != second.case_id
    assert second.revision == 1


async def test_late_evidence_creates_parent_linked_revision() -> None:
    metadata = InMemoryCaseHistoryMetadataStore()
    service = CaseHistoryMaterializer(
        metadata=metadata,
        artifacts=InMemoryCaseHistoryArtifactStore(),
    )
    first = await _seal(service)
    extra = CaseSourceRecord(
        record_type="postmortem",
        record_id="review-1",
        record_digest="c" * 64,
        occurred_at=T0 + timedelta(hours=3),
        payload={"finding": "seasonal baseline mismatch"},
    )
    second = await _seal(service, sources=(extra,))
    assert second.revision == 2
    assert second.parent_manifest_digest == first.manifest_digest


async def test_revision_rejects_changed_digest_for_existing_source_identity() -> None:
    metadata = InMemoryCaseHistoryMetadataStore()
    service = CaseHistoryMaterializer(
        metadata=metadata,
        artifacts=InMemoryCaseHistoryArtifactStore(),
    )
    await _seal(service)
    with pytest.raises(ValueError, match="preserve prior source evidence"):
        await service.seal_forecast_outcome(
            _outcome(label="intervention_censored", intervention_refs=("action:1",)),
            purpose="forecast-error-analysis",
            redaction_policy_version="1.0.0",
            retention_until=T0 + timedelta(days=30),
            deletion_due_at=T0 + timedelta(days=60),
        )


async def test_revision_rejects_dropped_prior_source() -> None:
    metadata = InMemoryCaseHistoryMetadataStore()
    service = CaseHistoryMaterializer(
        metadata=metadata,
        artifacts=InMemoryCaseHistoryArtifactStore(),
    )
    extra = CaseSourceRecord(
        record_type="postmortem",
        record_id="review-1",
        record_digest="c" * 64,
        occurred_at=T0 + timedelta(hours=3),
        payload={"finding": "seasonal baseline mismatch"},
    )
    await _seal(service, sources=(extra,))
    replacement = CaseSourceRecord(
        record_type="review",
        record_id="review-2",
        record_digest="d" * 64,
        occurred_at=T0 + timedelta(hours=4),
        payload={"finding": "new evidence"},
    )
    with pytest.raises(ValueError, match="preserve prior source evidence"):
        await _seal(service, sources=(replacement,))


async def test_cross_scope_latest_is_not_visible() -> None:
    metadata = InMemoryCaseHistoryMetadataStore()
    service = CaseHistoryMaterializer(
        metadata=metadata,
        artifacts=InMemoryCaseHistoryArtifactStore(),
    )
    record = await _seal(service)
    assert await metadata.latest(record.case_id, access_scope_digest="d" * 64) is None


async def test_same_prediction_isolated_into_distinct_scope_case_ids() -> None:
    metadata = InMemoryCaseHistoryMetadataStore()
    service = CaseHistoryMaterializer(
        metadata=metadata,
        artifacts=InMemoryCaseHistoryArtifactStore(),
    )
    first = await _seal(service)
    second = await service.seal_forecast_outcome(
        _outcome(access_scope_digest="d" * 64),
        purpose="forecast-error-analysis",
        redaction_policy_version="1.0.0",
        retention_until=T0 + timedelta(days=30),
        deletion_due_at=T0 + timedelta(days=60),
    )
    assert first.case_id != second.case_id
    assert await metadata.latest(first.case_id, access_scope_digest=SCOPE) == first
    assert await metadata.latest(second.case_id, access_scope_digest="d" * 64) == second


async def test_artifact_store_rejects_wrong_digest() -> None:
    artifacts = InMemoryCaseHistoryArtifactStore()
    with pytest.raises(ValueError, match="digest mismatch"):
        await artifacts.put("case-history/x", b"content", digest="0" * 64)


async def test_duplicate_evidence_rejects_governance_drift() -> None:
    service = CaseHistoryMaterializer(
        metadata=InMemoryCaseHistoryMetadataStore(),
        artifacts=InMemoryCaseHistoryArtifactStore(),
    )
    await _seal(service)
    with pytest.raises(ValueError, match="governance cannot change"):
        await service.seal_forecast_outcome(
            _outcome(),
            purpose="forecast-error-analysis",
            redaction_policy_version="1.0.0",
            retention_until=T0 + timedelta(days=31),
            deletion_due_at=T0 + timedelta(days=60),
        )


async def test_retention_deletes_artifact_then_tombstones_metadata() -> None:
    metadata = InMemoryCaseHistoryMetadataStore()
    artifacts = InMemoryCaseHistoryArtifactStore()
    service = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    record = await _seal(service)
    retention = CaseHistoryRetentionService(metadata=metadata, artifacts=artifacts)
    assert await retention.delete_due(now=record.deletion_due_at) == (record.case_id,)
    assert await artifacts.get(record.storage_ref or "") is None
    tombstone = await metadata.latest(record.case_id, access_scope_digest=SCOPE)
    assert tombstone is not None
    assert tombstone.storage_ref is None


async def test_metadata_failure_removes_newly_created_artifact() -> None:
    class _RejectingMetadata(InMemoryCaseHistoryMetadataStore):
        async def append_revision(self, record):  # type: ignore[no-untyped-def]
            raise ValueError("metadata conflict")

    artifacts = InMemoryCaseHistoryArtifactStore()
    service = CaseHistoryMaterializer(
        metadata=_RejectingMetadata(),
        artifacts=artifacts,
    )
    with pytest.raises(ValueError, match="metadata conflict"):
        await _seal(service)

    expected_case_id = f"prediction-{_outcome().prediction_id}-"
    assert all(
        not key.startswith(f"case-history/{expected_case_id}/")
        for key in artifacts._records  # noqa: SLF001 - cleanup contract assertion
    )


async def test_ambiguous_metadata_commit_preserves_committed_artifact() -> None:
    class _CommitThenTimeout(InMemoryCaseHistoryMetadataStore):
        async def append_revision(self, record):  # type: ignore[no-untyped-def]
            await super().append_revision(record)
            raise TimeoutError("metadata response lost")

    metadata = _CommitThenTimeout()
    artifacts = InMemoryCaseHistoryArtifactStore()
    service = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    record = await _seal(service)
    assert await metadata.latest(record.case_id, access_scope_digest=SCOPE) == record
    assert record.storage_ref is not None
    assert await artifacts.get(record.storage_ref) is not None


async def test_unverifiable_metadata_commit_preserves_artifact_and_both_errors() -> None:
    class _CommitThenUnavailable(InMemoryCaseHistoryMetadataStore):
        def __init__(self) -> None:
            super().__init__()
            self.latest_calls = 0

        async def append_revision(self, record):  # type: ignore[no-untyped-def]
            await super().append_revision(record)
            raise TimeoutError("metadata response lost")

        async def latest(self, case_id, *, access_scope_digest):  # type: ignore[no-untyped-def]
            self.latest_calls += 1
            if self.latest_calls > 1:
                raise ConnectionError("metadata verification unavailable")
            return await super().latest(case_id, access_scope_digest=access_scope_digest)

    metadata = _CommitThenUnavailable()
    artifacts = InMemoryCaseHistoryArtifactStore()
    service = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    with pytest.raises(ExceptionGroup) as captured:
        await _seal(service)

    assert [str(error) for error in captured.value.exceptions] == [
        "metadata response lost",
        "metadata verification unavailable",
    ]
    assert len(artifacts._records) == 1  # noqa: SLF001 - ambiguity preservation assertion


async def test_metadata_and_cleanup_failures_are_both_reported() -> None:
    class _RejectingMetadata(InMemoryCaseHistoryMetadataStore):
        async def append_revision(self, record):  # type: ignore[no-untyped-def]
            raise ValueError("metadata conflict")

    class _CleanupFailureArtifacts(InMemoryCaseHistoryArtifactStore):
        async def delete(self, storage_ref: str) -> None:
            raise RuntimeError(f"artifact cleanup unavailable: {storage_ref.split('/')[0]}")

    service = CaseHistoryMaterializer(
        metadata=_RejectingMetadata(),
        artifacts=_CleanupFailureArtifacts(),
    )
    with pytest.raises(ExceptionGroup) as captured:
        await _seal(service)

    assert str(captured.value) == (
        "case history metadata append and artifact cleanup failed (2 sub-exceptions)"
    )
    assert [str(error) for error in captured.value.exceptions] == [
        "metadata conflict",
        "artifact cleanup unavailable: case-history",
    ]

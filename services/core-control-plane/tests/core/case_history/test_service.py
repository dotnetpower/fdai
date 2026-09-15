from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai.core.case_history import (
    CaseHistoryMaterializer,
    CaseHistoryRetentionService,
    CaseKind,
    CaseSourceRecord,
    OperationalOutcomeClass,
    OperationalReceiptType,
)
from fdai.core.case_history.testing import (
    InMemoryCaseHistoryArtifactStore,
    InMemoryCaseHistoryMetadataStore,
)
from fdai.shared.contracts.models import ForecastOutcome
from fdai.shared.providers.case_history import CaseHistoryRevisionRecord
from tests.core.case_history.test_operational_case import _case_input, _receipt

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


@pytest.mark.parametrize("kind", [CaseKind.ACTION, CaseKind.INCIDENT])
async def test_operational_case_duplicate_and_late_receipt_preserve_governance(
    kind: CaseKind,
) -> None:
    metadata = InMemoryCaseHistoryMetadataStore()
    artifacts = InMemoryCaseHistoryArtifactStore()
    service = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    case_input = replace(
        _case_input(outcome_class=OperationalOutcomeClass.ROLLBACK),
        kind=kind,
    )
    retention_until = case_input.event_time_cutoff + timedelta(days=30)
    deletion_due_at = case_input.event_time_cutoff + timedelta(days=60)
    first = await service.seal_operational_case(
        case_input,
        retention_until=retention_until,
        deletion_due_at=deletion_due_at,
        legal_hold=True,
        legal_hold_ref="legal-review",
    )
    duplicate = await service.seal_operational_case(
        case_input,
        retention_until=retention_until,
        deletion_due_at=deletion_due_at,
        legal_hold=True,
        legal_hold_ref="legal-review",
    )

    assert duplicate == first
    assert first.record.kind == kind.value
    assert first.record.outcome_label == "rollback"
    assert first.record.detector_id is first.record.detector_version is first.record.metric is None
    assert first.record.legal_hold_ref == "legal-review"
    assert first.projection.outcome_class is OperationalOutcomeClass.ROLLBACK
    artifact = await artifacts.get(first.record.storage_ref or "")
    assert artifact is not None
    document = json.loads(artifact)
    assert document["metadata"] == {
        "action_type": "ops.restart-service",
        "failure_fingerprint": case_input.failure_fingerprint.digest,
        "fdai_revision": case_input.fdai_revision,
        "operational_outcome": "rollback",
        "resource_type": "kubernetes.service",
        "scenario_set_version": case_input.scenario_set_version,
        "source_identity_digest": case_input.source_identity_digest,
        "source_kind": case_input.source_kind.value,
    }

    late_evaluation = _receipt(
        OperationalReceiptType.EVALUATION,
        "5",
        (("validation_status", "rejected"), ("evidence_digest", "7" * 64)),
    )
    revised = await service.seal_operational_case(
        replace(case_input, receipts=(*case_input.receipts, late_evaluation)),
        retention_until=retention_until,
        deletion_due_at=deletion_due_at,
        legal_hold=True,
        legal_hold_ref="legal-review",
    )
    assert revised.record.revision == 2
    assert revised.record.parent_manifest_digest == first.record.manifest_digest
    assert revised.projection.case_revision == 2


async def test_operational_case_projection_change_is_rejected() -> None:
    metadata = InMemoryCaseHistoryMetadataStore()
    service = CaseHistoryMaterializer(
        metadata=metadata,
        artifacts=InMemoryCaseHistoryArtifactStore(),
    )
    case_input = _case_input()
    retention_until = case_input.event_time_cutoff + timedelta(days=30)
    deletion_due_at = case_input.event_time_cutoff + timedelta(days=60)
    await service.seal_operational_case(
        case_input,
        retention_until=retention_until,
        deletion_due_at=deletion_due_at,
    )

    changed = replace(case_input, evidence_refs=("7" * 64,))
    with pytest.raises(ValueError, match="preserve prior source evidence"):
        await service.seal_operational_case(
            changed,
            retention_until=retention_until,
            deletion_due_at=deletion_due_at,
        )


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


async def test_retention_deletes_every_revision_artifact() -> None:
    metadata = InMemoryCaseHistoryMetadataStore()
    artifacts = InMemoryCaseHistoryArtifactStore()
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    await _seal(materializer)
    extra = CaseSourceRecord(
        record_type="postmortem",
        record_id="review-1",
        record_digest="c" * 64,
        occurred_at=T0 + timedelta(hours=3),
        payload={"finding": "seasonal baseline mismatch"},
    )
    latest = await _seal(materializer, sources=(extra,))
    assert len(artifacts._records) == 2  # noqa: SLF001 - full-chain deletion assertion

    retention = CaseHistoryRetentionService(metadata=metadata, artifacts=artifacts)
    assert await retention.delete_due(now=latest.deletion_due_at) == (latest.case_id,)
    assert artifacts._records == {}  # noqa: SLF001 - full-chain deletion assertion


@pytest.mark.parametrize("composite", [False, True])
async def test_derived_deletion_failure_stays_pending_and_retries_after_restart(composite) -> None:
    from fdai.core.case_history.derived import CaseHistoryDerivedRetention
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    metadata = InMemoryCaseHistoryMetadataStore()
    artifacts = InMemoryCaseHistoryArtifactStore()
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    source = await _seal(materializer)

    class _Derived:
        calls = 0

        async def purge(self, record):
            self.calls += 1
            assert record.deletion_started_at is not None
            assert record.deleted_at is None
            assert record.access_scope_digest == SCOPE
            if self.calls == 1:
                raise RuntimeError("derived data deletion unavailable")

    derived = _Derived()
    downstream = (
        CaseHistoryDerivedRetention(
            store=InMemoryStateStore(), materializer=materializer, downstream=(derived,)
        )
        if composite
        else derived
    )
    if composite:
        with pytest.raises(PermissionError, match="deletion claim"):
            await downstream.purge(source)
        assert derived.calls == 0
    retention = CaseHistoryRetentionService(
        metadata=metadata,
        artifacts=artifacts,
        derived_data=downstream,
    )
    with pytest.raises(RuntimeError, match="derived data deletion unavailable"):
        await retention.delete_due(now=source.deletion_due_at)
    pending = await metadata.latest(source.case_id, access_scope_digest=SCOPE)
    assert pending is not None and pending.deletion_started_at is not None
    assert pending.deleted_at is None
    restarted = CaseHistoryRetentionService(
        metadata=metadata,
        artifacts=artifacts,
        derived_data=downstream,
    )
    assert await restarted.delete_due(now=source.deletion_due_at) == (source.case_id,)
    assert derived.calls == 2


async def test_projection_deletion_removes_copies_and_rejects_replay() -> None:
    from fdai.core.case_history.derived import (
        CaseHistoryDerivedRetention,
        CaseHistoryProjectionStore,
    )
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    metadata = InMemoryCaseHistoryMetadataStore()
    artifacts = InMemoryCaseHistoryArtifactStore()
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    source = await _seal(materializer)
    store = InMemoryStateStore()
    projections = CaseHistoryProjectionStore(
        store=store,
        materializer=materializer,
        access_scope_digest=SCOPE,
        clock=lambda: source.sealed_at,
    )
    value = {
        "purpose": source.purpose,
        "access_scope_digest": SCOPE,
        "cases": [
            {
                "case_id": source.case_id,
                "revision": source.revision,
                "manifest_digest": source.manifest_digest,
            }
        ],
    }
    assert await projections.write_state_if_absent("pattern-example", value)
    assert await projections.read_state("pattern-example") == value
    other_scope = CaseHistoryProjectionStore(
        store=store,
        materializer=materializer,
        access_scope_digest="f" * 64,
    )
    assert await other_scope.read_state("pattern-example") is None
    retention = CaseHistoryRetentionService(
        metadata=metadata,
        artifacts=artifacts,
        derived_data=CaseHistoryDerivedRetention(store=store, materializer=materializer),
    )
    assert await retention.delete_due(now=source.deletion_due_at) == (source.case_id,)
    assert await projections.read_state("pattern-example") is None
    with pytest.raises(PermissionError, match="not current"):
        await projections.write_state_if_absent("replayed-pattern", value)


async def test_modified_projection_lineage_cannot_evade_source_deletion() -> None:
    from fdai.core.case_history.derived import CaseHistoryProjectionStore
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    metadata, artifacts = InMemoryCaseHistoryMetadataStore(), InMemoryCaseHistoryArtifactStore()
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    source = await _seal(materializer)
    store = InMemoryStateStore()
    projections = CaseHistoryProjectionStore(
        store=store,
        materializer=materializer,
        access_scope_digest=SCOPE,
        clock=lambda: source.sealed_at,
    )
    value = {
        "purpose": source.purpose,
        "access_scope_digest": SCOPE,
        "cases": [
            {
                "case_id": source.case_id,
                "revision": source.revision,
                "manifest_digest": source.manifest_digest,
            }
        ],
    }
    await projections.write_state_if_absent("pattern-example", value)
    key = f"case-history-derived:v1:{SCOPE}"
    state = await store.read_state(key)
    assert state is not None
    state["entries"]["pattern-example"]["case_refs"] = ["case-history:other-case:1:" + "f" * 64]
    await store.write_state(key, state)
    with pytest.raises(ValueError, match="lineage"):
        await projections.read_state("pattern-example")


@pytest.mark.parametrize(
    "invalid",
    [
        "scope",
        "root",
        "entry",
        "key",
        "source",
        "cases",
        "capacity",
        "bytes",
        "claim",
        "contention",
    ],
)
async def test_derived_projection_rejects_invalid_or_unbounded_work(invalid: str) -> None:
    from fdai.core.case_history.derived import CaseHistoryProjectionStore
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    metadata, artifacts = InMemoryCaseHistoryMetadataStore(), InMemoryCaseHistoryArtifactStore()
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    source = await _seal(materializer)
    durable = InMemoryStateStore()
    if invalid == "scope":
        with pytest.raises(ValueError, match="SHA-256"):
            CaseHistoryProjectionStore(
                store=durable, materializer=materializer, access_scope_digest="invalid"
            )
        return
    projections = CaseHistoryProjectionStore(
        store=durable,
        materializer=materializer,
        access_scope_digest=SCOPE,
        clock=lambda: source.sealed_at,
    )
    value = {
        "purpose": source.purpose,
        "access_scope_digest": SCOPE,
        "cases": [
            {
                "case_id": source.case_id,
                "revision": source.revision,
                "manifest_digest": source.manifest_digest,
            }
        ],
    }
    key = f"case-history-derived:v1:{SCOPE}"
    if invalid in {"root", "entry"}:
        record = (
            {"revision": True, "entries": {}}
            if invalid == "root"
            else {"revision": 1, "entries": {"bad": {}}}
        )
        await durable.write_state(key, record)
        with pytest.raises(ValueError, match="malformed"):
            await projections.read_state("example")
        return
    if invalid == "claim":
        with pytest.raises(PermissionError, match="deletion claim"):
            await projections.purge(source)
        return
    if invalid == "key":
        with pytest.raises(ValueError, match="key"):
            await projections.write_state_if_absent("", value)
        return
    if invalid == "source":
        value["purpose"] = None
    elif invalid == "cases":
        value["cases"] = []
    elif invalid == "bytes":
        value["oversized"] = "x" * (4 * 1024 * 1024)
    elif invalid == "capacity":
        reference = f"case-history:{source.case_id}:{source.revision}:{source.manifest_digest}"
        await durable.write_state(
            key,
            {
                "revision": 1,
                "entries": {
                    f"pattern-{index}": {"case_refs": [reference], "value": value}
                    for index in range(512)
                },
            },
        )
    elif invalid == "contention":
        from unittest.mock import AsyncMock

        durable.write_state_with_audit_if_absent = AsyncMock(return_value=False)
    with pytest.raises((ValueError, RuntimeError)):
        await projections.write_state_if_absent("example", value)


async def test_projection_compare_and_set_rejects_wrong_revision_and_duplicate_create() -> None:
    from fdai.core.case_history.derived import CaseHistoryProjectionStore
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    materializer = CaseHistoryMaterializer(
        metadata=InMemoryCaseHistoryMetadataStore(), artifacts=InMemoryCaseHistoryArtifactStore()
    )
    source = await _seal(materializer)
    projections = CaseHistoryProjectionStore(
        store=InMemoryStateStore(),
        materializer=materializer,
        access_scope_digest=SCOPE,
        clock=lambda: source.sealed_at,
    )
    value = {
        "revision": 1,
        "purpose": source.purpose,
        "access_scope_digest": SCOPE,
        "cases": [
            {
                "case_id": source.case_id,
                "revision": source.revision,
                "manifest_digest": source.manifest_digest,
            }
        ],
    }
    assert await projections.write_state_if_absent("example", value)
    assert not await projections.write_state_if_absent("example", value)
    assert not await projections.compare_and_set_state_with_audit(
        "example", value, expected_revision=9, audit_entry={}
    )


@pytest.mark.parametrize("existing_projection", [True, False])
async def test_projection_writer_cannot_race_source_deletion(existing_projection: bool) -> None:
    import asyncio

    from fdai.core.case_history.derived import (
        CaseHistoryDerivedRetention,
        CaseHistoryProjectionStore,
    )
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    entered, release = asyncio.Event(), asyncio.Event()

    class _DelayedStore(InMemoryStateStore):
        async def write_state_with_audit_if_absent(self, key, value, audit_entry):
            if "racing-pattern" in value.get("entries", {}):
                entered.set()
                await release.wait()
            return await super().write_state_with_audit_if_absent(key, value, audit_entry)

        async def compare_and_set_state_with_audit(self, key, value, **kwargs):
            if "racing-pattern" in value.get("entries", {}):
                entered.set()
                await release.wait()
            return await super().compare_and_set_state_with_audit(key, value, **kwargs)

    metadata, artifacts = InMemoryCaseHistoryMetadataStore(), InMemoryCaseHistoryArtifactStore()
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    source = await _seal(materializer)
    store = _DelayedStore()
    projections = CaseHistoryProjectionStore(
        store=store,
        materializer=materializer,
        access_scope_digest=SCOPE,
        clock=lambda: source.sealed_at,
    )
    value = {
        "purpose": source.purpose,
        "access_scope_digest": SCOPE,
        "cases": [
            {
                "case_id": source.case_id,
                "revision": source.revision,
                "manifest_digest": source.manifest_digest,
            }
        ],
    }
    if existing_projection:
        await projections.write_state_if_absent("existing-pattern", value)
    writer = asyncio.create_task(projections.write_state_if_absent("racing-pattern", value))
    await asyncio.wait_for(entered.wait(), timeout=1)
    retention = CaseHistoryRetentionService(
        metadata=metadata,
        artifacts=artifacts,
        derived_data=CaseHistoryDerivedRetention(store=store, materializer=materializer),
    )
    try:
        assert await retention.delete_due(now=source.deletion_due_at) == (source.case_id,)
    finally:
        release.set()
    with pytest.raises(PermissionError, match="not current"):
        await asyncio.wait_for(writer, timeout=1)
    assert await projections.read_state("existing-pattern") is None
    assert await projections.read_state("racing-pattern") is None


async def test_artifact_delete_failure_keeps_retryable_deletion_intent() -> None:
    class _FailsOnceArtifacts(InMemoryCaseHistoryArtifactStore):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        async def delete(self, storage_ref: str) -> None:
            if not self.failed:
                self.failed = True
                raise RuntimeError("artifact delete unavailable")
            await super().delete(storage_ref)

    metadata = InMemoryCaseHistoryMetadataStore()
    artifacts = _FailsOnceArtifacts()
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    record = await _seal(materializer)
    retention = CaseHistoryRetentionService(metadata=metadata, artifacts=artifacts)

    with pytest.raises(RuntimeError, match="artifact delete unavailable"):
        await retention.delete_due(now=record.deletion_due_at)
    pending = await metadata.latest(record.case_id, access_scope_digest=SCOPE)
    assert pending is not None
    assert pending.deleted_at is None
    assert pending.deletion_started_at == record.deletion_due_at
    assert (
        await metadata.list_closed(
            access_scope_digest=SCOPE,
            purpose=record.purpose,
            outcome_labels=(),
            limit=10,
        )
        == ()
    )

    assert await retention.delete_due(now=record.deletion_due_at) == (record.case_id,)
    tombstone = await metadata.latest(record.case_id, access_scope_digest=SCOPE)
    assert tombstone is not None
    assert tombstone.deleted_at == record.deletion_due_at


async def test_metadata_tombstone_failure_retries_after_artifact_deletion() -> None:
    class _FailsOnceMetadata(InMemoryCaseHistoryMetadataStore):
        def __init__(self) -> None:
            super().__init__()
            self.failed = False

        async def mark_deleted(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            if not self.failed:
                self.failed = True
                raise RuntimeError("metadata tombstone unavailable")
            return await super().mark_deleted(*args, **kwargs)

    metadata = _FailsOnceMetadata()
    artifacts = InMemoryCaseHistoryArtifactStore()
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)
    record = await _seal(materializer)
    retention = CaseHistoryRetentionService(metadata=metadata, artifacts=artifacts)

    with pytest.raises(RuntimeError, match="metadata tombstone unavailable"):
        await retention.delete_due(now=record.deletion_due_at)
    assert record.storage_ref is not None
    assert await artifacts.get(record.storage_ref) is None
    pending = await metadata.latest(record.case_id, access_scope_digest=SCOPE)
    assert pending is not None
    assert pending.deleted_at is None
    assert pending.deletion_storage_refs == (record.storage_ref,)

    assert await retention.delete_due(now=record.deletion_due_at) == (record.case_id,)
    tombstone = await metadata.latest(record.case_id, access_scope_digest=SCOPE)
    assert tombstone is not None
    assert tombstone.deleted_at == record.deletion_due_at


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

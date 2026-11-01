"""Focused Core-to-Operator integration tests for the OutcomeAssuranceProjection producer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import fdai_service_contracts as sc
import pytest
from fdai.core.measurement.outcome_assurance import (
    FinalizedOutcomeEvent,
    OutcomeMeasurementObservation,
)
from fdai.delivery.measurement.outcome_assurance_producer import (
    OutcomeAssuranceProjectionProducer,
    outcome_assurance_projection_key,
    persist_outcome_assurance_projection,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_operator_service.families.operations import ProjectionQuery
from fdai_operator_service.outcome_assurance_projection import (
    _outcome_assurance_key,
    build_outcome_assurance_operator_projection,
    read_outcome_assurance_projection,
)

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
PRINCIPAL_ID = "reader-principal-1"
SCOPE_REF = "scope.checkout"


def _projection(
    *,
    expires_at: datetime,
    observed_at: datetime = NOW,
    scope_ref: str = SCOPE_REF,
) -> sc.OutcomeAssuranceProjection:
    return sc.OutcomeAssuranceProjection(
        state=sc.OutcomeAssuranceReadState.COMPLETE,
        scope=sc.OutcomeAssuranceScope(
            scope_ref=scope_ref,
            vertical=sc.OutcomeAssuranceVertical.CHANGE_SAFETY,
        ),
        window=sc.OutcomeAssuranceWindow(
            start=NOW - timedelta(days=30),
            end=NOW,
            label="30d",
        ),
        sources=(
            sc.OutcomeAssuranceSource(
                name="outcome-assurance-measurement",
                state=sc.OutcomeAssuranceSourceState.COMPLETE,
                observed_at=observed_at,
                expires_at=expires_at,
                evidence_refs=("measurement:change-safety",),
            ),
        ),
        readiness=(
            sc.OutcomeAssuranceReadiness(
                facet=sc.OutcomeAssuranceReadinessFacet.MEASUREMENT,
                state=sc.OutcomeAssuranceReadinessState.READY,
                observed_at=observed_at,
                expires_at=expires_at,
                evidence_refs=("readiness:measurement",),
            ),
        ),
        alignment=sc.OutcomeAssuranceAttribution(
            state=sc.OutcomeAssuranceAttributionState.ATTRIBUTED,
            finalized_events=2,
            attributed_events=2,
            unattributed_events=0,
            coverage=1.0,
            objective_refs=("objective.change-failure-rate@1.0.0",),
            workflow_refs=("workflow.change-safety@1.0.0",),
            action_type_ids=("remediate.rollback-deployment@1.0.0",),
            evidence_refs=("audit:event-1", "audit:event-2"),
        ),
        outcomes=(
            sc.OutcomeAssuranceMetric(
                objective_ref="objective.change-failure-rate@1.0.0",
                metric="change_failure_rate",
                state=sc.OutcomeAssuranceMetricState.MEASURED,
                current_value=0.02,
                baseline_value=0.04,
                target_value=0.025,
                unit="ratio",
                sample_size=48,
                confidence_interval=sc.OutcomeAssuranceConfidenceInterval(low=0.01, high=0.03),
                source_time=observed_at,
                evidence_refs=("measurement:change-failure-rate",),
            ),
        ),
        guards=sc.OutcomeAssuranceControlSummary(
            state=sc.OutcomeAssuranceGuardState.HEALTHY,
            guard_evaluations=(
                sc.OutcomeAssuranceGuardEvaluation(
                    guard_id="policy_escape_zero",
                    threshold=0.0,
                    observed_value=0.0,
                    passed=True,
                    evidence_ref="guard:policy-escape-zero",
                ),
            ),
            evidence_refs=("promotion:change-safety",),
        ),
        provenance=sc.OutcomeAssuranceProvenance(
            as_of=observed_at,
            generated_at=observed_at,
            source_names=("outcome-assurance-measurement",),
        ),
    )


def _fetch_all_adapter(store: InMemoryStateStore):
    async def _fetch_all(statement: str, parameters: tuple[object, ...]) -> list[dict[str, Any]]:
        assert statement == "SELECT value FROM state_kv WHERE key = %s"
        assert len(parameters) == 1
        key = str(parameters[0])
        stored = await store.read_state(key)
        if stored is None:
            return []
        return [{"value": dict(stored)}]

    return _fetch_all


async def test_core_producer_to_operator_reader_round_trip() -> None:
    store = InMemoryStateStore()
    producer = OutcomeAssuranceProjectionProducer(store=store)
    query = ProjectionQuery(
        operation="outcome_assurance",
        path="/kpi/outcome-assurance",
        principal_id=PRINCIPAL_ID,
        limit=50,
        cursor=None,
        params={
            "scope_ref": (SCOPE_REF,),
            "vertical": ("change_safety",),
            "window": ("30d",),
        },
    )

    # 1. Unavailable before Core producer writes any projection
    unavailable_raw = await read_outcome_assurance_projection(
        fetch_all=_fetch_all_adapter(store),
        query=query,
    )
    assert unavailable_raw["state"] == "unavailable"
    assert unavailable_raw["reason"] == "projection_missing"
    assert unavailable_raw["outcomes"] == []

    # 2. Complete after Core producer writes fresh projection under shared reader key
    fresh_projection = _projection(
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        observed_at=NOW,
    )
    receipt = await producer.publish(
        principal_id=PRINCIPAL_ID,
        projection=fresh_projection,
        published_at=NOW,
    )
    expected_key = _outcome_assurance_key(PRINCIPAL_ID, SCOPE_REF, "change_safety", "30d")
    assert receipt.key == expected_key
    assert outcome_assurance_projection_key(PRINCIPAL_ID, SCOPE_REF, "change_safety", "30d") == (
        expected_key
    )
    assert receipt.execution_authority is False
    assert len(store.audit_entries) == 1
    assert (
        store.audit_entries[0]["entry"]["action_kind"]
        == "measurement.outcome_assurance.projection.v1"
    )

    complete_raw = await read_outcome_assurance_projection(
        fetch_all=_fetch_all_adapter(store),
        query=query,
    )
    decoded_complete = sc.OutcomeAssuranceProjection.model_validate(complete_raw)
    assert decoded_complete.state is sc.OutcomeAssuranceReadState.COMPLETE
    assert decoded_complete.outcomes[0].current_value == 0.02
    assert decoded_complete.execution_authority is False

    operator_view = build_outcome_assurance_operator_projection(
        principal_id=PRINCIPAL_ID,
        projection=decoded_complete,
        scope_ref=SCOPE_REF,
        vertical="change_safety",
        window_label="30d",
        now=NOW + timedelta(minutes=5),
    )
    assert operator_view.state is sc.OutcomeAssuranceReadState.COMPLETE
    assert operator_view.authority == "none"
    assert operator_view.read_only is True
    assert operator_view.projection_digest.startswith("sha256:")

    # 3. Out-of-order older provenance on the same key is rejected
    older_same_scope = _projection(
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        observed_at=NOW - timedelta(hours=1),
    )
    with pytest.raises(ValueError, match="cannot overwrite newer provenance"):
        await persist_outcome_assurance_projection(
            principal_id=PRINCIPAL_ID,
            projection=older_same_scope,
            store=store,
        )

    # 4. Stale when Core producer writes a projection whose source freshness window expired
    expired_projection = _projection(
        expires_at=datetime(2025, 1, 2, tzinfo=UTC),
        observed_at=datetime(2025, 1, 1, tzinfo=UTC),
        scope_ref="scope.checkout-stale",
    )
    await persist_outcome_assurance_projection(
        principal_id=PRINCIPAL_ID,
        projection=expired_projection,
        store=store,
    )
    stale_query = ProjectionQuery(
        operation="outcome_assurance",
        path="/kpi/outcome-assurance",
        principal_id=PRINCIPAL_ID,
        limit=50,
        cursor=None,
        params={
            "scope_ref": ("scope.checkout-stale",),
            "vertical": ("change_safety",),
            "window": ("30d",),
        },
    )
    stale_raw = await read_outcome_assurance_projection(
        fetch_all=_fetch_all_adapter(store),
        query=stale_query,
    )
    assert stale_raw["state"] == "stale"
    assert stale_raw["reason"] == "source_stale"
    assert stale_raw["outcomes"][0]["state"] == "stale"
    assert stale_raw["outcomes"][0]["current_value"] is None


def test_producer_key_rejects_malformed_inputs() -> None:
    with pytest.raises(ValueError, match="principal_id is malformed"):
        outcome_assurance_projection_key("", SCOPE_REF, "change_safety", "30d")
    with pytest.raises(ValueError, match="scope_ref is malformed"):
        outcome_assurance_projection_key(PRINCIPAL_ID, "bad\x00scope", "change_safety", "30d")
    with pytest.raises(ValueError, match="vertical is malformed"):
        outcome_assurance_projection_key(PRINCIPAL_ID, SCOPE_REF, "invalid_vertical", "30d")
    with pytest.raises(ValueError, match="window MUST be an integer day label"):
        outcome_assurance_projection_key(PRINCIPAL_ID, SCOPE_REF, "change_safety", "0d")


async def test_publish_from_authoritative_sources_joins_and_fails_closed() -> None:
    store = InMemoryStateStore()
    producer = OutcomeAssuranceProjectionProducer(store=store)
    projection = _projection(expires_at=datetime(2099, 1, 1, tzinfo=UTC), observed_at=NOW)
    events = (
        FinalizedOutcomeEvent(
            event_id="ev-1",
            finalized_at=NOW,
            decision_case_id="case-1",
            protected_objective_ref="objective.change-failure-rate@1.0.0",
            workflow_ref="workflow.change-safety@1.0.0",
            action_type_id="remediate.rollback-deployment@1.0.0",
            action_run_id="run-1",
            observed_outcome_ref="obs-outcome-1",
            evidence_refs=("audit:event-1",),
        ),
    )
    observations = (
        OutcomeMeasurementObservation(
            observation_id="obs-1",
            event_id="ev-1",
            objective_ref="objective.change-failure-rate@1.0.0",
            metric="change_failure_rate",
            value=0.02,
            observed_at=NOW,
            recorded_at=NOW,
            evidence_ref="measurement:change-failure-rate",
        ),
    )

    receipt = await producer.publish_from_authoritative_sources(
        principal_id=PRINCIPAL_ID,
        scope=projection.scope,
        window=projection.window,
        sources=projection.sources,
        readiness=projection.readiness,
        finalized_events=events,
        observations=observations,
        outcomes=projection.outcomes,
        guards=projection.guards,
        as_of=NOW,
    )
    assert receipt.state is sc.OutcomeAssuranceReadState.COMPLETE

    unavailable_receipt = await producer.publish_from_authoritative_sources(
        principal_id=PRINCIPAL_ID,
        scope=projection.scope,
        window=projection.window,
        sources=(
            sc.OutcomeAssuranceSource(
                name="outcome-assurance-measurement",
                state=sc.OutcomeAssuranceSourceState.UNAVAILABLE,
                reason=sc.OutcomeAssuranceUnavailableReason.SOURCE_MISSING,
            ),
        ),
        readiness=(),
        finalized_events=events,
        observations=observations,
        outcomes=projection.outcomes,
        guards=sc.OutcomeAssuranceControlSummary(
            state=sc.OutcomeAssuranceGuardState.UNAVAILABLE,
            reason=sc.OutcomeAssuranceUnavailableReason.SOURCE_MISSING,
        ),
        as_of=NOW,
    )
    assert unavailable_receipt.state is sc.OutcomeAssuranceReadState.UNAVAILABLE


async def test_atomic_write_and_audit_rollback_and_cli_rejects_precomputed_state(
    tmp_path, monkeypatch
) -> None:
    from fdai.delivery.measurement_runner_cli import _run_outcome_assurance

    class _FailingAuditStore(InMemoryStateStore):
        def _append_audit_locked(self, entry) -> None:
            raise RuntimeError("audit append failed")

    failing_store = _FailingAuditStore()
    projection = _projection(expires_at=datetime(2099, 1, 1, tzinfo=UTC), observed_at=NOW)
    with pytest.raises(RuntimeError, match="audit append failed"):
        await persist_outcome_assurance_projection(
            principal_id=PRINCIPAL_ID,
            projection=projection,
            store=failing_store,
        )
    key = outcome_assurance_projection_key(PRINCIPAL_ID, SCOPE_REF, "change_safety", "30d")
    assert await failing_store.read_state(key) is None

    forged = tmp_path / "forged-source-bundle.json"
    forged.write_text('{"state": "complete", "alignment": {}}', encoding="utf-8")
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://127.0.0.1:5433/fdai")
    monkeypatch.setenv("FDAI_OUTCOME_ASSURANCE_PRINCIPAL_ID", PRINCIPAL_ID)
    monkeypatch.setenv("FDAI_OUTCOME_ASSURANCE_ROOT", str(tmp_path))
    monkeypatch.setenv("FDAI_OUTCOME_ASSURANCE_SOURCE_BUNDLE_PATH", "forged-source-bundle.json")
    with pytest.raises(ValueError, match="MUST supply raw sources"):
        await _run_outcome_assurance()


async def test_interleaved_concurrent_update_prevents_stale_overwrite() -> None:
    base_store = InMemoryStateStore()
    initial = _projection(
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        observed_at=NOW,
    )
    await persist_outcome_assurance_projection(
        principal_id=PRINCIPAL_ID,
        projection=initial,
        store=base_store,
    )
    newer = _projection(
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        observed_at=NOW + timedelta(minutes=10),
    )
    stale_middle = _projection(
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        observed_at=NOW + timedelta(minutes=5),
    )

    class _InterleavedStore(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__()
            self._state = base_store._state
            self._audit = base_store._audit
            self._interleaved = False

        async def compare_and_set_state_with_audit(
            self,
            key: str,
            value,
            *,
            expected_revision: int,
            audit_entry,
        ) -> bool:
            if not self._interleaved:
                self._interleaved = True
                # Newer writer commits revision 2 after stale_middle already read revision 1
                await persist_outcome_assurance_projection(
                    principal_id=PRINCIPAL_ID,
                    projection=newer,
                    store=base_store,
                )
            return await super().compare_and_set_state_with_audit(
                key,
                value,
                expected_revision=expected_revision,
                audit_entry=audit_entry,
            )

    interleaved_store = _InterleavedStore()
    with pytest.raises(ValueError, match="cannot overwrite newer provenance"):
        await persist_outcome_assurance_projection(
            principal_id=PRINCIPAL_ID,
            projection=stale_middle,
            store=interleaved_store,
        )
    key = outcome_assurance_projection_key(PRINCIPAL_ID, SCOPE_REF, "change_safety", "30d")
    stored = await base_store.read_state(key)
    assert stored is not None
    assert stored["revision"] == 2

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.architecture_review import (
    ArchitectureReviewObservationTrace,
    ArchitectureReviewStage,
    ArchitectureReviewTraceEvent,
    ArchitectureReviewTraceObserver,
    replay_architecture_review_trace,
)

_NOW = datetime(2026, 8, 29, 3, 0, tzinfo=UTC)
_DEADLINE = _NOW + timedelta(minutes=5)
_CORRELATION_ID = "correlation-arb-observation-1"
_REVIEW_CASE_ID = "review-case-arb-observation-1"
_BINDINGS = (
    (ArchitectureReviewStage.CHANGE, "object.change", "Huginn"),
    (ArchitectureReviewStage.CONTEXT, "object.state-snapshot", "Muninn"),
    (ArchitectureReviewStage.RELIABILITY, "object.anomaly", "Heimdall"),
    (ArchitectureReviewStage.COST, "object.cost-anomaly", "Njord"),
    (ArchitectureReviewStage.CAPACITY, "object.capacity-forecast", "Freyr"),
    (ArchitectureReviewStage.RECOVERY, "object.chaos-experiment", "Loki"),
    (ArchitectureReviewStage.EVIDENCE_BUNDLE, "object.state-snapshot", "Muninn"),
    (ArchitectureReviewStage.SCENARIO_BRANCH, "object.verdict", "Forseti"),
    (ArchitectureReviewStage.DECISION_CASE, "object.verdict", "Forseti"),
    (ArchitectureReviewStage.IMPACT_ENVELOPE, "object.verdict", "Forseti"),
    (ArchitectureReviewStage.RECOMMENDATION, "object.verdict", "Forseti"),
    (ArchitectureReviewStage.AUDIT, "object.audit-entry", "Saga"),
)


def _events() -> tuple[ArchitectureReviewTraceEvent, ...]:
    return tuple(
        ArchitectureReviewTraceEvent(
            sequence=index,
            stage=stage,
            topic=topic,
            producer_principal=producer,
            correlation_id=_CORRELATION_ID,
            review_case_id=_REVIEW_CASE_ID,
            idempotency_key=f"arb-observation-1:{index}",
            observed_at=_NOW + timedelta(seconds=index),
            evidence_digest=f"sha256:{index:064x}",
            status="conformant" if stage is ArchitectureReviewStage.RECOMMENDATION else "complete",
        )
        for index, (stage, topic, producer) in enumerate(_BINDINGS, start=1)
    )


def _replay(
    events: tuple[ArchitectureReviewTraceEvent, ...],
) -> ArchitectureReviewObservationTrace:
    return replay_architecture_review_trace(
        correlation_id=_CORRELATION_ID,
        review_case_id=_REVIEW_CASE_ID,
        deadline_at=_DEADLINE,
        events=events,
    )


def test_complete_observation_trace_is_replay_stable_and_authority_free() -> None:
    events = _events()

    first = _replay(events)
    reordered = _replay(tuple(reversed(events)))
    redelivered = _replay((events[0], *events, events[-1]))

    assert first == reordered == redelivered
    assert first.outcome == "conformant"
    assert first.hold_reasons == ()
    assert first.authority_state == "observation_only"
    assert first.mutation_authority is False
    assert first.execution_authority is False
    assert first.trace_digest.startswith("sha256:")
    assert tuple(event.stage for event in first.events) == tuple(ArchitectureReviewStage)


def test_checkpoint_replay_converges_after_restart() -> None:
    events = _events()
    checkpoint = _replay(events[:6])

    resumed = _replay((*checkpoint.events, *events[6:]))

    assert checkpoint.outcome == "hold"
    assert "missing_stage:audit" in checkpoint.hold_reasons
    assert resumed == _replay(events)


def test_missing_conflicting_late_or_wrong_owner_evidence_holds() -> None:
    events = _events()
    missing = _replay(events[:-1])
    conflicting = _replay(
        (
            *events,
            replace(events[2], evidence_digest=f"sha256:{999:064x}"),
        )
    )
    conflicting_reordered = _replay(
        (
            replace(events[2], evidence_digest=f"sha256:{999:064x}"),
            *events,
        )
    )
    late = _replay(
        tuple(
            replace(event, observed_at=_DEADLINE + timedelta(seconds=1))
            if event.stage is ArchitectureReviewStage.COST
            else event
            for event in events
        )
    )
    wrong_owner = _replay(
        tuple(
            replace(event, producer_principal="Thor")
            if event.stage is ArchitectureReviewStage.RECOMMENDATION
            else event
            for event in events
        )
    )

    assert missing.outcome == "hold"
    assert "missing_stage:audit" in missing.hold_reasons
    assert conflicting.outcome == "hold"
    assert "conflicting_sequence:3" in conflicting.hold_reasons
    assert conflicting == conflicting_reordered
    assert late.outcome == "hold"
    assert "late_stage:cost" in late.hold_reasons
    assert wrong_owner.outcome == "hold"
    assert "owner_mismatch:recommendation" in wrong_owner.hold_reasons
    for trace in (missing, conflicting, late, wrong_owner):
        assert trace.mutation_authority is False
        assert trace.execution_authority is False


def _runtime_payload(
    stage: ArchitectureReviewStage,
    *,
    sequence: int,
    observed_at: datetime | None = None,
) -> tuple[str, dict[str, object]]:
    topic, producer = _BINDINGS[sequence - 1][1:]
    payload: dict[str, object] = {
        "producer_principal": producer,
        "correlation_id": _CORRELATION_ID,
        "review_case_id": _REVIEW_CASE_ID,
        "deadline_at": _DEADLINE.isoformat(),
        "observed_at": (observed_at or (_NOW + timedelta(seconds=sequence))).isoformat(),
        "idempotency_key": f"arb-runtime:{sequence}",
        "evidence_digest": f"sha256:{sequence + 100:064x}",
    }
    if stage is ArchitectureReviewStage.CHANGE:
        payload.update(
            {
                "id": _REVIEW_CASE_ID,
                "intent_kind": "planned",
                "occurred_at": _NOW.isoformat(),
            }
        )
    elif stage is ArchitectureReviewStage.CONTEXT:
        payload["snapshot_type"] = "architecture_review_context"
    elif stage is ArchitectureReviewStage.RELIABILITY:
        payload["resource_id"] = "resource-1"
    elif stage is ArchitectureReviewStage.COST:
        payload["resource_id"] = "resource-1"
        payload["scope"] = "scope-1"
    elif stage is ArchitectureReviewStage.CAPACITY:
        payload["resource_id"] = "resource-1"
        payload["forecast_util"] = 0.8
        payload["recommendation"] = "scale_up"
    elif stage is ArchitectureReviewStage.RECOVERY:
        payload["resource_id"] = "resource-1"
        payload["experiment_id"] = "experiment-1"
    elif stage is ArchitectureReviewStage.EVIDENCE_BUNDLE:
        payload["snapshot_type"] = "architecture_review_evidence_bundle"
    elif stage is ArchitectureReviewStage.SCENARIO_BRANCH:
        payload["resource_id"] = "resource-1"
        payload["change_assessment"] = {"change_id": _REVIEW_CASE_ID}
    elif stage is ArchitectureReviewStage.DECISION_CASE:
        payload["resource_id"] = "resource-1"
        payload["decision_case"] = {"selected_option_id": "hold", "options": []}
    elif stage is ArchitectureReviewStage.IMPACT_ENVELOPE:
        payload["resource_id"] = "resource-1"
        payload["architecture_review_trace"] = {
            "stage": stage.value,
            "review_case_id": _REVIEW_CASE_ID,
            "deadline_at": _DEADLINE.isoformat(),
        }
    elif stage is ArchitectureReviewStage.RECOMMENDATION:
        payload["resource_id"] = "resource-1"
        payload["risk_verdict"] = "auto"
        payload["architecture_review_trace"] = {
            "stage": stage.value,
            "review_case_id": _REVIEW_CASE_ID,
            "deadline_at": _DEADLINE.isoformat(),
        }
    else:
        payload["audited_topic"] = "object.verdict"
        payload["mode"] = "shadow"
    return topic, payload


def test_runtime_observer_replays_owned_records_across_restart_and_reorder() -> None:
    records = tuple(
        _runtime_payload(stage, sequence=index)
        for index, (stage, _topic, _producer) in enumerate(_BINDINGS, start=1)
    )
    resumed = ArchitectureReviewTraceObserver(clock=lambda: _NOW)
    for topic, payload in records[:6]:
        resumed.observe(topic, payload)
    partial = resumed.trace_for(_CORRELATION_ID, review_case_id=_REVIEW_CASE_ID)

    assert partial is not None
    assert partial.outcome == "hold"
    assert "missing_stage:recommendation" in partial.hold_reasons

    for topic, payload in records[6:]:
        resumed.observe(topic, payload)
    resumed_trace = resumed.trace_for(_CORRELATION_ID, review_case_id=_REVIEW_CASE_ID)
    restarted = ArchitectureReviewTraceObserver(clock=lambda: _NOW)
    replay_input = tuple(reversed((records[0], *records, records[-1])))
    for topic, payload in replay_input:
        restarted.observe(topic, payload)
    restarted_trace = restarted.trace_for(_CORRELATION_ID, review_case_id=_REVIEW_CASE_ID)

    assert resumed_trace is not None
    assert restarted_trace is not None
    assert resumed_trace == restarted_trace
    assert resumed_trace.outcome == "conformant"
    assert tuple(event.stage for event in resumed_trace.events) == tuple(ArchitectureReviewStage)


def test_runtime_observer_does_not_claim_unseeded_specialist_signal() -> None:
    observer = ArchitectureReviewTraceObserver(clock=lambda: _NOW)

    trace = observer.observe(
        "object.cost-anomaly",
        {
            "producer_principal": "Njord",
            "correlation_id": "corr-unseeded",
            "resource_id": "resource-1",
            "observed_at": _NOW.isoformat(),
        },
    )

    assert trace is None
    assert observer.snapshot()["seeded_correlations"] == 0


def test_runtime_observer_holds_late_or_degraded_topics_without_authority() -> None:
    observer = ArchitectureReviewTraceObserver(clock=lambda: _NOW)
    change_topic, change_payload = _runtime_payload(ArchitectureReviewStage.CHANGE, sequence=1)
    recommendation_topic, recommendation_payload = _runtime_payload(
        ArchitectureReviewStage.RECOMMENDATION,
        sequence=11,
        observed_at=_DEADLINE + timedelta(seconds=1),
    )

    observer.observe(change_topic, change_payload)
    observer.observe(recommendation_topic, recommendation_payload)
    observer.observe_consumer_state(topic="object.audit-entry", state="gave_up")
    trace = observer.trace_for(_CORRELATION_ID, review_case_id=_REVIEW_CASE_ID)

    assert trace is not None
    assert trace.outcome == "hold"
    assert "late_stage:recommendation" in trace.hold_reasons
    assert "topic_degraded:object.audit-entry:gave_up" in trace.hold_reasons
    assert trace.mutation_authority is False
    assert trace.execution_authority is False

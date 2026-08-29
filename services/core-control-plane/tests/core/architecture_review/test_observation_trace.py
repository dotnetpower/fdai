from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.architecture_review import (
    ArchitectureReviewObservationTrace,
    ArchitectureReviewStage,
    ArchitectureReviewTraceEvent,
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

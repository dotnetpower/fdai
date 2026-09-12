"""Descriptive metrics cannot promote decisions or dispatches into outcomes."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai_operator_service.dashboard_aggregation import (
    ActionObservation,
    ClassifiedEvent,
    HumanTouchpoint,
    MetricObservation,
    aggregate_dashboard,
)

START = datetime(2026, 8, 1, tzinfo=UTC)
END = START + timedelta(days=30)
EVENT = ClassifiedEvent(
    event_id="event-a",
    identity="ingest-a",
    tier="t0",
    decision="auto",
    mode="enforce",
    occurred_at=START + timedelta(hours=1),
    seq=1,
    action_ids=("action-a",),
)
OUTCOME = ActionObservation(
    event_id="event-a",
    action_id="action-a",
    observation_id="observation-a",
    mode="enforce",
    decision="auto",
    scorable=True,
    verified=True,
    rollback=False,
    observed_at=START + timedelta(hours=2),
    seq=2,
)


def reduce(*, events=(), outcomes=(), metrics=(), touchpoints=()):
    return aggregate_dashboard(
        events=events,
        outcomes=outcomes,
        metrics=metrics,
        touchpoints=touchpoints,
        window_start=START,
        window_end=END,
    )


def test_no_measurements_are_unavailable_not_zero() -> None:
    result = reduce()
    assert result["sample_size"] == 0
    assert all(metric["value"] is None for metric in result["success"].values())
    assert result["confidence"] is None
    assert result["verticals"] == []


def test_dispatch_and_shadow_verification_never_resolve_an_event() -> None:
    assert reduce(events=[EVENT])["success"]["auto_resolution_rate"]["value"] == 0
    result = reduce(
        events=[replace(EVENT, mode="shadow")],
        outcomes=[replace(OUTCOME, mode="shadow")],
    )
    assert result["success"]["auto_resolution_rate"]["value"] == 0
    assert result["finalization"]["pending_events"] == 1


def test_counts_unique_human_actions_and_retains_pending_denominator() -> None:
    event_b = replace(
        EVENT, event_id="event-b", identity="ingest-b", decision="hil", action_ids=(), seq=3
    )
    points = [
        HumanTouchpoint("event-b", "approval-one"),
        HumanTouchpoint("event-b", "approval-one"),
        HumanTouchpoint("event-b", "approval-two"),
    ]
    result = reduce(events=[EVENT, event_b], outcomes=[OUTCOME], touchpoints=points)
    assert result["sample_size"] == 2
    assert result["success"]["auto_resolution_rate"]["value"] == 0.5
    assert result["success"]["human_touchpoints_per_100"]["value"] == 100
    assert result["finalization"]["pending_events"] == 1


def test_required_human_input_without_identity_does_not_claim_zero_touchpoints() -> None:
    result = reduce(events=[replace(EVENT, decision="hil")])
    assert result["success"]["human_touchpoints_per_100"]["value"] is None


def test_human_input_disqualifies_automatic_resolution() -> None:
    result = reduce(
        events=[EVENT],
        outcomes=[OUTCOME],
        touchpoints=[HumanTouchpoint(EVENT.event_id, "manual-action")],
    )
    assert result["success"]["auto_resolution_rate"]["value"] == 0


def test_all_actions_require_observed_closure() -> None:
    event = replace(EVENT, action_ids=("action-a", "action-b"))
    assert reduce(events=[event], outcomes=[OUTCOME])["finalization"]["pending_events"] == 1
    second = replace(OUTCOME, action_id="action-b", observation_id="observation-b", seq=3)
    assert (
        reduce(events=[event], outcomes=[OUTCOME, second])["success"]["auto_resolution_rate"][
            "value"
        ]
        == 1
    )


@pytest.mark.parametrize(
    "correction",
    [
        replace(OUTCOME, rollback=True, seq=3),
        replace(OUTCOME, verified=False, seq=3),
        replace(OUTCOME, verified=False, scorable=False, observed_at=None, seq=3),
    ],
)
def test_latest_correction_withdraws_prior_success(correction) -> None:
    result = reduce(events=[EVENT], outcomes=[correction, OUTCOME])
    assert result["success"]["auto_resolution_rate"]["value"] == 0


def test_timing_metrics_use_their_own_samples_and_keep_fractional_seconds() -> None:
    metrics = [
        MetricObservation("incident-a", "mttr_seconds", 0.5, END, 2),
        MetricObservation("incident-b", "mttr_seconds", 1.0, END, 3),
        MetricObservation("change-a", "change_lead_time_seconds", 0.0, END, 4),
    ]
    result = reduce(events=[EVENT], metrics=metrics)
    assert result["success"]["mttr_seconds"]["value"] == 0.75
    assert result["metric_samples"]["mttr_seconds"] == 2
    assert result["success"]["change_lead_time_seconds"]["value"] == 0
    assert result["metric_samples"]["change_lead_time_seconds"] == 1


def test_metric_correction_replaces_then_can_invalidate_a_value() -> None:
    original = MetricObservation("incident-a", "mttr_seconds", 5.0, END, 2)
    corrected = replace(original, value=3.0, seq=3)
    withdrawn = replace(original, value=None, seq=4)
    assert reduce(metrics=[original, corrected])["success"]["mttr_seconds"]["value"] == 3
    assert (
        reduce(metrics=[withdrawn, original, corrected])["success"]["mttr_seconds"]["value"] is None
    )


def test_cost_needs_every_event_and_includes_unresolved_spend() -> None:
    event_b = replace(
        EVENT, event_id="event-b", identity="ingest-b", action_ids=("action-b",), seq=3
    )
    cost_a = MetricObservation("event-a", "attributed_cost_usd", 3.0, END, 4)
    cost_b = MetricObservation("event-b", "attributed_cost_usd", 4.0, END, 5)
    incomplete = reduce(events=[EVENT, event_b], outcomes=[OUTCOME], metrics=[cost_a])
    assert incomplete["success"]["cost_per_resolved_event_usd"]["value"] is None
    complete = reduce(events=[EVENT, event_b], outcomes=[OUTCOME], metrics=[cost_a, cost_b])
    assert complete["success"]["cost_per_resolved_event_usd"]["value"] == 7


def test_identity_changes_fail_closed() -> None:
    with pytest.raises(ValueError, match="identity changed"):
        reduce(events=[EVENT, replace(EVENT, event_id="different", seq=3)])
    with pytest.raises(ValueError, match="conflicting idempotency"):
        reduce(events=[EVENT, replace(EVENT, identity="different", seq=3)])
    with pytest.raises(ValueError, match="changed its event"):
        reduce(events=[EVENT], outcomes=[OUTCOME, replace(OUTCOME, event_id="other", seq=3)])


def test_unrelated_and_outside_window_events_are_not_added_to_the_cohort() -> None:
    outside = replace(
        EVENT, event_id="old", identity="old-key", occurred_at=START - timedelta(seconds=1)
    )
    result = reduce(events=[EVENT, EVENT, outside], outcomes=[OUTCOME])
    assert result["sample_size"] == 1
    assert result["success"]["auto_resolution_rate"]["value"] == 1


def test_compliant_noop_is_neutral_not_an_operational_recovery() -> None:
    result = reduce(events=[replace(EVENT, decision="compliant", action_ids=())])
    assert result["success"]["auto_resolution_rate"]["value"] == 0
    assert result["finalization"] == {
        "finalized_events": 0,
        "pending_events": 0,
        "adverse_events": 0,
        "neutral_events": 1,
    }


def test_latest_synthetic_classification_does_not_reveal_an_older_live_event() -> None:
    result = reduce(events=[EVENT, replace(EVENT, synthetic=True, seq=3)], outcomes=[OUTCOME])
    assert result["sample_size"] == 0
    assert result["success"]["auto_resolution_rate"]["value"] is None


def test_mixed_metric_contexts_are_not_averaged() -> None:
    first = MetricObservation("a", "mttr_seconds", 1.0, END, 1, ("p", "v1", "s", "enforce"))
    second = MetricObservation("b", "mttr_seconds", 3.0, END, 2, ("p", "v2", "s", "enforce"))
    result = reduce(metrics=[first, second])
    assert result["success"]["mttr_seconds"]["value"] is None
    assert result["measurement_gaps"] == ["mixed_context:mttr_seconds"]


def test_incomplete_metric_does_not_make_the_rest_a_complete_cohort() -> None:
    result = reduce(
        metrics=[
            MetricObservation("a", "mttr_seconds", 1.0, END, 1),
            MetricObservation("b", "mttr_seconds", None, END, 2),
        ]
    )
    assert result["success"]["mttr_seconds"]["value"] is None
    assert result["measurement_gaps"] == ["incomplete:mttr_seconds"]


def test_finite_means_do_not_overflow_and_unrepresentable_cost_is_explicit() -> None:
    result = reduce(
        metrics=[
            MetricObservation("a", "mttr_seconds", 1e308, END, 1),
            MetricObservation("b", "mttr_seconds", 1e308, END, 2),
        ]
    )
    assert result["success"]["mttr_seconds"]["value"] == 1e308
    other = replace(EVENT, event_id="event-b", identity="ingest-b", action_ids=())
    with pytest.raises(ValueError, match="finite reporting range"):
        reduce(
            events=[EVENT, other],
            outcomes=[OUTCOME],
            metrics=[
                MetricObservation("event-a", "attributed_cost_usd", 1e308, END, 3),
                MetricObservation("event-b", "attributed_cost_usd", 1e308, END, 4),
            ],
        )


def test_one_incident_linked_to_multiple_events_keeps_one_timing_sample() -> None:
    original = MetricObservation(
        "event-a", "mttr_seconds", 5.0, END, 1, sample_identity=("source", "incident")
    )
    correction = replace(original, event_id="event-b", value=3.0, seq=2)
    result = reduce(metrics=[original, correction])
    assert result["success"]["mttr_seconds"]["value"] == 3
    assert result["metric_samples"]["mttr_seconds"] == 1

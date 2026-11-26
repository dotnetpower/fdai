"""T1 correlation RCA - deterministic causal-chain from temporal antecedents.

Verifies T1 identifies the closest antecedent change as the probable
trigger, grounds it on event citations, scales confidence with proximity
within the bounded T1 band, and abstains (defers to T2) when no plausible
antecedent change exists.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.rca import CorrelatedEvent, t1_causal_chain
from fdai.core.rca.contract import CitationKind, RcaTier

FAIL_AT = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
WINDOW = timedelta(minutes=10)


def _change(event_id: str, *, before: timedelta, resource: str) -> CorrelatedEvent:
    return CorrelatedEvent(
        event_id=event_id,
        at=FAIL_AT - before,
        resource_ref=resource,
        is_change=True,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_picks_closest_antecedent_change_as_trigger() -> None:
    events = [
        _change("chg-early", before=timedelta(minutes=8), resource="res-a"),
        _change("chg-late", before=timedelta(minutes=2), resource="res-a"),
    ]
    hyp = t1_causal_chain(
        failure_event_id="fail-1",
        failure_at=FAIL_AT,
        failure_resource_ref="res-a",
        correlated_events=events,
        window=WINDOW,
    )
    assert hyp is not None
    assert hyp.tier is RcaTier.T1
    assert "chg-late" in hyp.cause  # closest antecedent wins
    assert hyp.grounded
    # Cites both the trigger and the failure event.
    refs = {c.ref for c in hyp.citations}
    assert refs == {"chg-late", "fail-1"}
    assert all(c.kind is CitationKind.EVENT for c in hyp.citations)


def test_confidence_is_within_t1_band_and_rises_with_proximity() -> None:
    near = t1_causal_chain(
        failure_event_id="fail-1",
        failure_at=FAIL_AT,
        failure_resource_ref="res-a",
        correlated_events=[_change("c", before=timedelta(seconds=5), resource="res-a")],
        window=WINDOW,
    )
    far = t1_causal_chain(
        failure_event_id="fail-1",
        failure_at=FAIL_AT,
        failure_resource_ref="res-a",
        correlated_events=[_change("c", before=timedelta(minutes=9), resource="res-a")],
        window=WINDOW,
    )
    assert near is not None
    assert far is not None
    assert near.confidence > far.confidence
    # Bounded T1 band - never T0-style certainty.
    for hyp in (near, far):
        assert 0.35 <= hyp.confidence <= 0.85


def test_cross_resource_change_qualifies_by_default() -> None:
    hyp = t1_causal_chain(
        failure_event_id="fail-1",
        failure_at=FAIL_AT,
        failure_resource_ref="res-a",
        correlated_events=[_change("dep", before=timedelta(minutes=1), resource="res-shared")],
        window=WINDOW,
    )
    assert hyp is not None
    assert "upstream-resource" in hyp.cause
    assert "res-shared" in hyp.cause


def test_same_resource_only_excludes_upstream_change() -> None:
    hyp = t1_causal_chain(
        failure_event_id="fail-1",
        failure_at=FAIL_AT,
        failure_resource_ref="res-a",
        correlated_events=[_change("dep", before=timedelta(minutes=1), resource="res-shared")],
        window=WINDOW,
        same_resource_only=True,
    )
    assert hyp is None


# ---------------------------------------------------------------------------
# Abstain paths (defer to T2)
# ---------------------------------------------------------------------------


def test_abstains_when_no_change_events() -> None:
    non_change = CorrelatedEvent(
        event_id="obs-1",
        at=FAIL_AT - timedelta(minutes=1),
        resource_ref="res-a",
        is_change=False,
    )
    hyp = t1_causal_chain(
        failure_event_id="fail-1",
        failure_at=FAIL_AT,
        failure_resource_ref="res-a",
        correlated_events=[non_change],
        window=WINDOW,
    )
    assert hyp is None


def test_abstains_when_change_outside_window() -> None:
    hyp = t1_causal_chain(
        failure_event_id="fail-1",
        failure_at=FAIL_AT,
        failure_resource_ref="res-a",
        correlated_events=[_change("old", before=timedelta(minutes=20), resource="res-a")],
        window=WINDOW,
    )
    assert hyp is None


def test_abstains_when_change_after_failure() -> None:
    after = CorrelatedEvent(
        event_id="post",
        at=FAIL_AT + timedelta(minutes=1),
        resource_ref="res-a",
        is_change=True,
    )
    hyp = t1_causal_chain(
        failure_event_id="fail-1",
        failure_at=FAIL_AT,
        failure_resource_ref="res-a",
        correlated_events=[after],
        window=WINDOW,
    )
    assert hyp is None


def test_abstains_on_non_positive_window() -> None:
    hyp = t1_causal_chain(
        failure_event_id="fail-1",
        failure_at=FAIL_AT,
        failure_resource_ref="res-a",
        correlated_events=[_change("c", before=timedelta(minutes=1), resource="res-a")],
        window=timedelta(0),
    )
    assert hyp is None


def test_abstains_on_non_positive_max_hops() -> None:
    hyp = t1_causal_chain(
        failure_event_id="fail-1",
        failure_at=FAIL_AT,
        failure_resource_ref="res-a",
        correlated_events=[_change("c", before=timedelta(minutes=1), resource="res-a")],
        window=WINDOW,
        max_hops=0,
    )
    assert hyp is None


def test_deterministic_and_ignores_self_event() -> None:
    events = [
        _change("fail-1", before=timedelta(minutes=1), resource="res-a"),  # self, ignored
        _change("chg", before=timedelta(minutes=2), resource="res-a"),
    ]
    first = t1_causal_chain(
        failure_event_id="fail-1",
        failure_at=FAIL_AT,
        failure_resource_ref="res-a",
        correlated_events=events,
        window=WINDOW,
    )
    second = t1_causal_chain(
        failure_event_id="fail-1",
        failure_at=FAIL_AT,
        failure_resource_ref="res-a",
        correlated_events=list(reversed(events)),
        window=WINDOW,
    )
    assert first is not None
    assert second is not None
    assert first.cause == second.cause
    assert "chg" in first.cause  # self-event excluded, only real antecedent remains

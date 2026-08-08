"""Tests for :class:`LatencyRoutedCrossCheckModel` (T2 primary latency pool).

Mirrors the narrator router tests: real ``asyncio.sleep`` latency drives
warm-up + p50 selection, so no white-box access to internals is needed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import pytest
from fdai.core.quality_gate.gate import QualityCandidate
from fdai.delivery.azure.llm.latency_routed_cross_check import (
    InMemoryModelHealthTransitionSink,
    LatencyRoutedCrossCheckModel,
    ModelFailureKind,
    ModelPoolUnavailableError,
    classify_model_failure,
)
from fdai.shared.telemetry import InMemoryRoutingTransitionSink


def _candidate() -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="resource:example/rg/x",
        params={"tag_name": "owner", "tag_value": "team-a"},
        cited_rule_ids=("object-storage.owner-tag.required",),
    )


class _FixedLatencyModel:
    """CrossCheckModel that sleeps a fixed amount so the router measures it."""

    def __init__(
        self, *, delay_ms: int, result: tuple[str, Mapping[str, Any]] = ("noop", {})
    ) -> None:
        self._delay_ms = delay_ms
        self._result = result
        self.calls = 0

    async def propose(self, candidate: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
        del candidate
        self.calls += 1
        await asyncio.sleep(self._delay_ms / 1000)
        return self._result


class _RaisingModel:
    def __init__(self) -> None:
        self.calls = 0

    async def propose(self, candidate: QualityCandidate) -> tuple[str, Mapping[str, Any]]:
        del candidate
        self.calls += 1
        raise RuntimeError("upstream down")


class _StatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__("provider detail")
        self.status_code = status_code


class _FailingTransitionSink:
    async def append(self, transition: object) -> None:
        del transition
        raise RuntimeError("telemetry unavailable")


class TestConstruction:
    def test_requires_two_or_more_candidates(self) -> None:
        with pytest.raises(ValueError, match=">= 2"):
            LatencyRoutedCrossCheckModel(candidates=[("only", _FixedLatencyModel(delay_ms=1))])

    def test_rejects_duplicate_names(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            LatencyRoutedCrossCheckModel(
                candidates=[
                    ("dup", _FixedLatencyModel(delay_ms=1)),
                    ("dup", _FixedLatencyModel(delay_ms=1)),
                ]
            )


class TestRouting:
    async def test_warmup_visits_every_candidate_before_reselect(self) -> None:
        a = _FixedLatencyModel(delay_ms=2)
        b = _FixedLatencyModel(delay_ms=2)
        router = LatencyRoutedCrossCheckModel(candidates=[("a", a), ("b", b)])
        assert router.current_pick_name() == "a"  # cold, tie-broken by name
        await router.propose(_candidate())
        assert router.current_pick_name() == "b"  # a measured, b still cold
        await router.propose(_candidate())
        assert a.calls == 1
        assert b.calls == 1

    async def test_delegates_and_returns_inner_result(self) -> None:
        a = _FixedLatencyModel(delay_ms=1, result=("scale.up", {"replicas": 2}))
        b = _FixedLatencyModel(delay_ms=1)
        router = LatencyRoutedCrossCheckModel(candidates=[("a", a), ("b", b)])
        action_type, params = await router.propose(_candidate())
        assert action_type == "scale.up"
        assert params == {"replicas": 2}

    async def test_converges_to_fastest_candidate(self) -> None:
        slow = _FixedLatencyModel(delay_ms=60)
        fast = _FixedLatencyModel(delay_ms=3)
        # Name the slow one first so warm-up visits it first; steady state
        # must still converge on the fast one by p50.
        router = LatencyRoutedCrossCheckModel(candidates=[("a-slow", slow), ("b-fast", fast)])
        for _ in range(6):
            await router.propose(_candidate())
        assert router.current_pick_name() == "b-fast"
        assert fast.calls > slow.calls

    async def test_failure_penalizes_and_fails_over_within_call(self) -> None:
        boom = _RaisingModel()
        ok = _FixedLatencyModel(delay_ms=2, result=("fallback.action", {"safe": True}))
        router = LatencyRoutedCrossCheckModel(candidates=[("a", boom), ("z", ok)])

        result = await router.propose(_candidate())

        assert result == ("fallback.action", {"safe": True})
        assert boom.calls == 1
        assert ok.calls == 1

    async def test_transition_sink_failure_does_not_block_model_failover(self) -> None:
        boom = _RaisingModel()
        ok = _FixedLatencyModel(delay_ms=1, result=("fallback.action", {"safe": True}))
        router = LatencyRoutedCrossCheckModel(
            candidates=[("a", boom), ("b", ok)],
            transition_sink=_FailingTransitionSink(),
        )

        result = await router.propose(_candidate())

        assert result == ("fallback.action", {"safe": True})

    async def test_all_failures_raise_after_each_candidate_once(self) -> None:
        first = _RaisingModel()
        second = _RaisingModel()
        router = LatencyRoutedCrossCheckModel(candidates=[("a", first), ("b", second)])

        with pytest.raises(RuntimeError, match="upstream down"):
            await router.propose(_candidate())

        assert first.calls == 1
        assert second.calls == 1

    async def test_cooldown_skips_failed_candidate_then_allows_recovery_probe(self) -> None:
        now = [100.0]
        boom = _RaisingModel()
        ok = _FixedLatencyModel(delay_ms=1)
        router = LatencyRoutedCrossCheckModel(
            candidates=[("a", boom), ("b", ok)],
            clock=lambda: now[0],
        )

        await router.propose(_candidate())
        assert router.current_pick_name() == "b"
        state = {row["deployment"]: row for row in router.stats()}
        assert state["a"]["last_failure_kind"] == "unknown"
        assert state["a"]["cooldown_remaining_seconds"] == 30

        now[0] += 31
        assert router.current_pick_name() == "a"

    async def test_failure_and_recovery_transitions_are_role_scoped(self) -> None:
        now = [100.0]
        transitions = InMemoryModelHealthTransitionSink()
        first = _RaisingModel()
        fallback = _FixedLatencyModel(delay_ms=1)
        router = LatencyRoutedCrossCheckModel(
            candidates=[("a", first), ("b", fallback)],
            clock=lambda: now[0],
            transition_sink=transitions,
            model_role="narrator",
        )
        await router.propose(_candidate())
        first.propose = fallback.propose  # type: ignore[method-assign]
        now[0] += 31
        await router.propose(_candidate())

        assert [event.status for event in transitions.transitions] == [
            "unhealthy",
            "selected",
            "recovered",
            "selected",
        ]
        assert all(event.model_role == "narrator" for event in transitions.transitions)
        assert transitions.transitions[0].failure_kind is ModelFailureKind.UNKNOWN
        assert transitions.transitions[0].cooldown_seconds == 30
        assert transitions.transitions[1].reason == "failover_after_1_candidate_failure"

    async def test_model_router_emits_stable_selection_transition(self) -> None:
        transitions = InMemoryRoutingTransitionSink()
        router = LatencyRoutedCrossCheckModel(
            candidates=[
                ("a", _FixedLatencyModel(delay_ms=1)),
                ("b", _FixedLatencyModel(delay_ms=1)),
            ],
            routing_transition_sink=transitions,
        )

        await router.propose(_candidate())

        assert transitions.transitions[0].domain == "model"
        assert transitions.transitions[0].outcome == "selected"

    async def test_all_candidates_in_cooldown_fail_fast_on_next_call(self) -> None:
        now = [100.0]
        first = _RaisingModel()
        second = _RaisingModel()
        router = LatencyRoutedCrossCheckModel(
            candidates=[("a", first), ("b", second)],
            clock=lambda: now[0],
        )
        with pytest.raises(RuntimeError, match="upstream down"):
            await router.propose(_candidate())

        with pytest.raises(ModelPoolUnavailableError, match="cooling down"):
            await router.propose(_candidate())
        assert first.calls == 1
        assert second.calls == 1

    async def test_records_chosen_deployment_for_audit(self, caplog: Any) -> None:
        a = _FixedLatencyModel(delay_ms=1)
        b = _FixedLatencyModel(delay_ms=1)
        router = LatencyRoutedCrossCheckModel(candidates=[("a", a), ("b", b)])
        with caplog.at_level(
            logging.INFO, logger="fdai.delivery.azure.llm.latency_routed_cross_check"
        ):
            await router.propose(_candidate())
        pick_logs = [r for r in caplog.records if r.message == "t2_primary_router.pick"]
        assert len(pick_logs) == 1
        assert getattr(pick_logs[0], "chose", None) == "a"

    async def test_stats_reports_per_candidate_samples(self) -> None:
        a = _FixedLatencyModel(delay_ms=1)
        b = _FixedLatencyModel(delay_ms=1)
        router = LatencyRoutedCrossCheckModel(candidates=[("a", a), ("b", b)])
        # Fresh: every candidate present with zero samples.
        fresh = {row["deployment"]: row for row in router.stats()}
        assert set(fresh) == {"a", "b"}
        assert all(row["samples"] == 0 for row in fresh.values())
        # After one call the picked candidate has a recorded sample.
        await router.propose(_candidate())
        after = {row["deployment"]: row for row in router.stats()}
        assert after["a"]["samples"] == 1
        assert isinstance(after["a"]["p50_ms"], (int, float))


@pytest.mark.parametrize(
    ("error", "kind"),
    (
        (_StatusError(401), ModelFailureKind.AUTH),
        (_StatusError(429), ModelFailureKind.RATE_LIMIT),
        (_StatusError(503), ModelFailureKind.OVERLOADED),
        (TimeoutError(), ModelFailureKind.TIMEOUT),
        (ConnectionError(), ModelFailureKind.TRANSPORT),
        (RuntimeError(), ModelFailureKind.UNKNOWN),
    ),
)
def test_failure_classification(error: Exception, kind: ModelFailureKind) -> None:
    assert classify_model_failure(error) is kind

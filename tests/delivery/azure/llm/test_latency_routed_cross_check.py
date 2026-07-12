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
    LatencyRoutedCrossCheckModel,
)


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

    async def test_failure_penalizes_and_reraises(self) -> None:
        boom = _RaisingModel()
        ok = _FixedLatencyModel(delay_ms=2)
        router = LatencyRoutedCrossCheckModel(candidates=[("a", boom), ("z", ok)])
        with pytest.raises(RuntimeError, match="upstream down"):
            await router.propose(_candidate())  # cold -> picks "a"
        # "a" carries a penalty sample; the still-cold "z" is picked next.
        assert router.current_pick_name() == "z"

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

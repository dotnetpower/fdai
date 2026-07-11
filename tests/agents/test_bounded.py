"""Bounded LRU containers - eviction correctness + agent memory bounds."""

from __future__ import annotations

import asyncio

import pytest

from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents.norns import Norns


class TestBoundedLruSet:
    def test_rejects_bad_maxsize(self) -> None:
        with pytest.raises(ValueError, match="maxsize"):
            BoundedLruSet(0)

    def test_evicts_oldest_past_cap(self) -> None:
        s: BoundedLruSet[str] = BoundedLruSet(2)
        s.add("a")
        s.add("b")
        s.add("c")  # evicts "a"
        assert len(s) == 2
        assert "a" not in s
        assert "b" in s
        assert "c" in s

    def test_contains_is_pure(self) -> None:
        """A membership check must NOT reorder eviction (pure __contains__)."""
        s: BoundedLruSet[str] = BoundedLruSet(2)
        s.add("a")
        s.add("b")
        assert "a" in s  # pure: does not refresh a
        s.add("c")  # evicts a (oldest by insertion), not b
        assert "a" not in s
        assert "b" in s

    def test_readd_refreshes(self) -> None:
        s: BoundedLruSet[str] = BoundedLruSet(2)
        s.add("a")
        s.add("b")
        s.add("a")  # re-add refreshes a -> order becomes [b, a]
        s.add("c")  # evicts b, not a
        assert "a" in s
        assert "b" not in s

    def test_readd_does_not_grow(self) -> None:
        s: BoundedLruSet[str] = BoundedLruSet(3)
        for _ in range(100):
            s.add("same")
        assert len(s) == 1


class TestBoundedLruDict:
    def test_evicts_lru_on_insert(self) -> None:
        d: BoundedLruDict[str, int] = BoundedLruDict(2)
        d.set("a", 1)
        d.set("b", 2)
        d.set("c", 3)  # evicts "a"
        assert len(d) == 2
        assert d.get("a") is None
        assert d.get("b") == 2

    def test_get_marks_mru(self) -> None:
        d: BoundedLruDict[str, int] = BoundedLruDict(2)
        d.set("a", 1)
        d.set("b", 2)
        assert d.get("a") == 1  # touch a
        d.set("c", 3)  # evicts b
        assert d.get("a") == 1
        assert d.get("b") is None

    def test_pop(self) -> None:
        d: BoundedLruDict[str, int] = BoundedLruDict(2)
        d.set("a", 1)
        assert d.pop("a") == 1
        assert d.pop("missing", -1) == -1
        assert len(d) == 0


def test_norns_counted_correlations_is_bounded() -> None:
    """The per-event dedup guard is the bounded LRU container, not an
    unbounded set - so a long-lived learner cannot leak one entry per action.
    Eviction correctness itself is covered by TestBoundedLruSet."""
    norns = Norns(min_outcome_samples=100, rollback_alarm_rate=0.99)
    assert isinstance(norns._counted_correlations, BoundedLruSet)  # noqa: SLF001
    # The sibling fingerprint maps share the same unbounded (content-hash)
    # keyspace and MUST also be bounded.
    assert isinstance(norns._proposed, BoundedLruSet)  # noqa: SLF001
    assert isinstance(norns._fingerprint_counter, BoundedLruDict)  # noqa: SLF001
    for i in range(200):
        asyncio.run(
            norns.on_typed_message(
                "object.audit-entry",
                {"action_type": "a", "result": "success", "correlation_id": f"c{i}"},
            )
        )
    assert len(norns._counted_correlations) == 200  # noqa: SLF001


def test_forseti_domain_advice_is_bounded() -> None:
    from fdai.agents.forseti import Forseti

    forseti = Forseti(bus=None)
    assert isinstance(forseti._domain_advice, BoundedLruDict)  # noqa: SLF001
    assert isinstance(forseti._domain_impact, BoundedLruDict)  # noqa: SLF001

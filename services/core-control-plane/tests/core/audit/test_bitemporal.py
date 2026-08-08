"""Tests for :mod:`fdai.core.audit.bitemporal`."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.core.audit.bitemporal import (
    BitemporalQueryError,
    snapshot_at,
)


@dataclass(frozen=True, slots=True)
class _StubAuditItem:
    seq: int
    correlation_id: str | None
    entry: Mapping[str, Any]
    action_kind: str = "state_change"
    mode: str = "shadow"
    entry_hash: str = "h"
    recorded_at: str = ""


def _at(y: int, m: int, d: int, hh: int = 0) -> datetime:
    return datetime(y, m, d, hh, 0, 0, tzinfo=UTC)


def _iso(y: int, m: int, d: int, hh: int = 0) -> str:
    return _at(y, m, d, hh).isoformat()


def test_snapshot_folds_state_in_effective_time_order() -> None:
    items = [
        _StubAuditItem(
            seq=1,
            correlation_id=None,
            entry={"state": {"tier": "S1"}, "effective_at": _iso(2026, 1, 1)},
            recorded_at=_iso(2026, 1, 2),
        ),
        _StubAuditItem(
            seq=2,
            correlation_id=None,
            entry={"state": {"tier": "S2", "region": "us"}, "effective_at": _iso(2026, 2, 1)},
            recorded_at=_iso(2026, 2, 2),
        ),
    ]
    snap = snapshot_at("res-1", items, as_of=_at(2026, 3, 1))
    assert snap.state == {"tier": "S2", "region": "us"}
    assert snap.source_seqs == (1, 2)


def test_snapshot_coerces_naive_query_cutoff_to_utc() -> None:
    # as_of passed naive (no tz) must be coerced to UTC, not raise TypeError
    # against the UTC-aware audit timestamps.
    items = [
        _StubAuditItem(
            seq=1,
            correlation_id=None,
            entry={"state": {"tier": "S1"}, "effective_at": _iso(2026, 1, 1)},
            recorded_at=_iso(2026, 1, 2),
        ),
    ]
    naive_as_of = datetime(2026, 3, 1, 0, 0, 0)  # no tzinfo
    snap = snapshot_at("res-1", items, as_of=naive_as_of)  # must not raise
    assert snap.state == {"tier": "S1"}


def test_snapshot_coerces_naive_effective_at_in_entry() -> None:
    # A fork adapter that writes a naive effective_at must not trip the
    # eff_ts > effective comparison with a TypeError.
    items = [
        _StubAuditItem(
            seq=1,
            correlation_id=None,
            entry={"state": {"tier": "S1"}, "effective_at": "2026-01-01T00:00:00"},  # naive
            recorded_at=_iso(2026, 1, 2),
        ),
    ]
    snap = snapshot_at("res-1", items, as_of=_at(2026, 3, 1))  # must not raise
    assert snap.state == {"tier": "S1"}


def test_as_of_cuts_off_later_records() -> None:
    items = [
        _StubAuditItem(
            seq=1,
            correlation_id=None,
            entry={"state": {"tier": "S1"}},
            recorded_at=_iso(2026, 1, 1),
        ),
        _StubAuditItem(
            seq=2,
            correlation_id=None,
            entry={"state": {"tier": "S2"}},
            recorded_at=_iso(2026, 3, 1),
        ),
    ]
    snap = snapshot_at("res-1", items, as_of=_at(2026, 2, 1))
    # Item 2 was recorded AFTER as_of - MUST be excluded from state AND provenance.
    assert snap.state == {"tier": "S1"}
    assert snap.source_seqs == (1,)


def test_effective_cutoff_excludes_future_effective() -> None:
    items = [
        _StubAuditItem(
            seq=1,
            correlation_id=None,
            entry={"state": {"tier": "S1"}, "effective_at": _iso(2026, 1, 1)},
            recorded_at=_iso(2026, 1, 2),
        ),
        _StubAuditItem(
            seq=2,
            correlation_id=None,
            entry={"state": {"tier": "S2"}, "effective_at": _iso(2026, 6, 1)},
            recorded_at=_iso(2026, 6, 2),
        ),
    ]
    # We know about both entries (as_of after both recorded_at) but only
    # the earlier one takes effect within the effective cutoff.
    snap = snapshot_at("res-1", items, as_of=_at(2026, 7, 1), effective=_at(2026, 3, 1))
    assert snap.state == {"tier": "S1"}
    # Provenance includes both because both were KNOWN to the system by
    # as_of; the effective filter only affected which state contributed.
    assert snap.source_seqs == (1, 2)


def test_missing_state_block_still_counts_toward_provenance() -> None:
    items = [
        _StubAuditItem(
            seq=1,
            correlation_id=None,
            entry={"decision": "denied", "reason": "policy"},
            recorded_at=_iso(2026, 1, 1),
        )
    ]
    snap = snapshot_at("res-1", items, as_of=_at(2026, 2, 1))
    assert snap.state == {}
    assert snap.source_seqs == (1,)


def test_snapshot_defaults_effective_to_as_of() -> None:
    items = [
        _StubAuditItem(
            seq=1,
            correlation_id=None,
            entry={"state": {"tier": "S1"}, "effective_at": _iso(2026, 1, 1)},
            recorded_at=_iso(2026, 1, 2),
        )
    ]
    snap = snapshot_at("res-1", items, as_of=_at(2026, 6, 1))
    assert snap.effective == snap.as_of


def test_rejects_empty_resource_id() -> None:
    with pytest.raises(BitemporalQueryError):
        snapshot_at("", [], as_of=_at(2026, 1, 1))


def test_rejects_future_effective_relative_to_as_of() -> None:
    with pytest.raises(BitemporalQueryError):
        snapshot_at(
            "res-1",
            [],
            as_of=_at(2026, 1, 1),
            effective=_at(2026, 6, 1),  # effective > as_of - forbidden.
        )


def test_deterministic_across_repeated_calls() -> None:
    items = [
        _StubAuditItem(
            seq=1,
            correlation_id=None,
            entry={"state": {"tier": "S1"}, "effective_at": _iso(2026, 1, 1)},
            recorded_at=_iso(2026, 1, 2),
        ),
        _StubAuditItem(
            seq=2,
            correlation_id=None,
            entry={"state": {"tier": "S2"}, "effective_at": _iso(2026, 2, 1)},
            recorded_at=_iso(2026, 2, 2),
        ),
    ]
    first = snapshot_at("res-1", items, as_of=_at(2026, 3, 1))
    second = snapshot_at("res-1", items, as_of=_at(2026, 3, 1))
    assert first.as_json() == second.as_json()


def test_unparseable_recorded_at_is_dropped() -> None:
    items = [
        _StubAuditItem(
            seq=1,
            correlation_id=None,
            entry={"state": {"tier": "S1"}, "effective_at": _iso(2026, 1, 1)},
            recorded_at="not-a-timestamp",
        )
    ]
    snap = snapshot_at("res-1", items, as_of=_at(2026, 6, 1))
    assert snap.state == {}
    assert snap.source_seqs == ()


def test_effective_at_ordering_uses_seq_as_tie_breaker() -> None:
    ts = _iso(2026, 1, 1)
    items = [
        _StubAuditItem(
            seq=1,
            correlation_id=None,
            entry={"state": {"v": "a"}, "effective_at": ts},
            recorded_at=ts,
        ),
        _StubAuditItem(
            seq=2,
            correlation_id=None,
            entry={"state": {"v": "b"}, "effective_at": ts},
            recorded_at=ts,
        ),
    ]
    snap = snapshot_at("res-1", items, as_of=_at(2026, 2, 1))
    # Higher seq wins when effective_at ties.
    assert snap.state == {"v": "b"}

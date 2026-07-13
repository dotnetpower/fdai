"""StormCoordinator - deterministic incident-command sequencing.

Covers the storm-handling contract: storm detection over a sliding
window, reproducible severity/blast-radius ordering, capped waves so a
fan-out does not execute in parallel, and a raised HIL bar while a storm
is active.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.incident import (
    StormCoordinator,
    StormSignal,
)
from fdai.shared.contracts.models import IncidentSeverity

_NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def _sig(
    sid: str,
    sev: IncidentSeverity,
    *,
    resource: str = "r",
    blast: int = 1,
    ago_s: int = 0,
) -> StormSignal:
    return StormSignal(
        signal_id=sid,
        severity=sev,
        resource_ref=resource,
        blast_radius=blast,
        arrived_at=_NOW - timedelta(seconds=ago_s),
    )


def test_storm_detected_at_threshold() -> None:
    coord = StormCoordinator(storm_threshold=5)
    signals = [_sig(f"s{i}", IncidentSeverity.SEV3) for i in range(5)]
    policy = coord.assess(signals, now=_NOW)
    assert policy.active is True
    assert policy.signal_count == 5
    assert policy.concurrency_cap == 1  # storm tightens concurrency
    assert policy.escalate_hil_at_or_above is IncidentSeverity.SEV3


def test_nominal_below_threshold() -> None:
    coord = StormCoordinator(storm_threshold=5, base_concurrency=3)
    signals = [_sig(f"s{i}", IncidentSeverity.SEV3) for i in range(4)]
    policy = coord.assess(signals, now=_NOW)
    assert policy.active is False
    assert policy.concurrency_cap == 3
    assert policy.escalate_hil_at_or_above is None


def test_old_signals_fall_out_of_window() -> None:
    coord = StormCoordinator(storm_threshold=3, window=timedelta(minutes=5))
    signals = [
        _sig("a", IncidentSeverity.SEV2, ago_s=10),
        _sig("b", IncidentSeverity.SEV2, ago_s=20),
        _sig("c", IncidentSeverity.SEV2, ago_s=600),  # 10 min ago -> excluded
    ]
    policy = coord.assess(signals, now=_NOW)
    assert policy.signal_count == 2
    assert policy.active is False


def test_sequence_orders_by_severity_then_blast() -> None:
    coord = StormCoordinator()
    signals = [
        _sig("low", IncidentSeverity.SEV4),
        _sig("crit-small", IncidentSeverity.SEV1, blast=1),
        _sig("crit-big", IncidentSeverity.SEV1, blast=9),
        _sig("mid", IncidentSeverity.SEV3),
    ]
    steps = coord.sequence(signals, concurrency_cap=2)
    assert [s.signal_id for s in steps] == ["crit-big", "crit-small", "mid", "low"]
    # Waves of 2 under the cap.
    assert [s.wave for s in steps] == [0, 0, 1, 1]


def test_storm_plan_serializes_into_single_waves() -> None:
    coord = StormCoordinator(storm_threshold=3, storm_concurrency=1)
    signals = [_sig(f"s{i}", IncidentSeverity.SEV2) for i in range(4)]
    policy, steps = coord.plan(signals, now=_NOW)
    assert policy.active is True
    # cap 1 => each step its own wave (strictly serial).
    assert [s.wave for s in steps] == [0, 1, 2, 3]


def test_storm_plan_excludes_stale_signals_from_steps() -> None:
    # A stale signal (outside the window) neither counts toward the storm nor
    # gets a remediation step - plan sequences only the in-window set, so it
    # cannot remediate an old, possibly-already-resolved signal.
    coord = StormCoordinator(storm_threshold=3, window=timedelta(minutes=5))
    signals = [
        _sig("a", IncidentSeverity.SEV2, ago_s=10),
        _sig("b", IncidentSeverity.SEV2, ago_s=20),
        _sig("c", IncidentSeverity.SEV2, ago_s=30),
        # SEV1 so it would sort FIRST if wrongly included - proves exclusion.
        _sig("stale", IncidentSeverity.SEV1, ago_s=600),
    ]
    policy, steps = coord.plan(signals, now=_NOW)
    assert policy.active is True
    assert policy.signal_count == 3
    step_ids = {s.signal_id for s in steps}
    assert "stale" not in step_ids
    assert step_ids == {"a", "b", "c"}


def test_sequence_is_deterministic() -> None:
    coord = StormCoordinator()
    signals = [
        _sig("b", IncidentSeverity.SEV2, resource="r2"),
        _sig("a", IncidentSeverity.SEV2, resource="r1"),
    ]
    first = coord.sequence(signals, concurrency_cap=5)
    second = coord.sequence(list(reversed(signals)), concurrency_cap=5)
    assert [s.signal_id for s in first] == [s.signal_id for s in second]


def test_invalid_config_rejected() -> None:
    with pytest.raises(ValueError, match="storm_threshold"):
        StormCoordinator(storm_threshold=0)
    with pytest.raises(ValueError, match="window"):
        StormCoordinator(window=timedelta(0))
    with pytest.raises(ValueError, match="concurrency"):
        StormCoordinator(base_concurrency=0)
    coord = StormCoordinator()
    with pytest.raises(ValueError, match="concurrency_cap"):
        coord.sequence([], concurrency_cap=0)

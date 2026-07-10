"""H9: investigation rank functions are fail-safe against unmapped values.

An unmapped Severity / Priority (e.g. a future enum value) must sort last
rather than raising KeyError and crashing the recommendation reducer for
the whole investigation.
"""

from __future__ import annotations

import pytest

from fdai.core.investigation.contract import Priority, priority_rank, severity_rank
from fdai.shared.contracts.models import Severity


def test_severity_rank_orders_critical_first() -> None:
    ranks = [severity_rank(s) for s in Severity]
    # Every real member maps to a finite rank strictly below the sentinel.
    assert all(r < 99 for r in ranks)
    assert severity_rank(Severity.CRITICAL) < severity_rank(Severity.LOW)


def test_priority_rank_orders_p1_first() -> None:
    assert priority_rank(Priority.P1) < priority_rank(Priority.P3)
    assert all(priority_rank(p) < 99 for p in Priority)


def test_severity_rank_unmapped_value_is_fail_safe() -> None:
    # A value outside the enum (foreign / future) must not raise; it sorts
    # last so the reducer degrades instead of crashing.
    assert severity_rank("unmapped_severity") == 99  # type: ignore[arg-type]


def test_priority_rank_unmapped_value_is_fail_safe() -> None:
    assert priority_rank("unmapped_priority") == 99  # type: ignore[arg-type]


def test_ranks_sort_a_mixed_list_without_error() -> None:
    findings = ["low", "critical", "unmapped", "high"]
    ordered = sorted(findings, key=lambda s: severity_rank(s))  # type: ignore[arg-type]
    assert ordered[0] == "critical"
    assert ordered[-1] == "unmapped"  # unknown sinks to the bottom


@pytest.mark.parametrize("severity", list(Severity))
def test_every_severity_member_has_distinct_rank(severity: Severity) -> None:
    assert isinstance(severity_rank(severity), int)

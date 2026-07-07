"""Golden-fixture metrics regression test.

Loads a synthetic audit-log trace and asserts that every declared
dashboard metric is derivable from the fixture. Removing a required
field from the fixture MUST break the specific metric assertion it
supports - that is the acceptance criterion for W1.8.
"""

from __future__ import annotations

import copy
import json
from math import isclose
from pathlib import Path

import pytest

from aiopspilot.shared.telemetry.metrics_derivation import derive_dashboard_metrics

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "golden_trace.json"


def _load_fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_golden_fixture_reproduces_every_dashboard_metric() -> None:
    fixture = _load_fixture()
    entries = fixture["entries"]
    expected = fixture["expected_metrics"]
    assert isinstance(entries, list)
    assert isinstance(expected, dict)

    metrics = derive_dashboard_metrics(entries)

    assert metrics.event_count == expected["event_count"]
    assert isclose(metrics.auto_resolution_rate, expected["auto_resolution_rate"], abs_tol=1e-9)
    assert isclose(metrics.hil_rate, expected["hil_rate"], abs_tol=1e-9)
    assert isclose(metrics.abstain_rate, expected["abstain_rate"], abs_tol=1e-9)
    assert isclose(metrics.deny_rate, expected["deny_rate"], abs_tol=1e-9)
    assert isclose(
        metrics.human_touchpoints_per_100_events,
        expected["human_touchpoints_per_100_events"],
        abs_tol=1e-9,
    )
    assert isclose(metrics.shadow_share, expected["shadow_share"], abs_tol=1e-9)
    assert isclose(metrics.enforce_share, expected["enforce_share"], abs_tol=1e-9)
    assert dict(metrics.per_tier) == expected["per_tier"]


def test_removing_decision_field_breaks_decision_metrics() -> None:
    """Acceptance: dropping a trace attribute fails a specific metric assertion."""
    fixture = _load_fixture()
    entries = copy.deepcopy(fixture["entries"])
    del entries[0]["decision"]  # remove required field from the first entry

    with pytest.raises(KeyError):
        derive_dashboard_metrics(entries)


def test_removing_mode_field_breaks_mode_metrics() -> None:
    fixture = _load_fixture()
    entries = copy.deepcopy(fixture["entries"])
    del entries[5]["mode"]

    with pytest.raises(KeyError):
        derive_dashboard_metrics(entries)


def test_removing_tier_field_breaks_per_tier_metric() -> None:
    fixture = _load_fixture()
    entries = copy.deepcopy(fixture["entries"])
    del entries[2]["tier"]

    with pytest.raises(KeyError):
        derive_dashboard_metrics(entries)


def test_unknown_decision_value_is_rejected() -> None:
    fixture = _load_fixture()
    entries = copy.deepcopy(fixture["entries"])
    entries[0]["decision"] = "hesitate"  # not one of auto/hil/abstain/deny

    with pytest.raises(ValueError, match="unknown decision"):
        derive_dashboard_metrics(entries)


def test_unknown_mode_value_is_rejected() -> None:
    """`mode` MUST be shadow or enforce; anything else fails the derivation."""
    fixture = _load_fixture()
    entries = copy.deepcopy(fixture["entries"])
    entries[0]["mode"] = "dry-run"  # not one of shadow/enforce

    with pytest.raises(ValueError, match="unknown mode"):
        derive_dashboard_metrics(entries)


def test_empty_audit_batch_returns_zero_metrics() -> None:
    metrics = derive_dashboard_metrics([])
    assert metrics.event_count == 0
    assert metrics.auto_resolution_rate == 0.0
    assert metrics.hil_rate == 0.0
    assert metrics.human_touchpoints_per_100_events == 0.0
    assert dict(metrics.per_tier) == {}


def test_fixture_only_uses_placeholder_uuids() -> None:
    """Every UUID in the golden fixture MUST be the reserved zero form."""
    import re

    body = FIXTURE_PATH.read_text(encoding="utf-8")
    nonzero = re.findall(
        r"\b(?!00000000-0000-0000-0000-[0-9a-fA-F]{12}\b)"
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        body,
    )
    assert not nonzero, f"golden fixture contains real UUIDs: {nonzero[:3]}"

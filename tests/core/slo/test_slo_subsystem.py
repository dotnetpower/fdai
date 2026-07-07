"""SLO subsystem - schema, models, burn-rate evaluator, registry."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from fdai.core.slo import (
    SLI,
    SLO,
    BurnRate,
    BurnRateEvaluator,
    ErrorBudget,
    SLIKind,
    SloRegistry,
    SloRegistryError,
)
from fdai.core.slo.burn_rate import build_alerts
from fdai.core.slo.models import BurnRateAlertDef

# ---------------------------------------------------------------------------
# SLO / SLI value objects
# ---------------------------------------------------------------------------


def test_slo_rejects_out_of_range_objective() -> None:
    with pytest.raises(ValueError, match="objective_ratio"):
        SLO(id="a", objective_ratio=0.0, window_days=7, sli=_sli())
    with pytest.raises(ValueError, match="objective_ratio"):
        SLO(id="a", objective_ratio=1.5, window_days=7, sli=_sli())


def test_slo_error_budget_fraction_matches_1_minus_objective() -> None:
    slo = SLO(id="a", objective_ratio=0.999, window_days=28, sli=_sli())
    assert slo.error_budget_fraction == pytest.approx(0.001)


def _sli() -> SLI:
    return SLI(
        kind=SLIKind.AVAILABILITY,
        good_query="stub_good",
        total_query="stub_total",
        labels={},
    )


# ---------------------------------------------------------------------------
# ErrorBudget arithmetic
# ---------------------------------------------------------------------------


def test_error_budget_remaining_full_when_no_bad_events() -> None:
    eb = ErrorBudget(slo_id="a", good_events=1000, total_events=1000, objective_ratio=0.99)
    assert eb.budget_remaining_fraction == pytest.approx(1.0)


def test_error_budget_remaining_zero_when_fully_burned() -> None:
    # 99% objective + 1000 events allows up to 10 bad. 10 bad -> 0 remaining.
    eb = ErrorBudget(slo_id="a", good_events=990, total_events=1000, objective_ratio=0.99)
    assert eb.budget_remaining_fraction == pytest.approx(0.0)


def test_error_budget_remaining_clamped_at_zero_on_breach() -> None:
    # 20 bad events against a budget of 10 -> negative would be -1.0;
    # clamp at 0.0 (breach is captured by the burn-rate value itself).
    eb = ErrorBudget(slo_id="a", good_events=980, total_events=1000, objective_ratio=0.99)
    assert eb.budget_remaining_fraction == pytest.approx(0.0)


def test_error_budget_rejects_impossible_input() -> None:
    with pytest.raises(ValueError):
        ErrorBudget(slo_id="a", good_events=-1, total_events=100, objective_ratio=0.9)
    with pytest.raises(ValueError):
        ErrorBudget(slo_id="a", good_events=101, total_events=100, objective_ratio=0.9)


# ---------------------------------------------------------------------------
# BurnRate arithmetic
# ---------------------------------------------------------------------------


def test_burn_rate_of_1_means_burning_at_allowed_pace() -> None:
    # objective 0.9 -> 10% bad allowed. bad_ratio 10% => rate 1.0
    br = BurnRate(window_minutes=5, good_events=900, total_events=1000, objective_ratio=0.9)
    assert br.rate == pytest.approx(1.0)


def test_burn_rate_of_10_means_10x_faster_than_allowed() -> None:
    # objective 0.99 -> 1% bad allowed. bad_ratio 10% => rate 10.0
    br = BurnRate(window_minutes=5, good_events=900, total_events=1000, objective_ratio=0.99)
    assert br.rate == pytest.approx(10.0)


def test_burn_rate_zero_events_is_zero_rate_not_undefined() -> None:
    br = BurnRate(window_minutes=5, good_events=0, total_events=0, objective_ratio=0.99)
    assert br.rate == 0.0


def test_burn_rate_infinite_when_perfect_objective_and_any_bad() -> None:
    br = BurnRate(window_minutes=5, good_events=99, total_events=100, objective_ratio=1.0)
    assert br.rate == float("inf")


# ---------------------------------------------------------------------------
# BurnRateEvaluator - multi-window multi-burn-rate
# ---------------------------------------------------------------------------


def _slo_with_alert() -> SLO:
    return SLO(
        id="api.checkout.availability",
        objective_ratio=0.999,
        window_days=28,
        sli=_sli(),
        burn_rate_alerts=(
            BurnRateAlertDef(
                name="fast-burn",
                short_window_minutes=5,
                long_window_minutes=60,
                burn_rate_threshold=14.4,
                severity="sev2",
            ),
        ),
    )


def test_burn_rate_evaluator_fires_only_when_both_windows_exceed() -> None:
    slo = _slo_with_alert()
    evaluator = BurnRateEvaluator()

    # Both windows breach (bad ratio 3% each; allowed 0.1% -> rate 30 >> 14.4).
    alerts_breach = build_alerts(slo=slo, samples={5: (9700, 10000), 60: (9700, 10000)})
    assert len(evaluator.evaluate(alerts_breach)) == 1

    # Only short window breaches (long window healthy) - MUST NOT fire.
    alerts_short_only = build_alerts(slo=slo, samples={5: (9700, 10000), 60: (99990, 100000)})
    assert evaluator.evaluate(alerts_short_only) == ()

    # Only long window breaches - MUST NOT fire.
    alerts_long_only = build_alerts(slo=slo, samples={5: (9999, 10000), 60: (97000, 100000)})
    assert evaluator.evaluate(alerts_long_only) == ()

    # Neither breaches.
    alerts_healthy = build_alerts(slo=slo, samples={5: (9999, 10000), 60: (99990, 100000)})
    assert evaluator.evaluate(alerts_healthy) == ()


def test_burn_rate_build_alerts_fails_closed_on_missing_window() -> None:
    slo = _slo_with_alert()
    with pytest.raises(KeyError):
        build_alerts(slo=slo, samples={5: (10000, 10000)})  # missing 60


# ---------------------------------------------------------------------------
# SloRegistry - directory load + validation
# ---------------------------------------------------------------------------


def test_registry_load_empty_directory_returns_empty(tmp_path: Path) -> None:
    reg = SloRegistry.from_directory(tmp_path)
    assert reg.all() == ()
    assert reg.get("anything") is None


def test_registry_load_valid_yaml_and_indexes_by_id(tmp_path: Path) -> None:
    (tmp_path / "checkout.yaml").write_text(
        """
schema_version: 1.0.0
id: api.checkout.availability
description: 99.9% of checkout requests succeed
objective_ratio: 0.999
window_days: 28
sli:
  kind: availability
  good_query: "checkout_ok"
  total_query: "checkout_total"
  labels:
    service: checkout
burn_rate_alerts:
  - name: fast-burn
    short_window_minutes: 5
    long_window_minutes: 60
    burn_rate_threshold: 14.4
    severity: sev2
""",
        encoding="utf-8",
    )
    reg = SloRegistry.from_directory(tmp_path)
    slo = reg.get("api.checkout.availability")
    assert slo is not None
    assert slo.objective_ratio == pytest.approx(0.999)
    assert slo.sli.kind is SLIKind.AVAILABILITY
    assert len(slo.burn_rate_alerts) == 1
    assert slo.burn_rate_alerts[0].severity == "sev2"


def test_registry_load_rejects_schema_violation(tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text(
        """
schema_version: 1.0.0
id: bad.slo
objective_ratio: 2.0
window_days: 7
sli:
  kind: availability
  good_query: "g"
  total_query: "t"
""",
        encoding="utf-8",
    )
    with pytest.raises(SloRegistryError):
        SloRegistry.from_directory(tmp_path)


def test_registry_load_rejects_duplicate_id(tmp_path: Path) -> None:
    body = """
schema_version: 1.0.0
id: dup.id
objective_ratio: 0.99
window_days: 7
sli:
  kind: availability
  good_query: "g"
  total_query: "t"
"""
    (tmp_path / "a.yaml").write_text(body, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(body, encoding="utf-8")
    with pytest.raises(SloRegistryError, match="duplicate SLO id"):
        SloRegistry.from_directory(tmp_path)


# Ref used to keep the imports minimal - `datetime` documents that the
# window semantic is UTC even though the current tests don't need it.
_ = (datetime, UTC)

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.readiness.self_health import (
    SelfHealthCatalogError,
    SelfHealthObservation,
    SelfHealthSignal,
    load_self_health_catalog,
)
from fdai.runtime.bootstrap_core import _load_self_health_catalog
from fdai.runtime.readiness import RuntimeReadinessState, StartupReadinessRuntime

ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


def _catalog():
    matrix = load_matrix_from_yaml(ROOT / "config" / "notifications-matrix.yaml")
    route_fallbacks = {name: route.on_all_fail.value for name, route in matrix.routes.items()}
    return load_self_health_catalog(
        ROOT / "config" / "self-health-signals.yaml",
        route_fallbacks=route_fallbacks,
    )


def test_shipped_catalog_covers_every_required_signal_and_route() -> None:
    catalog = _catalog()

    assert set(catalog.policies) == set(SelfHealthSignal)
    assert len(catalog.policies) == 15
    assert all(policy.owner_lane.value == "operational" for policy in catalog.policies.values())
    assert all(policy.fallback == "hil_escalate" for policy in catalog.policies.values())


def test_production_bootstrap_loads_the_complete_catalog() -> None:
    assert set(_load_self_health_catalog().policies) == set(SelfHealthSignal)


@pytest.mark.parametrize("signal", list(SelfHealthSignal))
def test_stale_observation_alerts_without_authority(signal: SelfHealthSignal) -> None:
    catalog = _catalog()
    policy = catalog.policies[signal]
    decision = catalog.evaluate(
        SelfHealthObservation(
            signal=signal,
            value=policy.threshold,
            observed_at=NOW - timedelta(seconds=policy.maximum_age_seconds + 1),
            source="runtime:test",
        ),
        now=NOW,
    )

    assert decision.alert is True
    assert decision.reason == "observation_stale"
    assert decision.execution_authority is False


@pytest.mark.parametrize("signal", list(SelfHealthSignal))
def test_threshold_boundary_is_healthy_and_crossing_it_alerts(
    signal: SelfHealthSignal,
) -> None:
    catalog = _catalog()
    policy = catalog.policies[signal]
    boundary = SelfHealthObservation(
        signal=signal,
        value=policy.threshold,
        observed_at=NOW,
        source="runtime:test",
    )
    delta = Decimal("0.01")
    breached_value = (
        policy.threshold + delta
        if policy.comparison.value == "greater_than"
        else policy.threshold - delta
    )

    assert catalog.evaluate(boundary, now=NOW).alert is False
    breached = catalog.evaluate(
        SelfHealthObservation(
            signal=signal,
            value=breached_value,
            observed_at=NOW,
            source="runtime:test",
        ),
        now=NOW,
    )
    assert breached.alert is True
    assert breached.reason == "threshold_breached"


def test_catalog_rejects_route_fallback_drift() -> None:
    with pytest.raises(SelfHealthCatalogError, match="fallback"):
        load_self_health_catalog(
            ROOT / "config" / "self-health-signals.yaml",
            route_fallbacks={
                "operational_alert": "queue_and_page_ops",
                "adapter_health": "hil_escalate",
                "kill_switch_state": "hil_escalate",
            },
        )


def test_startup_runtime_exposes_authority_neutral_self_health_evaluation() -> None:
    catalog = _catalog()
    runtime = StartupReadinessRuntime(
        coordinator=cast(Any, object()),
        state=RuntimeReadinessState(),
        refresh_interval_seconds=60,
        self_health_catalog=catalog,
    )

    decision = runtime.evaluate_self_health(
        SelfHealthObservation(
            signal=SelfHealthSignal.KILL_SWITCH_STATE,
            value=Decimal("1"),
            observed_at=NOW,
            source="state-store:kill-switch",
        ),
        now=NOW,
    )

    assert decision.route == "kill_switch_state"
    assert decision.alert is True
    assert decision.execution_authority is False

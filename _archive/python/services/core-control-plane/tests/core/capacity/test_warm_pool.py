"""Warm-capacity policy - #30 cold-start vs MTTR resolution.

Verifies each warm trigger (high severity, storm, off-hours), the
scale-to-zero default, config tunability, and deterministic output.
"""

from __future__ import annotations

import pytest
from fdai.core.capacity import (
    CapacityDecision,
    WarmCapacityConfig,
    WarmCapacityPolicy,
)
from fdai.shared.contracts.models import IncidentSeverity

# ---------------------------------------------------------------------------
# Warm triggers
# ---------------------------------------------------------------------------


def test_high_severity_forces_warm() -> None:
    policy = WarmCapacityPolicy()
    decision = policy.decide(severity=IncidentSeverity.SEV1)
    assert isinstance(decision, CapacityDecision)
    assert decision.warm_required is True
    assert decision.min_replicas == 1
    assert any("severity" in t for t in decision.triggers)


def test_storm_forces_warm_even_at_low_severity() -> None:
    policy = WarmCapacityPolicy()
    decision = policy.decide(severity=IncidentSeverity.SEV5, storm_active=True)
    assert decision.warm_required is True
    assert "storm active" in decision.triggers


def test_off_hours_forces_warm_even_at_low_severity() -> None:
    policy = WarmCapacityPolicy()
    decision = policy.decide(severity=IncidentSeverity.SEV5, off_hours=True)
    assert decision.warm_required is True
    assert any("off-hours" in t for t in decision.triggers)


def test_multiple_triggers_all_recorded() -> None:
    policy = WarmCapacityPolicy()
    decision = policy.decide(severity=IncidentSeverity.SEV1, storm_active=True, off_hours=True)
    assert decision.warm_required is True
    assert len(decision.triggers) == 3


# ---------------------------------------------------------------------------
# Scale-to-zero default
# ---------------------------------------------------------------------------


def test_low_severity_business_hours_is_scale_to_zero() -> None:
    policy = WarmCapacityPolicy()
    decision = policy.decide(severity=IncidentSeverity.SEV4)
    assert decision.warm_required is False
    assert decision.min_replicas == 0
    assert decision.triggers == ()
    assert "scale-to-zero" in decision.reason


def test_sev2_is_warm_by_default_threshold() -> None:
    policy = WarmCapacityPolicy()
    # Default threshold is SEV2 -> SEV2 and SEV1 warrant warm; SEV3 does not.
    assert policy.decide(severity=IncidentSeverity.SEV2).warm_required is True
    assert policy.decide(severity=IncidentSeverity.SEV3).warm_required is False


# ---------------------------------------------------------------------------
# Config tunability
# ---------------------------------------------------------------------------


def test_config_can_raise_severity_threshold() -> None:
    policy = WarmCapacityPolicy(WarmCapacityConfig(warm_at_or_above_severity=IncidentSeverity.SEV1))
    # Now only SEV1 warrants warm on severity alone.
    assert policy.decide(severity=IncidentSeverity.SEV2).warm_required is False
    assert policy.decide(severity=IncidentSeverity.SEV1).warm_required is True


def test_config_can_disable_storm_forcing() -> None:
    policy = WarmCapacityPolicy(WarmCapacityConfig(storm_forces_warm=False))
    decision = policy.decide(severity=IncidentSeverity.SEV5, storm_active=True)
    assert decision.warm_required is False


def test_config_can_raise_warm_replica_floor() -> None:
    policy = WarmCapacityPolicy(WarmCapacityConfig(warm_min_replicas=3))
    decision = policy.decide(severity=IncidentSeverity.SEV1)
    assert decision.min_replicas == 3


def test_warm_min_replicas_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="warm_min_replicas MUST be >= 1"):
        WarmCapacityConfig(warm_min_replicas=0)


def test_negative_cold_min_replicas_is_rejected() -> None:
    with pytest.raises(ValueError, match="cold_min_replicas MUST be >= 0"):
        WarmCapacityConfig(cold_min_replicas=-1)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_decision_is_deterministic() -> None:
    policy = WarmCapacityPolicy()
    first = policy.decide(severity=IncidentSeverity.SEV2, storm_active=True)
    second = policy.decide(severity=IncidentSeverity.SEV2, storm_active=True)
    assert first == second

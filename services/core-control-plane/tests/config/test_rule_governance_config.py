"""RuleGovernanceConfig - defaults, bounds, and cross-field validation."""

from __future__ import annotations

import pytest
from fdai.shared.config.models import RuleGovernanceConfig


def test_default_rule_governance_config() -> None:
    cfg = RuleGovernanceConfig()
    assert cfg.exemption_max_duration_days == 180
    assert cfg.exemption_alert_lead_days == 14


def test_alert_lead_must_be_shorter_than_max_duration() -> None:
    with pytest.raises(ValueError, match="exemption_alert_lead_days"):
        RuleGovernanceConfig(exemption_max_duration_days=10, exemption_alert_lead_days=10)


def test_alert_lead_longer_than_max_duration_is_rejected() -> None:
    with pytest.raises(ValueError, match="exemption_alert_lead_days"):
        RuleGovernanceConfig(exemption_max_duration_days=10, exemption_alert_lead_days=20)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("exemption_max_duration_days", 0),
        ("exemption_max_duration_days", 3651),
        ("exemption_alert_lead_days", 0),
        ("exemption_alert_lead_days", 366),
    ],
)
def test_out_of_bounds_values_are_rejected(field: str, value: int) -> None:
    with pytest.raises(ValueError):
        RuleGovernanceConfig(**{field: value})


def test_rule_governance_config_is_frozen() -> None:
    from pydantic import ValidationError

    cfg = RuleGovernanceConfig()
    with pytest.raises((AttributeError, TypeError, ValidationError)):
        cfg.exemption_max_duration_days = 1  # type: ignore[misc]

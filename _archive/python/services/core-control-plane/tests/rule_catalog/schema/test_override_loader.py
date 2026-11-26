"""load_override_from_mapping - schema + domain-boundary validation."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.rule_catalog.schema.governance_loader import (
    GovernanceLoadError,
    load_override_from_mapping,
)
from fdai.rule_catalog.schema.override import Override, OverrideMode


def _valid_disabled() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "kind": "override",
        "id": "override.disabled.rg-analytics",
        "version": "1.0.0",
        "target_rule": "postgresql-server.point-in-time-restore",
        "scope": "scope://org/account-000/rg-analytics",
        "mode": "disabled",
        "justification": "Non-critical analytics workloads accept a shorter retention window.",
        "requested_by": "00000000-0000-0000-0000-000000000001",
        "approver": "00000000-0000-0000-0000-000000000002",
        "provenance": {"created_at": "2026-07-03T00:00:00Z", "created_by": "assignment-operator"},
    }


def test_valid_disabled_override_loads() -> None:
    override = load_override_from_mapping(_valid_disabled())
    assert isinstance(override, Override)
    assert override.mode is OverrideMode.DISABLED
    assert override.scope.render() == "scope://org/account-000/rg-analytics"
    assert override.provenance is not None
    assert override.provenance.created_by == "assignment-operator"


def test_valid_parameter_relaxation_override_loads() -> None:
    raw = _valid_disabled()
    raw["mode"] = "parameter-relaxation"
    raw["parameter_overrides"] = {"min_retention_days": "3"}
    override = load_override_from_mapping(raw)
    assert override.parameter_overrides == {"min_retention_days": "3"}


def test_valid_severity_downgrade_override_loads() -> None:
    raw = _valid_disabled()
    raw["mode"] = "severity-downgrade"
    raw["severity_downgrade_to"] = "medium"
    override = load_override_from_mapping(raw)
    assert override.severity_downgrade_to is not None
    assert override.severity_downgrade_to.value == "medium"


def test_missing_required_field_rejected() -> None:
    raw = _valid_disabled()
    del raw["target_rule"]
    with pytest.raises(GovernanceLoadError):
        load_override_from_mapping(raw)


def test_unknown_field_rejected() -> None:
    raw = _valid_disabled()
    raw["unexpected"] = "nope"
    with pytest.raises(GovernanceLoadError):
        load_override_from_mapping(raw)


def test_bad_mode_enum_rejected() -> None:
    raw = _valid_disabled()
    raw["mode"] = "allow-everything"
    with pytest.raises(GovernanceLoadError):
        load_override_from_mapping(raw)


def test_organization_wide_scope_rejected_at_schema_and_domain_boundary() -> None:
    raw = _valid_disabled()
    raw["scope"] = "scope://org"
    with pytest.raises(GovernanceLoadError) as exc_info:
        load_override_from_mapping(raw)
    assert any("resource-group-equivalent" in issue.message for issue in exc_info.value.issues)


def test_parameter_relaxation_without_overrides_rejected_by_schema() -> None:
    raw = _valid_disabled()
    raw["mode"] = "parameter-relaxation"
    with pytest.raises(GovernanceLoadError):
        load_override_from_mapping(raw)


def test_severity_downgrade_without_target_rejected_by_schema() -> None:
    raw = _valid_disabled()
    raw["mode"] = "severity-downgrade"
    with pytest.raises(GovernanceLoadError):
        load_override_from_mapping(raw)


def test_self_override_rejected_at_domain_boundary() -> None:
    raw = _valid_disabled()
    raw["approver"] = raw["requested_by"]
    with pytest.raises(GovernanceLoadError) as exc_info:
        load_override_from_mapping(raw)
    assert any("self-override" in issue.message for issue in exc_info.value.issues)


def test_expires_at_optional_and_parsed() -> None:
    raw = _valid_disabled()
    raw["expires_at"] = "2027-01-01T00:00:00Z"
    override = load_override_from_mapping(raw)
    assert override.expires_at is not None
    assert override.expires_at.year == 2027


def test_no_expires_at_defaults_to_none() -> None:
    override = load_override_from_mapping(_valid_disabled())
    assert override.expires_at is None

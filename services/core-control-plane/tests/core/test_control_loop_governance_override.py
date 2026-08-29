"""apply_governance_override_to_rule - override precedence over an assignment."""

from __future__ import annotations

from fdai.core.control_loop._helpers import apply_governance_override_to_rule
from fdai.rule_catalog.schema.override import Override, OverrideMode
from fdai.rule_catalog.schema.scope import ScopeRef
from fdai.shared.contracts.models import Rule, Severity


def _rule(*, parameters: dict[str, object] | None = None, severity: str = "high") -> Rule:
    return Rule.model_validate(
        {
            "schema_version": "1.0.0",
            "id": "example.rule.x",
            "version": "1.0.0",
            "source": "custom",
            "severity": severity,
            "category": "config_drift",
            "resource_type": "compute.vm",
            "check_logic": {"kind": "rego", "reference": "policies/example/x.rego"},
            "remediation": {"template_ref": "remediations/example-x"},
            "remediates": "ops.scale-out",
            "parameters": parameters or {},
            "provenance": {
                "source_url": "https://example.com/x",
                "resolved_ref": "0000000000000000000000000000000000000000",
                "content_hash": "sha256:example",
                "license": "MIT",
                "redistribution": "embeddable",
                "retrieved_at": "2026-07-05T00:00:00Z",
            },
        }
    )


def _override(
    *,
    mode: OverrideMode,
    severity_downgrade_to: Severity | None = None,
    parameter_overrides: dict[str, str] | None = None,
) -> Override:
    return Override(
        id="override.x",
        target_rule="example.rule.x",
        scope=ScopeRef.parse("scope://org/account-000/rg-a"),
        mode=mode,
        justification="Non-critical analytics workloads accept a relaxed control here.",
        requested_by="requester",
        approver="approver",
        severity_downgrade_to=severity_downgrade_to,
        parameter_overrides=parameter_overrides or {},
    )


def test_no_override_and_no_assignment_parameters_returns_same_rule() -> None:
    rule = _rule()
    result = apply_governance_override_to_rule(rule, assignment_parameters={}, override=None)
    assert result is rule


def test_assignment_parameters_alone_merge_without_override() -> None:
    rule = _rule(parameters={"a": "1"})
    result = apply_governance_override_to_rule(
        rule, assignment_parameters={"b": "2"}, override=None
    )
    assert result.parameters == {"a": "1", "b": "2"}


def test_severity_downgrade_override_replaces_severity() -> None:
    rule = _rule(severity="critical")
    override = _override(
        mode=OverrideMode.SEVERITY_DOWNGRADE, severity_downgrade_to=Severity.MEDIUM
    )
    result = apply_governance_override_to_rule(rule, assignment_parameters={}, override=override)
    assert result.severity is Severity.MEDIUM


def test_parameter_relaxation_override_wins_over_assignment_value() -> None:
    rule = _rule(parameters={"min_retention_days": "14"})
    override = _override(
        mode=OverrideMode.PARAMETER_RELAXATION,
        parameter_overrides={"min_retention_days": "3"},
    )
    result = apply_governance_override_to_rule(
        rule,
        assignment_parameters={"min_retention_days": "7"},
        override=override,
    )
    assert result.parameters == {"min_retention_days": "3"}


def test_parameter_relaxation_override_adds_a_new_key() -> None:
    rule = _rule(parameters={})
    override = _override(
        mode=OverrideMode.PARAMETER_RELAXATION,
        parameter_overrides={"extra_key": "value"},
    )
    result = apply_governance_override_to_rule(rule, assignment_parameters={}, override=override)
    assert result.parameters == {"extra_key": "value"}


def test_disabled_override_does_not_change_parameters_or_severity() -> None:
    rule = _rule(parameters={"a": "1"}, severity="high")
    override = _override(mode=OverrideMode.DISABLED)
    result = apply_governance_override_to_rule(
        rule, assignment_parameters={"a": "1"}, override=override
    )
    assert result.parameters == {"a": "1"}
    assert result.severity is Severity.HIGH

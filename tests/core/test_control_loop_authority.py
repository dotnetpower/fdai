"""Shadow-parallel execution-authority helpers wired into the ControlLoop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fdai.core.control_loop import (
    _extract_environment,
    build_shadow_authority_audit,
    build_unified_risk_audit,
)
from fdai.core.risk_gate.gate import ActionPromotionRegistry, RiskGate
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.shared.contracts.models import (
    Action,
    ActionInterface,
    Event,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
    Rule,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TABLE_PATH = REPO_ROOT / "rule-catalog" / "risk-classification.yaml"


def test_extract_environment_prod_variants() -> None:
    assert _extract_environment({"tags": {"environment": "prod"}}) == "prod"
    assert _extract_environment({"tags": {"Environment": "production"}}) == "prod"
    assert _extract_environment({"environment": "PROD"}) == "prod"


def test_extract_environment_non_prod_variants() -> None:
    assert _extract_environment({"tags": {"fdai:env": "dev"}}) == "non-prod"
    assert _extract_environment({"tags": {"environment": "dev"}}) == "non-prod"
    assert _extract_environment({"environment": "staging"}) == "non-prod"
    assert _extract_environment({"tags": {"environment": "non-prod"}}) == "non-prod"


def test_extract_environment_prefers_canonical_namespaced_tag() -> None:
    resource = {"tags": {"fdai:env": "staging", "environment": "prod"}}
    assert _extract_environment(resource) == "non-prod"


def test_extract_environment_missing_or_unknown_fails_safe_to_prod() -> None:
    assert _extract_environment({}) == "prod"
    assert _extract_environment({"tags": {"environment": "weird"}}) == "prod"
    assert _extract_environment({"tags": "not-a-dict"}) == "prod"


def _destructive_action_type() -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name="remediate.remove-orphan-resource",
        version="1.0.0",
        operation=Operation.DELETE,
        interfaces=[ActionInterface.CONTROL_PLANE],
        rollback_contract=RollbackKind.SNAPSHOT_RESTORE,
        promotion_gate=PromotionGate(
            min_shadow_days=1, min_samples=1, min_accuracy=0.9, max_policy_escapes=0
        ),
    )


def test_build_shadow_authority_audit_shape(
    valid_event: dict[str, Any],
    valid_action: dict[str, Any],
    valid_rule: dict[str, Any],
    valid_ontology_action_type: dict[str, Any],
) -> None:
    entry = build_shadow_authority_audit(
        event=Event.model_validate(valid_event),
        action=Action.model_validate(valid_action),
        rule=Rule.model_validate(valid_rule),
        action_type=OntologyActionType.model_validate(valid_ontology_action_type),
        table=load_risk_table(TABLE_PATH),
    )
    assert entry["action_kind"] == "risk_gate.shadow_authority"
    assert entry["mode"] == "shadow"
    assert "decision" in entry
    assert "resolved_ceiling" in entry
    assert set(entry["resolved_ceiling"]["axes"]) == {
        "risk_table",
        "tier",
        "ceiling",
        "static_blast",
        "live_blast",
        "role",
        "env",
    }


def test_build_shadow_authority_audit_destructive_is_hil(
    valid_event: dict[str, Any],
    valid_action: dict[str, Any],
    valid_rule: dict[str, Any],
) -> None:
    entry = build_shadow_authority_audit(
        event=Event.model_validate(valid_event),
        action=Action.model_validate(valid_action),
        rule=Rule.model_validate(valid_rule),
        action_type=_destructive_action_type(),
        table=load_risk_table(TABLE_PATH),
    )
    assert entry["decision"] == "hil"
    assert entry["matched_rule_id"] == "hil-destructive"


def test_build_shadow_authority_audit_degraded_caps_to_shadow(
    valid_event: dict[str, Any],
    valid_action: dict[str, Any],
    valid_rule: dict[str, Any],
    valid_ontology_action_type: dict[str, Any],
) -> None:
    """B1 live path (control_loop threading): ``system_degraded=True`` reaches
    the authority audit and adds the ``system_health`` fail-safe axis, so a
    DEGRADED control plane never records an enforce-mode decision."""
    entry = build_shadow_authority_audit(
        event=Event.model_validate(valid_event),
        action=Action.model_validate(valid_action),
        rule=Rule.model_validate(valid_rule),
        action_type=OntologyActionType.model_validate(valid_ontology_action_type),
        table=load_risk_table(TABLE_PATH),
        system_degraded=True,
    )
    assert "system_health" in entry["resolved_ceiling"]["axes"]
    assert entry["decision"] in {"shadow", "deny"}


def test_build_shadow_authority_audit_kill_switch_caps_to_shadow(
    valid_event: dict[str, Any],
    valid_action: dict[str, Any],
    valid_rule: dict[str, Any],
    valid_ontology_action_type: dict[str, Any],
) -> None:
    """B2 live path (control_loop threading): ``kill_switch_engaged=True`` reaches
    the authority audit and adds the ``kill_switch`` axis, so the operator
    emergency stop never records an enforce-mode decision."""
    entry = build_shadow_authority_audit(
        event=Event.model_validate(valid_event),
        action=Action.model_validate(valid_action),
        rule=Rule.model_validate(valid_rule),
        action_type=OntologyActionType.model_validate(valid_ontology_action_type),
        table=load_risk_table(TABLE_PATH),
        kill_switch_engaged=True,
    )
    assert "kill_switch" in entry["resolved_ceiling"]["axes"]
    assert entry["decision"] in {"shadow", "deny"}


def test_build_unified_risk_audit_shape(
    valid_event: dict[str, Any],
    valid_action: dict[str, Any],
    valid_rule: dict[str, Any],
    valid_ontology_action_type: dict[str, Any],
) -> None:
    gate = RiskGate(registry=ActionPromotionRegistry())
    entry = build_unified_risk_audit(
        event=Event.model_validate(valid_event),
        action=Action.model_validate(valid_action),
        rule=Rule.model_validate(valid_rule),
        action_type=OntologyActionType.model_validate(valid_ontology_action_type),
        table=load_risk_table(TABLE_PATH),
        risk_gate=gate,
    )
    assert entry["action_kind"] == "risk_gate.unified"
    assert entry["mode"] == "shadow"
    assert entry["decision"] in {"auto", "hil", "shadow", "deny"}
    assert "winning_side" in entry
    assert "gate_outcome" in entry
    assert "authority" in entry


def test_build_unified_risk_audit_destructive_is_hil(
    valid_event: dict[str, Any],
    valid_action: dict[str, Any],
    valid_rule: dict[str, Any],
) -> None:
    gate = RiskGate(registry=ActionPromotionRegistry())
    entry = build_unified_risk_audit(
        event=Event.model_validate(valid_event),
        action=Action.model_validate(valid_action),
        rule=Rule.model_validate(valid_rule),
        action_type=_destructive_action_type(),
        table=load_risk_table(TABLE_PATH),
        risk_gate=gate,
    )
    # destructive -> authority hil; combined result is at least HIL.
    assert entry["decision"] in {"hil", "shadow", "deny"}


# ---------------------------------------------------------------------------
# Wave W2.5 - cost_override plumbing
# ---------------------------------------------------------------------------


def _rule_without_cost(base: dict[str, Any]) -> Rule:
    """Return a Rule whose remediation carries no static cost figure."""

    clone = dict(base)
    remediation = dict(clone["remediation"])
    remediation.pop("cost_impact_monthly_usd", None)
    clone["remediation"] = remediation
    return Rule.model_validate(clone)


def _non_prod_event(base: dict[str, Any]) -> Event:
    """Return an Event whose payload carries a non-prod environment tag.

    Axis A's ``hil-prod`` rule matches on ``environment == prod`` and
    fires before ``cost-threshold``; the cost-tests need a non-prod
    context so the cost rule can win the first-match.
    """

    clone = dict(base)
    clone["payload"] = {
        "resource": {
            "type": "compute.vm",
            "props": {
                "tags": {"environment": "dev"},
            },
        }
    }
    return Event.model_validate(clone)


def test_shadow_authority_audit_honours_cost_override(
    valid_event: dict[str, Any],
    valid_action: dict[str, Any],
    valid_rule: dict[str, Any],
    valid_ontology_action_type: dict[str, Any],
) -> None:
    """A high-cost override on a rule with no static cost surfaces on Axis A."""

    entry = build_shadow_authority_audit(
        event=_non_prod_event(valid_event),
        action=Action.model_validate(valid_action),
        rule=_rule_without_cost(valid_rule),
        action_type=OntologyActionType.model_validate(valid_ontology_action_type),
        table=load_risk_table(TABLE_PATH),
        cost_override=250.0,
    )
    # Cost-based table entry matches at >= $100 -> HIL. The upstream
    # rule id is ``hil-cost`` (see rule-catalog/risk-classification.yaml).
    assert entry["decision"] == "hil"
    assert entry["matched_rule_id"] == "hil-cost"


def test_shadow_authority_audit_cost_override_none_leaves_prior_decision(
    valid_event: dict[str, Any],
    valid_action: dict[str, Any],
    valid_rule: dict[str, Any],
    valid_ontology_action_type: dict[str, Any],
) -> None:
    """``cost_override=None`` reads the rule's static cost as before.

    Guarantees the new keyword is additive: existing callers that never
    supply the override see the pre-Wave-W2.5 behaviour on the same
    inputs.
    """

    with_override_none = build_shadow_authority_audit(
        event=_non_prod_event(valid_event),
        action=Action.model_validate(valid_action),
        rule=Rule.model_validate(valid_rule),
        action_type=OntologyActionType.model_validate(valid_ontology_action_type),
        table=load_risk_table(TABLE_PATH),
        cost_override=None,
    )
    without_kwarg = build_shadow_authority_audit(
        event=_non_prod_event(valid_event),
        action=Action.model_validate(valid_action),
        rule=Rule.model_validate(valid_rule),
        action_type=OntologyActionType.model_validate(valid_ontology_action_type),
        table=load_risk_table(TABLE_PATH),
    )
    # Same inputs, same decision - the override kwarg is inert when None.
    assert with_override_none["decision"] == without_kwarg["decision"]
    assert with_override_none["matched_rule_id"] == without_kwarg["matched_rule_id"]


def test_unified_risk_audit_honours_cost_override(
    valid_event: dict[str, Any],
    valid_action: dict[str, Any],
    valid_rule: dict[str, Any],
    valid_ontology_action_type: dict[str, Any],
) -> None:
    gate = RiskGate(registry=ActionPromotionRegistry())
    entry = build_unified_risk_audit(
        event=_non_prod_event(valid_event),
        action=Action.model_validate(valid_action),
        rule=_rule_without_cost(valid_rule),
        action_type=OntologyActionType.model_validate(valid_ontology_action_type),
        table=load_risk_table(TABLE_PATH),
        risk_gate=gate,
        cost_override=250.0,
    )
    # cost_override pushes Axis A to hil, which the combined decision
    # cannot raise above.
    assert entry["decision"] in {"hil", "shadow", "deny"}

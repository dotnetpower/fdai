"""Shadow-parallel execution-authority helpers wired into the ControlLoop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiopspilot.core.control_loop import (
    _extract_environment,
    build_shadow_authority_audit,
    build_unified_risk_audit,
)
from aiopspilot.core.risk_gate.gate import ActionPromotionRegistry, RiskGate
from aiopspilot.core.risk_gate.risk_table import load_risk_table
from aiopspilot.shared.contracts.models import (
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
    assert _extract_environment({"tags": {"environment": "dev"}}) == "non-prod"
    assert _extract_environment({"environment": "staging"}) == "non-prod"
    assert _extract_environment({"tags": {"environment": "non-prod"}}) == "non-prod"


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

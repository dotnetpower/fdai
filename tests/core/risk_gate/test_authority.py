"""Unified execution-authority pipeline (feature -> table -> ceiling)."""

from __future__ import annotations

from pathlib import Path

from fdai.core.risk_gate.authority import evaluate_execution_authority
from fdai.core.risk_gate.ceiling import AxisLevel
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.shared.contracts.models import (
    ActionBlastRadius,
    ActionInterface,
    Autonomy,
    BlastRadiusComputation,
    BlastRadiusScope,
    CeilingByTier,
    CeilingRole,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
    Tier,
    TierCeiling,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TABLE_PATH = REPO_ROOT / "rule-catalog" / "risk-classification.yaml"


def _table():  # type: ignore[no-untyped-def]
    return load_risk_table(TABLE_PATH)


def _low_risk_at(*, ceiling: CeilingByTier | None = None) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name="remediate.tag-add",
        version="1.0.0",
        operation=Operation.TAG,
        interfaces=[ActionInterface.CONTROL_PLANE, ActionInterface.IDEMPOTENT_BY_KEY],
        rollback_contract=RollbackKind.PR_REVERT,
        irreversible=False,
        promotion_gate=PromotionGate(
            min_shadow_days=1, min_samples=1, min_accuracy=0.9, max_policy_escapes=0
        ),
        blast_radius=ActionBlastRadius(
            computation=BlastRadiusComputation.STATIC_ENUM,
            static_bucket=BlastRadiusScope.RESOURCE,
        ),
        ceiling_by_tier=ceiling,
    )


def _destructive_at() -> OntologyActionType:
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
        blast_radius=ActionBlastRadius(
            computation=BlastRadiusComputation.STATIC_ENUM,
            static_bucket=BlastRadiusScope.RESOURCE,
        ),
    )


def test_low_risk_action_is_auto_end_to_end() -> None:
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=50.0,
    )
    assert d.decision == "auto"
    assert d.is_auto is True
    assert d.table_verdict.rule_id == "auto-low-risk"


def test_system_degraded_flips_auto_to_shadow() -> None:
    """The advertised fail-toward-safety wiring (csp-neutrality.md 4): the same
    low-risk action that is ``auto`` end-to-end when healthy is capped to
    ``shadow`` when the control plane is DEGRADED - a failing critical
    dependency MUST NOT drive an enforce-mode mutation."""
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=50.0,
        system_degraded=True,
    )
    assert d.decision == "shadow"
    assert d.is_auto is False
    assert d.resolved_ceiling.winning_axis == "system_health"


def test_kill_switch_flips_auto_to_shadow() -> None:
    """The operator emergency stop (security-and-identity.md): the same low-risk
    action that is ``auto`` end-to-end flips to ``shadow`` when the global
    kill-switch is engaged, halting all auto-execution."""
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=50.0,
        kill_switch_engaged=True,
    )
    assert d.decision == "shadow"
    assert d.is_auto is False
    assert d.resolved_ceiling.winning_axis == "kill_switch"


def test_destructive_action_is_hil() -> None:
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_destructive_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=10.0,
    )
    assert d.decision == "hil"
    assert d.requires_hil is True
    assert d.table_verdict.rule_id == "hil-destructive"


def test_policy_violation_denies_end_to_end() -> None:
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        policy_violation=True,
    )
    assert d.decision == "deny"
    assert d.is_denied is True
    assert d.resolved_ceiling.winning_axis == "risk_table"


def test_prod_downgrades_to_hil_via_table() -> None:
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="prod",
        cost_impact_monthly=50.0,
        allowlist_prod_auto=False,
    )
    assert d.decision == "hil"
    assert d.table_verdict.rule_id == "hil-prod"


def test_ceiling_lowers_a_table_auto_via_role_axis() -> None:
    # Table says auto (low risk) but the role ceiling requires Owner and the
    # caller is a Reader -> the role axis denies. Proves the six-axis ceiling
    # can only ever lower the table baseline, never the reverse.
    ceiling = CeilingByTier(
        t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_AUTO, min_role=CeilingRole.OWNER)
    )
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(ceiling=ceiling),
        table=_table(),
        principal_role=CeilingRole.READER,
        environment="non-prod",
        cost_impact_monthly=50.0,
    )
    assert d.table_verdict.rule_id == "auto-low-risk"  # table still said auto
    assert d.decision == "deny"  # but the ceiling lowered it
    assert d.resolved_ceiling.winning_axis == "role"


def test_t2_tier_forces_shadow() -> None:
    d = evaluate_execution_authority(
        tier=Tier.T2,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=CeilingRole.OWNER,
        environment="non-prod",
        cost_impact_monthly=50.0,
    )
    assert d.decision == "shadow"
    assert d.final_level is AxisLevel.SHADOW_ONLY


def test_audit_dict_shape() -> None:
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_destructive_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=10.0,
    )
    audit = d.as_audit_dict()
    assert audit["decision"] == "hil"
    assert audit["matched_rule_id"] == "hil-destructive"
    assert "resolved_ceiling" in audit
    assert set(audit["resolved_ceiling"]["axes"]) == {
        "risk_table",
        "tier",
        "ceiling",
        "static_blast",
        "live_blast",
        "role",
        "env",
    }


def test_environment_normalization_feeds_both_axes() -> None:
    # "non-prod" (table word) maps to the ceiling's "non_prod"; a prod word
    # reaches the table hil-prod rule. Both axes see one classification.
    d_prod = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="prod",
        cost_impact_monthly=50.0,
    )
    assert d_prod.feature_vector.environment == "prod"
    assert d_prod.decision == "hil"

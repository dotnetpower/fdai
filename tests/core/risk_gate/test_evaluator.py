"""Unified risk decision - gate.py x authority combination."""

from __future__ import annotations

from pathlib import Path

from aiopspilot.core.risk_gate.authority import evaluate_execution_authority
from aiopspilot.core.risk_gate.ceiling import AxisLevel
from aiopspilot.core.risk_gate.evaluator import combine, gate_level
from aiopspilot.core.risk_gate.gate import RiskDecision, RiskDecisionOutcome
from aiopspilot.core.risk_gate.risk_table import load_risk_table
from aiopspilot.shared.contracts.models import (
    ActionBlastRadius,
    ActionInterface,
    BlastRadiusComputation,
    BlastRadiusScope,
    Mode,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
    Tier,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TABLE_PATH = REPO_ROOT / "rule-catalog" / "risk-classification.yaml"


def _gate(
    outcome: RiskDecisionOutcome,
    *,
    mode: Mode = Mode.ENFORCE,
    reasons: tuple[str, ...] = (),
) -> RiskDecision:
    return RiskDecision(outcome=outcome, action_id="a1", effective_mode=mode, reasons=reasons)


def _low_risk_at() -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name="remediate.tag-add",
        version="1.0.0",
        operation=Operation.TAG,
        interfaces=[ActionInterface.CONTROL_PLANE],
        rollback_contract=RollbackKind.PR_REVERT,
        promotion_gate=PromotionGate(
            min_shadow_days=1, min_samples=1, min_accuracy=0.9, max_policy_escapes=0
        ),
        blast_radius=ActionBlastRadius(
            computation=BlastRadiusComputation.STATIC_ENUM,
            static_bucket=BlastRadiusScope.RESOURCE,
        ),
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
    )


def _authority(word: str):  # type: ignore[no-untyped-def]
    table = load_risk_table(TABLE_PATH)
    if word == "auto":
        return evaluate_execution_authority(
            tier=Tier.T0,
            action_type=_low_risk_at(),
            table=table,
            principal_role=None,
            environment="non-prod",
            cost_impact_monthly=50.0,
        )
    if word == "hil":
        return evaluate_execution_authority(
            tier=Tier.T0,
            action_type=_destructive_at(),
            table=table,
            principal_role=None,
            environment="non-prod",
            cost_impact_monthly=10.0,
        )
    if word == "deny":
        return evaluate_execution_authority(
            tier=Tier.T0,
            action_type=_low_risk_at(),
            table=table,
            principal_role=None,
            environment="non-prod",
            policy_violation=True,
        )
    if word == "shadow":
        return evaluate_execution_authority(
            tier=Tier.T2,
            action_type=_low_risk_at(),
            table=table,
            principal_role=None,
            environment="non-prod",
            cost_impact_monthly=50.0,
        )
    raise ValueError(word)


# --- gate_level normalization ------------------------------------------------


def test_gate_level_deny() -> None:
    assert gate_level(_gate(RiskDecisionOutcome.DENY)) is AxisLevel.DENY


def test_gate_level_hil() -> None:
    assert gate_level(_gate(RiskDecisionOutcome.HIL)) is AxisLevel.ENFORCE_HIL


def test_gate_level_abstain_hands_to_human() -> None:
    assert gate_level(_gate(RiskDecisionOutcome.ABSTAIN)) is AxisLevel.ENFORCE_HIL


def test_gate_level_auto_enforce() -> None:
    assert gate_level(_gate(RiskDecisionOutcome.AUTO, mode=Mode.ENFORCE)) is AxisLevel.ENFORCE_AUTO


def test_gate_level_auto_shadow_is_judge_only() -> None:
    assert gate_level(_gate(RiskDecisionOutcome.AUTO, mode=Mode.SHADOW)) is AxisLevel.SHADOW_ONLY


# --- combine -----------------------------------------------------------------


def test_combine_without_authority_uses_gate_alone() -> None:
    u = combine(_gate(RiskDecisionOutcome.HIL), None)
    assert u.decision == "hil"
    assert u.winning_side == "gate"
    assert u.authority is None
    assert u.requires_hil is True


def test_combine_gate_deny_beats_authority_auto() -> None:
    u = combine(_gate(RiskDecisionOutcome.AUTO, mode=Mode.ENFORCE), _authority("auto"))
    # gate auto/enforce = ENFORCE_AUTO; authority auto = ENFORCE_AUTO -> tie
    assert u.decision == "auto"
    u2 = combine(_gate(RiskDecisionOutcome.DENY), _authority("auto"))
    assert u2.decision == "deny"
    assert u2.winning_side == "gate"
    assert u2.is_denied is True


def test_combine_authority_hil_lowers_gate_auto() -> None:
    u = combine(_gate(RiskDecisionOutcome.AUTO, mode=Mode.ENFORCE), _authority("hil"))
    assert u.decision == "hil"
    assert u.winning_side == "authority"


def test_combine_tie_reports_both_sides() -> None:
    u = combine(_gate(RiskDecisionOutcome.AUTO, mode=Mode.ENFORCE), _authority("auto"))
    assert u.decision == "auto"
    assert u.winning_side == "gate+authority"
    assert u.is_auto is True


def test_combine_quorum_flows_from_authority() -> None:
    # An irreversible-style authority verdict does not apply here, so quorum is 1;
    # verify the quorum comes from the authority object, not a hard-coded gate value.
    u = combine(_gate(RiskDecisionOutcome.AUTO, mode=Mode.ENFORCE), _authority("hil"))
    assert u.quorum == u.authority.quorum  # type: ignore[union-attr]


def test_combine_shadow_authority_lowers_to_shadow() -> None:
    u = combine(_gate(RiskDecisionOutcome.AUTO, mode=Mode.ENFORCE), _authority("shadow"))
    assert u.decision == "shadow"


def test_as_audit_dict_without_authority() -> None:
    u = combine(_gate(RiskDecisionOutcome.HIL, reasons=("blast",)), None)
    d = u.as_audit_dict()
    assert d["decision"] == "hil"
    assert d["gate_outcome"] == "hil"
    assert d["gate_reasons"] == ["blast"]
    assert "authority" not in d


def test_as_audit_dict_with_authority() -> None:
    u = combine(_gate(RiskDecisionOutcome.AUTO, mode=Mode.ENFORCE), _authority("hil"))
    d = u.as_audit_dict()
    assert d["decision"] == "hil"
    assert "authority" in d
    assert "resolved_ceiling" in d["authority"]

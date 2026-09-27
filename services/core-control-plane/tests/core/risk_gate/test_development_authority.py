"""Risk admission for the full-authority development profile."""

from __future__ import annotations

from fdai.core.measurement.operational_promotion import action_type_digest
from fdai.core.risk_gate.authority import evaluate_execution_authority
from fdai.core.risk_gate.ceiling import AxisLevel
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.shared.contracts.models import (
    ActionBlastRadius,
    ActionInterface,
    BlastRadiusComputation,
    BlastRadiusScope,
    CeilingRole,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
    Tier,
)

from tests.contracts.test_development_authority import (
    NOW,
    _binding,
    _binding_request,
    _BindingSource,
    _confirmation,
    _profile,
    _verification,
)
from tests.core.risk_gate.test_authority import TABLE_PATH


def _action(
    *,
    operation: Operation = Operation.RESTART,
    irreversible: bool = False,
    scope: BlastRadiusScope = BlastRadiusScope.RESOURCE,
    live_probe_ref: str | None = None,
    requires_inventory: bool = False,
    graph_derived: bool = False,
) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name="ops.restart-service",
        version="1.0.0",
        operation=operation,
        interfaces=[
            ActionInterface.CONTROL_PLANE,
            *([ActionInterface.REQUIRES_INVENTORY_FRESH] if requires_inventory else []),
        ],
        rollback_contract=RollbackKind.SCRIPTED,
        irreversible=irreversible,
        promotion_gate=PromotionGate(
            min_shadow_days=1,
            min_samples=1,
            min_accuracy=0.9,
            max_policy_escapes=0,
        ),
        blast_radius=ActionBlastRadius(
            computation=(
                BlastRadiusComputation.GRAPH_DERIVED
                if graph_derived
                else BlastRadiusComputation.STATIC_ENUM
            ),
            static_bucket=None if graph_derived else scope,
            max_affected_resources=10 if graph_derived else None,
        ),
        live_probe_ref=live_probe_ref,
    )


def _evaluate(
    action: OntologyActionType,
    **overrides: object,
):  # type: ignore[no-untyped-def]
    digest = "sha256:" + action_type_digest(action)
    profile = _profile(resource_groups=(), action_type_digest=digest)
    binding = _binding(profile, action_type_digest=digest)
    confirmation = _confirmation(profile, binding)
    kwargs = {
        "tier": Tier.T0,
        "action_type": action,
        "table": load_risk_table(TABLE_PATH),
        "principal_role": CeilingRole.OWNER,
        "environment": "non-prod",
        "cost_impact_monthly": 10.0,
        "development_profile": profile,
        "development_confirmation": confirmation,
        "development_binding_source": _BindingSource(_verification(binding)),
        "development_binding_request": _binding_request(),
        "evaluated_at": NOW,
    }
    kwargs.update(overrides)
    return evaluate_execution_authority(**kwargs)  # type: ignore[arg-type]


def test_absent_profile_preserves_default_multi_operator_decision() -> None:
    action = _action(operation=Operation.DELETE, irreversible=True)
    baseline = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=action,
        table=load_risk_table(TABLE_PATH),
        principal_role=CeilingRole.OWNER,
        environment="non-prod",
        cost_impact_monthly=10.0,
    )

    assert baseline.final_level is AxisLevel.ENFORCE_HIL
    assert baseline.quorum == 2
    assert baseline.original_quorum == 2
    assert baseline.development_authority is None


def test_exact_confirmation_routes_auto_and_category_only_deny_to_hil() -> None:
    ordinary = _evaluate(_action())
    subscription = _evaluate(_action(scope=BlastRadiusScope.SUBSCRIPTION))

    assert ordinary.original_level is AxisLevel.ENFORCE_AUTO
    assert ordinary.final_level is AxisLevel.ENFORCE_HIL
    assert subscription.original_level is AxisLevel.DENY
    assert subscription.table_verdict.rule_id == "deny-subscription-blast"
    assert subscription.final_level is AxisLevel.ENFORCE_HIL


def test_irreversible_risk_and_original_quorum_remain_audited() -> None:
    decision = _evaluate(_action(operation=Operation.DELETE, irreversible=True))
    audit = decision.as_audit_dict()

    assert decision.original_level is AxisLevel.ENFORCE_HIL
    assert decision.original_quorum == 2
    assert decision.quorum == 1
    assert audit["original_quorum"] == 2
    assert audit["effective_quorum"] == 1
    assert audit["development_authority"]["development_only"] is True


def test_policy_graph_kill_switch_and_degradation_stay_closed() -> None:
    assert _evaluate(_action(), policy_violation=True).is_denied
    assert _evaluate(_action(), graph_stale=True).is_denied
    assert _evaluate(_action(), kill_switch_engaged=True).is_denied
    assert _evaluate(_action(), system_degraded=True).is_denied


def test_stale_required_probe_and_changed_binding_stay_closed() -> None:
    assert _evaluate(_action(live_probe_ref="probe.current")).is_denied
    assert _evaluate(_action(requires_inventory=True), graph_stale=None).is_denied
    assert _evaluate(_action(graph_derived=True), graph_affected=None).is_denied
    assert _evaluate(
        _action(scope=BlastRadiusScope.SUBSCRIPTION),
        tier=Tier.T2,
    ).is_denied

    action = _action()
    digest = "sha256:" + action_type_digest(action)
    profile = _profile(resource_groups=(), action_type_digest=digest)
    original = _binding(profile, action_type_digest=digest)
    changed = _binding(profile, target="resource:changed", action_type_digest=digest)
    decision = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=action,
        table=load_risk_table(TABLE_PATH),
        principal_role=CeilingRole.OWNER,
        environment="non-prod",
        cost_impact_monthly=10.0,
        development_profile=profile,
        development_confirmation=_confirmation(profile, original),
        development_binding_source=_BindingSource(_verification(changed)),
        development_binding_request=_binding_request(target="resource:changed"),
        evaluated_at=NOW,
    )

    assert decision.is_denied
    assert decision.development_authority is not None
    assert decision.development_authority.reason_code == "action_binding_mismatch"


def test_missing_source_and_stale_action_type_tuple_fail_closed() -> None:
    action = _action()
    current_digest = "sha256:" + action_type_digest(action)
    profile = _profile(resource_groups=(), action_type_digest=current_digest)
    current = _binding(profile, action_type_digest=current_digest)
    confirmation = _confirmation(profile, current)
    missing = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=action,
        table=load_risk_table(TABLE_PATH),
        principal_role=CeilingRole.OWNER,
        environment="non-prod",
        development_profile=profile,
        development_confirmation=confirmation,
        development_binding_request=_binding_request(),
        evaluated_at=NOW,
    )
    stale_binding = _binding(profile, action_type_digest="sha256:" + "f" * 64)
    stale = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=action,
        table=load_risk_table(TABLE_PATH),
        principal_role=CeilingRole.OWNER,
        environment="non-prod",
        development_profile=profile,
        development_confirmation=_confirmation(profile, stale_binding),
        development_binding_source=_BindingSource(_verification(stale_binding)),
        development_binding_request=_binding_request(),
        evaluated_at=NOW,
    )
    assert missing.is_denied
    assert missing.development_authority is not None
    assert missing.development_authority.reason_code == "binding_source_rejected"
    assert stale.is_denied
    assert stale.development_authority is not None
    assert stale.development_authority.reason_code == "current_action_type_mismatch"

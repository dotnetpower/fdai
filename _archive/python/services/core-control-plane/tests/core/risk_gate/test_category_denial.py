"""Only a denial caused solely by the ActionType category may park for the development Owner."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from fdai.core.risk_gate.authority import ExecutionAuthorityDecision, evaluate_execution_authority
from fdai.core.risk_gate.category_denial import (
    CategoryDenial,
    category_only_denial,
    development_category_denial,
)
from fdai.core.risk_gate.ceiling import AxisLevel
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision, combine
from fdai.core.risk_gate.gate import RiskDecision, RiskDecisionOutcome
from fdai.core.risk_gate.live_probe import LiveProbeObservation
from fdai.core.risk_gate.risk_table import RiskTable, load_risk_table, load_risk_table_from_mapping
from fdai.shared.contracts.development_authority import DevelopmentAuthorityDecision
from fdai.shared.contracts.models import (
    Autonomy,
    BlastRadiusScope,
    CeilingByTier,
    CeilingRole,
    Mode,
    OntologyActionType,
    Operation,
    TierCeiling,
)
from fdai.shared.contracts.models import Tier as ActionTier
from fdai.shared.providers.blast_probe import ProbeVerdict

from tests.core.risk_gate.test_authority import TABLE_PATH
from tests.core.risk_gate.test_development_authority import _action, _evaluate

SUBSCRIPTION = BlastRadiusScope.SUBSCRIPTION


def _authority(
    action_type: OntologyActionType,
    *,
    table: RiskTable | None = None,
    **overrides: Any,
) -> ExecutionAuthorityDecision:
    kwargs: dict[str, Any] = {
        "tier": ActionTier.T0,
        "action_type": action_type,
        "table": table or load_risk_table(TABLE_PATH),
        "principal_role": CeilingRole.OWNER,
        "environment": "non-prod",
        "cost_impact_monthly": 10.0,
    }
    kwargs.update(overrides)
    return evaluate_execution_authority(**kwargs)


def _category(
    action_type: OntologyActionType,
    *,
    table: RiskTable | None = None,
    **overrides: Any,
) -> CategoryDenial | None:
    current = table or load_risk_table(TABLE_PATH)
    decision = _authority(action_type, table=current, **overrides)
    return category_only_denial(
        table=current,
        feature=decision.feature_vector,
        ceiling=decision.resolved_ceiling,
    )


def _table(*rules: dict[str, Any]) -> RiskTable:
    return load_risk_table_from_mapping(
        {
            "version": "9.0.0",
            "owner_group": "aw-owners",
            "rules": [*rules, {"id": "default-hil", "default": "hil", "reason": "fail closed"}],
        }
    )


def test_subscription_blast_is_the_only_upstream_category_denial() -> None:
    denial = _category(_action(scope=SUBSCRIPTION))

    assert denial == CategoryDenial(
        rule_ids=("deny-subscription-blast",),
        axes=("risk_table", "static_blast"),
        residual_rule_id="default-hil",
        residual_decision="hil",
        residual_quorum=1,
    )
    irreversible = _category(
        _action(scope=SUBSCRIPTION, operation=Operation.DELETE, irreversible=True)
    )
    assert irreversible is not None
    # The Owner's approval stands in for the quorum the table would otherwise require.
    assert (irreversible.residual_rule_id, irreversible.residual_quorum) == ("hil-irreversible", 2)


def test_masked_or_mixed_denials_are_not_category_only() -> None:
    subscription = _action(scope=SUBSCRIPTION)
    mixed = _table(
        {
            "id": "deny-subscription-in-prod",
            "if": {"blast_radius": "subscription", "environment": "prod"},
            "decision": "deny",
            "reason": "mixed category and context",
        }
    )
    default_deny = load_risk_table_from_mapping(
        {
            "version": "9.0.0",
            "owner_group": "aw-owners",
            "rules": [
                {
                    "id": "deny-subscription-blast",
                    "if": {"blast_radius": "subscription"},
                    "decision": "deny",
                    "reason": "category",
                },
                {"id": "default-deny", "default": "deny", "reason": "fail closed"},
            ],
        }
    )

    assert _category(subscription, policy_violation=True) is None
    # First match returns the category rule, but a stale graph still denies behind it.
    assert _category(subscription, graph_stale=True) is None
    unconditional = _table({"id": "deny-all", "if": {}, "decision": "deny", "reason": "blanket"})
    assert _category(subscription, table=mixed, environment="prod") is None
    assert _category(subscription, table=default_deny) is None
    assert _category(subscription, table=unconditional) is None


def test_another_category_only_rule_counts() -> None:
    destructive = _table(
        {
            "id": "deny-destructive",
            "if": {"destructive": True},
            "decision": "deny",
            "reason": "category",
        }
    )

    denial = _category(_action(operation=Operation.DELETE), table=destructive)

    assert denial is not None
    assert (denial.rule_ids, denial.axes) == (("deny-destructive",), ("risk_table",))
    static_only = _category(_action(scope=SUBSCRIPTION), table=_table())
    assert static_only is not None
    assert (static_only.rule_ids, static_only.axes) == ((), ("static_blast",))


def test_every_other_denial_source_keeps_the_denial() -> None:
    subscription = _action(scope=SUBSCRIPTION)
    role_bound = subscription.model_copy(
        update={
            "ceiling_by_tier": CeilingByTier(
                t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_AUTO, min_role=CeilingRole.OWNER)
            )
        }
    )
    probed = subscription.model_copy(update={"live_probe_ref": "probe.current"})
    overloaded = LiveProbeObservation(
        probe_id="probe.current",
        verdict=ProbeVerdict.OVERLOADED,
        age_seconds=1.0,
        max_age_seconds=60.0,
    )

    assert _category(subscription, kill_switch_engaged=True) is None
    assert _category(subscription, system_degraded=True) is None
    assert _category(subscription, tier=ActionTier.T2) is None
    assert _category(role_bound, principal_role=CeilingRole.READER) is None
    assert _category(probed, live_probe_observation=overloaded) is None
    assert _category(_action()) is None


def _unified(
    authority: ExecutionAuthorityDecision,
    *,
    outcome: RiskDecisionOutcome = RiskDecisionOutcome.HIL,
    mode: Mode = Mode.ENFORCE,
    reasons: tuple[str, ...] = (),
) -> UnifiedRiskDecision:
    return combine(
        RiskDecision(
            outcome=outcome,
            action_id="00000000-0000-0000-0000-000000000010",
            effective_mode=mode,
            reasons=reasons,
        ),
        authority,
    )


def test_unified_denial_parks_only_when_the_gate_and_evidence_admit_it() -> None:
    table = load_risk_table(TABLE_PATH)
    subscription = _action(scope=SUBSCRIPTION)
    authority = _authority(subscription, table=table)

    def classify(unified: UnifiedRiskDecision, **overrides: Any) -> CategoryDenial | None:
        arguments: dict[str, Any] = {"table": table, "action_type": subscription}
        arguments.update(overrides)
        return development_category_denial(unified, **arguments)

    assert classify(_unified(authority)) is not None
    assert classify(_unified(authority, outcome=RiskDecisionOutcome.ABSTAIN)) is not None
    assert classify(_unified(authority, outcome=RiskDecisionOutcome.DENY)) is None
    assert classify(_unified(authority, outcome=RiskDecisionOutcome.AUTO, mode=Mode.SHADOW)) is None
    stale_graph = ("graph_fresh_precondition_stale:age=901>max=900",)
    assert classify(_unified(authority, reasons=stale_graph)) is None
    assert classify(replace(_unified(authority), evidence_conflict_clear=False)) is None
    assert classify(_unified(authority), table=_table()) is None
    assert classify(_unified(_authority(_action(), table=table))) is None
    with_confirmation = replace(
        authority,
        development_authority=DevelopmentAuthorityDecision(False, "binding_source_rejected"),
    )
    assert classify(_unified(with_confirmation)) is None


@pytest.mark.parametrize(
    ("action_type", "overrides", "expected"),
    [
        (
            _action(scope=SUBSCRIPTION).model_copy(update={"live_probe_ref": "probe.current"}),
            {},
            False,
        ),
        (
            _action(scope=SUBSCRIPTION).model_copy(update={"live_probe_ref": "probe.current"}),
            {
                "live_probe_observation": LiveProbeObservation(
                    probe_id="probe.current",
                    verdict=ProbeVerdict.QUIET,
                    age_seconds=1.0,
                    max_age_seconds=60.0,
                )
            },
            True,
        ),
        (_action(scope=SUBSCRIPTION, requires_inventory=True), {}, False),
        (_action(scope=SUBSCRIPTION, requires_inventory=True), {"graph_stale": False}, True),
    ],
)
def test_development_evidence_must_be_current(
    action_type: OntologyActionType,
    overrides: dict[str, Any],
    expected: bool,
) -> None:
    table = load_risk_table(TABLE_PATH)
    authority = _authority(action_type, table=table, **overrides)

    denial = development_category_denial(_unified(authority), table=table, action_type=action_type)

    assert (denial is not None) is expected


def test_confirmation_path_keeps_a_masked_evidence_denial_denied() -> None:
    confirmed = _evaluate(_action(scope=SUBSCRIPTION))
    masked = _evaluate(_action(scope=SUBSCRIPTION), graph_stale=True)

    assert confirmed.final_level is AxisLevel.ENFORCE_HIL
    assert masked.table_verdict.rule_id == "deny-subscription-blast"
    assert masked.is_denied

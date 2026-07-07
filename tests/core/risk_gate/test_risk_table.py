"""Risk-classification first-match table loader + evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aiopspilot.core.risk_gate.risk_table import (
    FeatureVector,
    RiskLevel,
    RiskRule,
    RiskTable,
    RiskTableError,
    _Equality,
    load_risk_table,
    load_risk_table_from_mapping,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TABLE_PATH = REPO_ROOT / "rule-catalog" / "risk-classification.yaml"


def _table() -> Any:
    return load_risk_table(TABLE_PATH)


def test_shipped_table_loads() -> None:
    table = _table()
    assert table.version == "1.0.0"
    ids = {r.rule_id for r in table.rules}
    assert "deny-policy-violation" in ids
    assert "auto-low-risk" in ids
    assert "default-hil" in ids


def test_policy_violation_denies() -> None:
    v = _table().evaluate(FeatureVector(policy_violation=True))
    assert v.decision is RiskLevel.DENY
    assert v.rule_id == "deny-policy-violation"


def test_subscription_blast_denies() -> None:
    v = _table().evaluate(FeatureVector(blast_radius="subscription"))
    assert v.decision is RiskLevel.DENY


def test_graph_stale_denies() -> None:
    v = _table().evaluate(FeatureVector(graph_stale=True))
    assert v.decision is RiskLevel.DENY


def test_irreversible_is_hil_with_quorum_two() -> None:
    v = _table().evaluate(FeatureVector(irreversible=True))
    assert v.decision is RiskLevel.HIL
    assert v.rule_id == "hil-irreversible"
    assert v.quorum == 2


def test_destructive_is_hil() -> None:
    v = _table().evaluate(FeatureVector(destructive=True))
    assert v.decision is RiskLevel.HIL
    assert v.quorum == 1


def test_prod_defaults_to_hil() -> None:
    v = _table().evaluate(FeatureVector(environment="prod", allowlist_prod_auto=False))
    assert v.decision is RiskLevel.HIL
    assert v.rule_id == "hil-prod"


def test_data_plane_is_hil() -> None:
    v = _table().evaluate(FeatureVector(data_plane_touched=True))
    assert v.decision is RiskLevel.HIL


def test_cost_at_threshold_is_hil() -> None:
    v = _table().evaluate(FeatureVector(cost_impact_monthly=100.0))
    assert v.decision is RiskLevel.HIL
    assert v.rule_id == "hil-cost"


def test_resource_group_blast_is_hil() -> None:
    v = _table().evaluate(FeatureVector(blast_radius="resource_group"))
    assert v.decision is RiskLevel.HIL


def test_low_verifier_confidence_is_hil() -> None:
    v = _table().evaluate(FeatureVector(verifier_confidence=0.5))
    assert v.decision is RiskLevel.HIL
    assert v.rule_id == "hil-low-confidence"


def test_low_risk_action_is_auto() -> None:
    v = _table().evaluate(
        FeatureVector(
            reversible=True,
            blast_radius="resource",
            cost_impact_monthly=50.0,
            data_plane_touched=False,
            irreversible=False,
            destructive=False,
            policy_violation=False,
            graph_stale=False,
            environment="non-prod",
            verifier_confidence=0.99,
        )
    )
    assert v.decision is RiskLevel.AUTO
    assert v.rule_id == "auto-low-risk"


def test_no_match_falls_through_to_default_hil() -> None:
    v = _table().evaluate(FeatureVector())
    assert v.decision is RiskLevel.HIL
    assert v.rule_id == "default-hil"


def test_deny_wins_over_hil_first_match() -> None:
    # Both policy_violation (deny) and destructive (hil) apply; deny comes first.
    v = _table().evaluate(FeatureVector(policy_violation=True, destructive=True))
    assert v.decision is RiskLevel.DENY


def test_cost_below_threshold_does_not_trigger_cost_hil() -> None:
    # 99 < 100 so the cost hil rule does not fire; with the other auto
    # conditions met the verdict is auto.
    v = _table().evaluate(
        FeatureVector(
            reversible=True,
            blast_radius="resource",
            cost_impact_monthly=99.0,
            data_plane_touched=False,
        )
    )
    assert v.decision is RiskLevel.AUTO


def test_unknown_dimension_is_rejected() -> None:
    raw = {
        "version": "1.0.0",
        "owner_group": "aw-owners",
        "rules": [
            {"id": "a", "if": {"bogus_key": True}, "decision": "hil", "reason": "x"},
            {"id": "d", "default": "hil", "reason": "z"},
        ],
    }
    with pytest.raises(RiskTableError) as info:
        load_risk_table_from_mapping(raw)
    assert any("unknown dimension" in i for i in info.value.issues)


def test_out_of_order_rules_are_rejected() -> None:
    raw = {
        "version": "1.0.0",
        "owner_group": "aw-owners",
        "rules": [
            {"id": "a", "if": {"reversible": True}, "decision": "auto", "reason": "x"},
            {"id": "b", "if": {"destructive": True}, "decision": "hil", "reason": "y"},
            {"id": "d", "default": "hil", "reason": "z"},
        ],
    }
    with pytest.raises(RiskTableError) as info:
        load_risk_table_from_mapping(raw)
    assert any("out of order" in i for i in info.value.issues)


def test_missing_default_is_rejected() -> None:
    raw = {
        "version": "1.0.0",
        "owner_group": "aw-owners",
        "rules": [
            {"id": "a", "if": {"destructive": True}, "decision": "hil", "reason": "y"},
        ],
    }
    with pytest.raises(RiskTableError) as info:
        load_risk_table_from_mapping(raw)
    assert any("default" in i for i in info.value.issues)


def test_multiple_defaults_are_rejected() -> None:
    raw = {
        "version": "1.0.0",
        "owner_group": "aw-owners",
        "rules": [
            {"id": "d1", "default": "hil", "reason": "z"},
            {"id": "d2", "default": "hil", "reason": "z"},
        ],
    }
    with pytest.raises(RiskTableError) as info:
        load_risk_table_from_mapping(raw)
    assert any("default" in i for i in info.value.issues)


def test_bad_decision_value_is_rejected() -> None:
    raw = {
        "version": "1.0.0",
        "owner_group": "aw-owners",
        "rules": [
            {"id": "a", "if": {"destructive": True}, "decision": "sometimes", "reason": "y"},
            {"id": "d", "default": "hil", "reason": "z"},
        ],
    }
    with pytest.raises(RiskTableError) as info:
        load_risk_table_from_mapping(raw)
    assert any("not one of" in i for i in info.value.issues)


def test_numeric_operators_all_supported() -> None:
    raw = {
        "version": "1.0.0",
        "owner_group": "aw-owners",
        "rules": [
            {"id": "le", "if": {"cost_impact_monthly": "<= 10"}, "decision": "deny", "reason": "x"},
            {"id": "gt", "if": {"cross_resource_impact": "> 5"}, "decision": "hil", "reason": "y"},
            {"id": "eq", "if": {"verifier_confidence": "== 1"}, "decision": "hil", "reason": "z"},
            {"id": "d", "default": "hil", "reason": "z"},
        ],
    }
    table = load_risk_table_from_mapping(raw)
    assert table.evaluate(FeatureVector(cost_impact_monthly=10.0)).rule_id == "le"
    assert table.evaluate(FeatureVector(cross_resource_impact=6)).rule_id == "gt"
    assert table.evaluate(FeatureVector(verifier_confidence=1.0)).rule_id == "eq"
    # A non-numeric actual never matches a numeric comparison.
    assert table.evaluate(FeatureVector()).rule_id == "d"


def test_if_all_must_be_list() -> None:
    raw = {
        "version": "1.0.0",
        "owner_group": "aw-owners",
        "rules": [
            {"id": "a", "if": {"all": {"reversible": True}}, "decision": "hil", "reason": "x"},
            {"id": "d", "default": "hil", "reason": "z"},
        ],
    }
    with pytest.raises(RiskTableError) as info:
        load_risk_table_from_mapping(raw)
    assert any("all` MUST be a list" in i for i in info.value.issues)


def test_if_must_be_mapping() -> None:
    raw = {
        "version": "1.0.0",
        "owner_group": "aw-owners",
        "rules": [
            {"id": "a", "if": "nope", "decision": "hil", "reason": "x"},
            {"id": "d", "default": "hil", "reason": "z"},
        ],
    }
    with pytest.raises(RiskTableError) as info:
        load_risk_table_from_mapping(raw)
    assert any("`if` MUST be a mapping" in i for i in info.value.issues)


def test_all_item_must_be_mapping() -> None:
    raw = {
        "version": "1.0.0",
        "owner_group": "aw-owners",
        "rules": [
            {"id": "a", "if": {"all": ["nope"]}, "decision": "hil", "reason": "x"},
            {"id": "d", "default": "hil", "reason": "z"},
        ],
    }
    with pytest.raises(RiskTableError) as info:
        load_risk_table_from_mapping(raw)
    assert any("all` item MUST be a mapping" in i for i in info.value.issues)


def test_top_level_not_mapping_rejected() -> None:
    with pytest.raises(RiskTableError):
        load_risk_table_from_mapping(["not", "a", "map"])


def test_rules_not_a_list_rejected() -> None:
    with pytest.raises(RiskTableError):
        load_risk_table_from_mapping({"version": "1.0.0", "owner_group": "aw-owners", "rules": "x"})


def test_rule_not_a_mapping_rejected() -> None:
    raw = {
        "version": "1.0.0",
        "owner_group": "aw-owners",
        "rules": ["notamap", {"id": "d", "default": "hil", "reason": "z"}],
    }
    with pytest.raises(RiskTableError) as info:
        load_risk_table_from_mapping(raw)
    assert any("MUST be a mapping" in i for i in info.value.issues)


def test_bad_quorum_rejected() -> None:
    raw = {
        "version": "1.0.0",
        "owner_group": "aw-owners",
        "rules": [
            {
                "id": "a",
                "if": {"irreversible": True},
                "decision": "hil",
                "quorum": 0,
                "reason": "x",
            },
            {"id": "d", "default": "hil", "reason": "z"},
        ],
    }
    with pytest.raises(RiskTableError) as info:
        load_risk_table_from_mapping(raw)
    assert any("quorum" in i for i in info.value.issues)


def test_missing_version_and_owner_rejected() -> None:
    raw = {"rules": [{"id": "d", "default": "hil", "reason": "z"}]}
    with pytest.raises(RiskTableError) as info:
        load_risk_table_from_mapping(raw)
    joined = " ".join(info.value.issues)
    assert "version" in joined and "owner_group" in joined


def test_evaluate_without_default_fails_closed() -> None:
    # A table built directly (bypassing the loader's default requirement)
    # with no matching rule fails closed to HIL.
    table = RiskTable(
        version="1.0.0",
        owner_group="aw-owners",
        rules=(
            RiskRule(
                rule_id="a",
                decision=RiskLevel.AUTO,
                reason="x",
                conditions=(_Equality(key="destructive", expected=True),),
            ),
        ),
    )
    v = table.evaluate(FeatureVector())
    assert v.decision is RiskLevel.HIL
    assert v.rule_id == "implicit-default"

"""A T1 reuse is credible only for the resource type its learned rule applies to."""

from __future__ import annotations

from types import SimpleNamespace

from fdai.core.control_loop._t1_resource_guard import (
    RESOURCE_TYPE_MISMATCH_REASON,
    guard_reuse_resource_type,
)
from fdai.core.tiers.t1_lightweight.tier import (
    LearnedAction,
    SimilarityMatch,
    T1Decision,
    T1Outcome,
)


def _reused() -> T1Decision:
    action = LearnedAction(
        signature="sig",
        rule_id="rule-1",
        action_type="remediate.tag-add",
        params={},
        incident_id="incident-1",
        success_rate=1.0,
    )
    return T1Decision(
        outcome=T1Outcome.REUSED,
        event_id="event-1",
        threshold=0.8,
        best_match=SimilarityMatch(action=action, score=0.86),
    )


def _rules(resource_type: str) -> dict[str, object]:
    return {"rule-1": SimpleNamespace(id="rule-1", resource_type=resource_type)}


def test_a_matching_resource_type_keeps_the_reuse() -> None:
    decision = _reused()
    guarded = guard_reuse_resource_type(
        decision,
        rules_by_id=_rules("resource-group"),
        resource_type="resource-group",  # type: ignore[arg-type]
    )
    assert guarded is decision


def test_a_cross_type_reuse_becomes_an_abstain_with_an_explicit_reason() -> None:
    guarded = guard_reuse_resource_type(
        _reused(),
        rules_by_id=_rules("resource-group"),  # type: ignore[arg-type]
        resource_type="authorization.role-assignment",
    )
    assert guarded.outcome is T1Outcome.ABSTAIN
    assert guarded.reason == RESOURCE_TYPE_MISMATCH_REASON
    assert guarded.reasons == (RESOURCE_TYPE_MISMATCH_REASON,)
    assert guarded.best_match is not None  # evidence of the near miss is retained


def test_an_unknown_rule_or_unresolved_resource_type_is_left_to_downstream_handling() -> None:
    for rules, resource_type in (({}, "resource-group"), (_rules("resource-group"), None)):
        decision = _reused()
        guarded = guard_reuse_resource_type(
            decision,
            rules_by_id=rules,
            resource_type=resource_type,  # type: ignore[arg-type]
        )
        assert guarded is decision


def test_a_non_reuse_decision_is_never_changed() -> None:
    decision = T1Decision(outcome=T1Outcome.ABSTAIN, event_id="event-1", threshold=0.8)
    assert guard_reuse_resource_type(decision, rules_by_id={}, resource_type=None) is decision

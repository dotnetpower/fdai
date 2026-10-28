"""Refuse a T1 reuse whose learned rule belongs to a different resource type.

T1 retrieval embeds only the event type, resource type, and property key names, so events of
different resource types can score above the similarity threshold. A reuse is credible only when
the learned rule applies to the resource type the trust router resolved for this event.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from fdai.core.tiers.t1_lightweight.tier import T1Decision, T1Outcome
from fdai.shared.contracts.models import Rule

RESOURCE_TYPE_MISMATCH_REASON = "t1_reuse_resource_type_mismatch"


def guard_reuse_resource_type(
    decision: T1Decision,
    *,
    rules_by_id: Mapping[str, Rule],
    resource_type: str | None,
) -> T1Decision:
    """Downgrade a reuse to an abstain when its known rule is for another resource type.

    An unknown rule is left to the existing downstream ``t1_reuse_rule_missing`` handling, so
    this guard changes only the case it can prove wrong.
    """
    if decision.outcome is not T1Outcome.REUSED or decision.best_match is None:
        return decision
    rule = rules_by_id.get(decision.best_match.action.rule_id)
    rule_type = getattr(rule, "resource_type", None)
    if rule_type is None or resource_type is None or rule_type == resource_type:
        return decision
    return replace(
        decision,
        outcome=T1Outcome.ABSTAIN,
        reason=RESOURCE_TYPE_MISMATCH_REASON,
        reasons=(RESOURCE_TYPE_MISMATCH_REASON,),
    )

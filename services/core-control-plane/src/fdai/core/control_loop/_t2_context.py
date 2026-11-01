"""Resolve the bounded T2 proposal context, or record why T2 is not consulted."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fdai.core.tiers.t2_reasoning import T2ProposalContext
from fdai.core.trust_router import RoutingDecision
from fdai.shared.contracts.models import Event, Rule
from fdai.shared.providers.stage_publisher import StageName, StagePhase


async def resolve_t2_context(
    emit_stage: Callable[..., Awaitable[None]],
    *,
    event: Event,
    decision: RoutingDecision,
    rules_by_id: Mapping[str, Rule],
    event_id: str,
    correlation_id: str,
) -> T2ProposalContext | None:
    """Return the T2 context, or emit a tier-less ``t2_skip_reason`` and return ``None``."""
    target_ref = event.resource_ref
    resource = event.payload.get("resource")
    if not target_ref and isinstance(resource, dict):
        candidate_ref = (
            resource.get("resource_id")
            or resource.get("resource_ref")
            or (resource.get("id") if rules_by_id else None)
        )
        if isinstance(candidate_ref, str) and candidate_ref:
            target_ref = candidate_ref
    allowed_rules = tuple(
        rule
        for rule_id in decision.candidate_rule_ids
        if (rule := rules_by_id.get(rule_id)) is not None
        and rule.resource_type == decision.resource_type
    )
    if not decision.candidate_rule_ids and decision.resource_type:
        allowed_rules = tuple(
            rule for rule in rules_by_id.values() if rule.resource_type == decision.resource_type
        )
    skip_reason: str | None = None
    if not target_ref or not decision.resource_type:
        skip_reason = "t2_missing_target_ref"
    elif not allowed_rules:
        skip_reason = "t2_no_candidate_rules"
    if skip_reason is not None or not target_ref or not decision.resource_type:
        # No "tier" key: a tier on a done verify stage would count as a T2 decision in Live.
        detail: dict[str, Any] = {"t2_skipped": True, "t2_skip_reason": skip_reason}
        await emit_stage(
            event_id=event_id,
            correlation_id=correlation_id,
            stage=StageName.VERIFY,
            phase=StagePhase.DONE,
            detail=detail,
        )
        return None
    return T2ProposalContext(
        event=event,
        target_resource_ref=target_ref,
        target_resource_type=decision.resource_type,
        allowed_rules=allowed_rules,
    )

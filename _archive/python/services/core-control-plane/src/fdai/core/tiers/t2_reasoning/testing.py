"""Deterministic T2 proposer used by local development and tests."""

from __future__ import annotations

from fdai.core.quality_gate.gate import QualityCandidate
from fdai.core.tiers.t2_reasoning.tier import T2ProposalContext, T2Proposer


class DeterministicT2Proposer(T2Proposer):
    """Propose the first catalog-authorized remediation, or abstain."""

    async def propose(self, *, context: T2ProposalContext) -> QualityCandidate | None:
        if not context.allowed_rules or not context.target_resource_ref:
            return None
        rule = context.allowed_rules[0]
        if rule.resource_type != context.target_resource_type:
            return None
        return QualityCandidate(
            action_type=rule.remediates,
            target_resource_ref=context.target_resource_ref,
            target_resource_type=context.target_resource_type,
            params={},
            cited_rule_ids=(rule.id,),
            confidence_signals={
                "catalog_authorization": 1.0,
                "target_type_match": 1.0,
            },
            reasoning_trace=f"Catalog rule {rule.id} authorizes {rule.remediates}.",
        )


class AbstainingT2Proposer(T2Proposer):
    """Fail-closed proposer for a composition with no proposal model."""

    async def propose(self, *, context: T2ProposalContext) -> QualityCandidate | None:
        del context
        return None


__all__ = ["AbstainingT2Proposer", "DeterministicT2Proposer"]

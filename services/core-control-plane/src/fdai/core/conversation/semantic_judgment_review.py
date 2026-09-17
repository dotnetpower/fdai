"""Validate independent semantic review without interpreting operator prose."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal


def validate_independent_bindings(primary: Any, reviewer: Any) -> None:
    """Reject a reviewer that reuses the primary model or configuration identity."""

    if (
        primary is not None
        and reviewer is not None
        and (
            primary.model is reviewer.model
            or primary.model_config_digest == reviewer.model_config_digest
        )
    ):
        raise ValueError("independent semantic review requires distinct model bindings")


def requires_independent_review(proposal: SemanticJudgmentProposal) -> bool:
    return proposal.primary_intent == "query.resource_state_inventory"


def proposals_match(
    primary: SemanticJudgmentProposal,
    reviewer: SemanticJudgmentProposal,
    *,
    confidence_threshold: float,
) -> bool:
    """Compare every meaning axis after both proposals pass ordinary grounding."""

    return (
        not reviewer.ambiguous
        and reviewer.confidence >= confidence_threshold
        and _signature(reviewer) == _signature(primary)
    )


def _signature(proposal: SemanticJudgmentProposal) -> tuple[object, ...]:
    def targets(values: Sequence[Any]) -> frozenset[tuple[object, ...]]:
        return frozenset(
            (
                target.kind,
                target.value,
                target.canonical_value,
                target.source_start,
                target.source_end,
            )
            for target in values
        )

    return (
        proposal.primary_intent,
        frozenset(proposal.secondary_intents),
        targets(proposal.targets),
        targets(proposal.forbidden_actions),
        frozenset(proposal.requested_facets),
        frozenset(proposal.alternatives),
        frozenset(proposal.unresolved_terms),
        proposal.document_evidence_mode,
        None
        if proposal.document_query is None
        else content_digest(proposal.document_query.model_dump(mode="json")),
        proposal.discourse_mode,
        proposal.action_posture,
        proposal.action_subject,
    )


__all__ = ["proposals_match", "requires_independent_review", "validate_independent_bindings"]

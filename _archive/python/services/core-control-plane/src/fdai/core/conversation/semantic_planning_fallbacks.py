"""Deterministic clarification and target-candidate fallbacks for semantic planning."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from fdai_service_contracts.ontology_query import SemanticOperation, SemanticProblemFrame

from fdai.rule_catalog.schema.inventory_query_language import InventoryQueryLanguageRegistry

from .conversation_preflight import operational_target_is_generic
from .semantic_current_state_planning import normalize_current_state_proposal
from .semantic_planning_cascade_judgment import (
    _judgment_non_resource_target_clarification,
    _non_resource_proposal_subjects,
)
from .semantic_planning_frame import build_semantic_frame
from .semantic_planning_models import SemanticFrameProposal, SemanticOutputShape
from .semantic_target_candidate_planning import (
    build_non_resource_target_clarification,
    build_resource_target_candidates_fallback,
    resource_target_candidates_apply_to_proposal,
)

_LOGGER = logging.getLogger(__name__)


def candidate_frame_fallback(
    *,
    tier: str,
    proposal: SemanticFrameProposal | None,
    semantic_judgment: Mapping[str, Any] | None,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
    inventory_query_language: InventoryQueryLanguageRegistry | None,
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Return a deterministic clarification or target-candidate frame when admissible."""
    if tier != "t1" or (
        proposal is not None and proposal.operation is SemanticOperation.ACTION_DRAFT
    ):
        return None
    judgment_clarification = _judgment_non_resource_target_clarification(
        proposal,
        semantic_judgment=semantic_judgment,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
        inventory_query_language=inventory_query_language,
    )
    if judgment_clarification is not None:
        _LOGGER.info(
            "semantic_planning_candidate_recovered",
            extra={"stage": "frame", "recovery": "non_resource_target_clarification"},
        )
        return judgment_clarification
    current_state_clarification = current_state_clarification_fallback(
        semantic_judgment=semantic_judgment,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
        confidence=proposal.confidence if proposal is not None else 0.0,
    )
    if current_state_clarification is not None:
        _LOGGER.info(
            "semantic_planning_candidate_recovered",
            extra={"stage": "frame", "recovery": "current_state_clarification"},
        )
        return current_state_clarification
    if proposal is not None:
        _LOGGER.info(
            "semantic_planning_candidate_recovery_unavailable",
            extra={
                "operation": proposal.operation.value,
                "output_shape": proposal.output_shape.value,
                "proposal_object_subjects": ",".join(
                    _non_resource_proposal_subjects(proposal, descriptors=descriptors)
                ),
            },
        )
    if proposal is None:
        return None
    clarification = build_non_resource_target_clarification(
        proposal,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
        inventory_query_language=inventory_query_language,
    )
    if clarification is not None:
        _LOGGER.info(
            "semantic_planning_candidate_recovered",
            extra={"stage": "frame", "recovery": "non_resource_target_clarification"},
        )
        return clarification
    if proposal.output_shape is SemanticOutputShape.RESOURCE_TARGET_CANDIDATES:
        return None
    if not resource_target_candidates_apply_to_proposal(
        proposal,
        utterance=utterance,
        descriptors=descriptors,
        inventory_query_language=inventory_query_language,
    ):
        return None
    fallback = build_resource_target_candidates_fallback(
        utterance=utterance,
        context=context,
        descriptors=descriptors,
        confidence=proposal.confidence,
        inventory_query_language=inventory_query_language,
        temporal_scope=(
            proposal.temporal_scope or judgment_candidate_temporal_scope(semantic_judgment)
        ),
    )
    if fallback is not None:
        _LOGGER.info(
            "semantic_planning_candidate_recovered",
            extra={"stage": "frame", "recovery": "resource_target_candidates"},
        )
    return fallback


def judgment_candidate_temporal_scope(
    semantic_judgment: Mapping[str, Any] | None,
) -> dict[str, str] | None:
    if semantic_judgment is None:
        return None
    return (
        {"kind": "current"}
        if semantic_judgment.get("primary_intent") == "query.resource_current_state"
        else None
    )


def current_state_clarification_fallback(
    *,
    semantic_judgment: Mapping[str, Any] | None,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
    confidence: float,
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Build a single-target current-state clarification without narrowing collections."""
    requested_facets = (
        semantic_judgment.get("requested_facets", ()) if semantic_judgment is not None else ()
    )
    targets = semantic_judgment.get("targets", ()) if semantic_judgment is not None else ()
    state_target_count = (
        sum(
            isinstance(target, Mapping) and target.get("kind") == "resource_state"
            for target in targets
        )
        if isinstance(targets, Sequence) and not isinstance(targets, (str, bytes))
        else 0
    )
    if (
        semantic_judgment is None
        or semantic_judgment.get("primary_intent") != "query.resource_current_state"
        or not isinstance(requested_facets, Sequence)
        or isinstance(requested_facets, (str, bytes))
        or "cause" in requested_facets
        or bool({"resource_state_inventory", "state_grouping"}.intersection(requested_facets))
        or state_target_count > 1
    ):
        return None
    exact_targets = (
        tuple(
            target
            for target in targets
            if isinstance(target, Mapping)
            and target.get("kind") in {"resource", "resource_id"}
            and isinstance(target.get("value"), str)
            and not _generic_resource_target(target["value"], descriptors)
            and isinstance(target.get("source_start"), int)
            and isinstance(target.get("source_end"), int)
            and utterance[target["source_start"] : target["source_end"]] == target["value"]
        )
        if isinstance(targets, Sequence) and not isinstance(targets, (str, bytes))
        else ()
    )
    subject_constraints: tuple[str, ...]
    if len(exact_targets) == 1:
        target = exact_targets[0]
        if (
            target.get("kind") == "resource_id"
            or target.get("canonical_value") == "Resource.id"
            or target["value"].casefold().startswith("/subscriptions/")
        ):
            subject_constraints = ("Resource", f"Resource.id={target['value']}")
        else:
            subject_constraints = ("Resource", f"Resource.name={target['value']}")
    else:
        subject_constraints = ("Resource",)
    normalization_utterance = (
        ("상태" if any("가" <= character <= "힣" for character in utterance) else "state")
        if len(exact_targets) > 1
        else utterance
    )
    proposal = normalize_current_state_proposal(
        SemanticFrameProposal(
            operation=SemanticOperation.SELECT,
            subject_constraints=subject_constraints,
            measure_concepts=(),
            temporal_scope={},
            output_shape=SemanticOutputShape.TARGET_CURRENT_STATE,
            evidence_requirements=("authoritative_inventory",),
            unresolved_terms=(),
            clarification_requirements=(),
            clarification=None,
            investigation=None,
            confidence=confidence,
        ),
        utterance=normalization_utterance,
        descriptors=descriptors,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def _generic_resource_target(
    value: str,
    descriptors: tuple[dict[str, Any], ...],
) -> bool:
    if operational_target_is_generic(value):
        return True
    normalized = " ".join(value.casefold().split())
    for descriptor in descriptors:
        if descriptor.get("kind") != "object" or descriptor.get("name") != "Resource":
            continue
        properties = descriptor.get("properties")
        if not isinstance(properties, Mapping):
            continue
        declaration = properties.get("type")
        if not isinstance(declaration, Mapping):
            continue
        candidates: list[str] = []
        declared_values = declaration.get("values", ())
        if isinstance(declared_values, Sequence) and not isinstance(declared_values, (str, bytes)):
            candidates.extend(value for value in declared_values if isinstance(value, str))
        groups = declaration.get("value_groups", ())
        if isinstance(groups, Sequence) and not isinstance(groups, (str, bytes)):
            for group in groups:
                if not isinstance(group, Mapping):
                    continue
                for key in ("terms", "values"):
                    values = group.get(key, ())
                    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                        candidates.extend(value for value in values if isinstance(value, str))
        if any(normalized == " ".join(candidate.casefold().split()) for candidate in candidates):
            return True
    return False


__all__ = [
    "candidate_frame_fallback",
    "current_state_clarification_fallback",
    "judgment_candidate_temporal_scope",
]

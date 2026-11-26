"""Resolve judgment-grounded non-Resource semantic targets."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.ontology_query import SemanticOperation, SemanticProblemFrame

from fdai.rule_catalog.schema.inventory_query_language import InventoryQueryLanguageRegistry

from .semantic_current_state_planning import exact_target_from_constraints
from .semantic_planning_frame_core import build_semantic_frame
from .semantic_planning_models import SemanticFrameProposal, SemanticOutputShape
from .semantic_target_candidate_planning import (
    build_non_resource_target_clarification,
    is_exact_schema_relationship,
)


def _judgment_non_resource_target_clarification(
    proposal: SemanticFrameProposal | None,
    *,
    semantic_judgment: Mapping[str, Any] | None,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
    inventory_query_language: InventoryQueryLanguageRegistry | None,
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    if proposal is not None and is_exact_schema_relationship(
        proposal,
        utterance=utterance,
        descriptors=descriptors,
    ):
        return None
    if (
        proposal is not None
        and exact_target_from_constraints(
            proposal.subject_constraints,
            utterance=utterance,
            descriptors=descriptors,
        )
        is not None
    ):
        return None
    judgment_subjects = _judgment_object_subjects(
        semantic_judgment,
        descriptors=descriptors,
    )
    judgment_link_subjects = _judgment_link_subjects(
        semantic_judgment,
        descriptors=descriptors,
        required_subjects=judgment_subjects,
    )
    unique_link_subjects = _unique_reviewed_link_subjects(
        judgment_subjects,
        descriptors=descriptors,
    )
    stated_subjects = _stated_object_subjects(utterance, descriptors=descriptors)
    proposal_subjects = (
        _non_resource_proposal_subjects(proposal, descriptors=descriptors)
        if proposal is not None
        else ()
    )
    selected_subjects = tuple(
        subject
        for subject in _descriptor_object_types(descriptors)
        if subject
        in {
            *judgment_subjects,
            *judgment_link_subjects,
            *unique_link_subjects,
            *stated_subjects,
            *proposal_subjects,
        }
    )
    if not selected_subjects:
        return None
    if proposal is None:
        confidence = semantic_judgment.get("confidence") if semantic_judgment is not None else 0.0
        proposal = SemanticFrameProposal(
            operation=SemanticOperation.SELECT,
            subject_constraints=selected_subjects,
            measure_concepts=(),
            temporal_scope={},
            output_shape=SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
            evidence_requirements=(),
            unresolved_terms=(),
            clarification_requirements=(),
            clarification=None,
            investigation=None,
            confidence=confidence if isinstance(confidence, float) else 0.0,
        )
    clarification = build_non_resource_target_clarification(
        proposal.model_copy(update={"subject_constraints": selected_subjects}),
        utterance=utterance,
        context=context,
        descriptors=descriptors,
        inventory_query_language=inventory_query_language,
    )
    if clarification is not None:
        return clarification
    if len(selected_subjects) < 2:
        return None
    recovered = proposal.model_copy(
        update={
            "operation": SemanticOperation.SELECT,
            "subject_constraints": selected_subjects,
            "measure_concepts": (),
            "temporal_scope": {"kind": "current"},
            "output_shape": SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
            "evidence_requirements": (),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
        }
    )
    return recovered, build_semantic_frame(recovered, utterance=utterance, context=context)


def _non_resource_proposal_subjects(
    proposal: SemanticFrameProposal,
    *,
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    declared = set(_descriptor_object_types(descriptors))
    return tuple(subject for subject in proposal.subject_constraints if subject in declared)


def _descriptor_object_types(
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    return tuple(
        name
        for descriptor in descriptors
        if descriptor.get("kind") == "object"
        if isinstance((name := descriptor.get("name")), str)
        if name != "Resource"
    )


def _stated_object_subjects(
    utterance: str,
    *,
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    normalized_utterance = " ".join(re.findall(r"[a-z0-9]+", utterance.casefold()))
    selected = set()
    for object_type in _descriptor_object_types(descriptors):
        label = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", object_type).casefold()
        if re.search(rf"(?:^| ){re.escape(label)}(?: |$)", normalized_utterance):
            selected.add(object_type)
    return tuple(
        object_type
        for object_type in _descriptor_object_types(descriptors)
        if object_type in selected
    )


def _judgment_object_subjects(
    judgment: Mapping[str, Any] | None,
    *,
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    if judgment is None:
        return ()
    object_types = _descriptor_object_types(descriptors)
    object_types_by_source_value = {
        re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).casefold(): name for name in object_types
    }
    targets = judgment.get("targets")
    if not isinstance(targets, list):
        return ()
    selected: set[str] = set()
    for target in targets:
        if not isinstance(target, Mapping):
            continue
        canonical_value = target.get("canonical_value")
        source_value = target.get("value")
        if isinstance(canonical_value, str) and canonical_value in object_types:
            selected.add(canonical_value)
        elif target.get("kind") == "object_type" and isinstance(source_value, str):
            matched = object_types_by_source_value.get(" ".join(source_value.casefold().split()))
            if matched is not None:
                selected.add(matched)
    return tuple(name for name in object_types if name in selected)


def _judgment_link_subjects(
    judgment: Mapping[str, Any] | None,
    *,
    descriptors: tuple[dict[str, Any], ...],
    required_subjects: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if judgment is None:
        return ()
    primary_intent = judgment.get("primary_intent")
    if not isinstance(primary_intent, str) or not primary_intent.startswith("query."):
        return ()
    link_name = primary_intent.removeprefix("query.")
    for descriptor in descriptors:
        if descriptor.get("kind") != "link" or descriptor.get("name") != link_name:
            continue
        endpoints = (descriptor.get("from_type"), descriptor.get("to_type"))
        if all(isinstance(endpoint, str) for endpoint in endpoints) and (
            not required_subjects or set(required_subjects).intersection(endpoints)
        ):
            object_types = _descriptor_object_types(descriptors)
            return tuple(endpoint for endpoint in object_types if endpoint in endpoints)
    return ()


def _unique_reviewed_link_subjects(
    subjects: tuple[str, ...],
    *,
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    if len(subjects) != 1:
        return ()
    subject = subjects[0]
    candidates: list[tuple[str, str]] = []
    for descriptor in descriptors:
        if descriptor.get("kind") != "link":
            continue
        source_type = descriptor.get("from_type")
        target_type = descriptor.get("to_type")
        if (
            isinstance(source_type, str)
            and isinstance(target_type, str)
            and subject in {source_type, target_type}
            and source_type != "Resource"
            and target_type != "Resource"
        ):
            candidates.append((source_type, target_type))
    if len(candidates) != 1:
        return ()
    endpoints = candidates[0]
    return tuple(
        object_type
        for object_type in _descriptor_object_types(descriptors)
        if object_type in endpoints
    )


__all__ = [
    "_descriptor_object_types",
    "_judgment_link_subjects",
    "_judgment_non_resource_target_clarification",
    "_judgment_object_subjects",
    "_non_resource_proposal_subjects",
    "_stated_object_subjects",
    "_unique_reviewed_link_subjects",
]

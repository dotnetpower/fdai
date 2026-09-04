"""Normalize topology frames that still require exact Resource identities."""

from __future__ import annotations

import re
from typing import Any

from fdai_service_contracts.ontology_query import (
    SemanticOperation,
    SemanticProblemFrame,
)

from .semantic_planning_frame_core import build_semantic_frame
from .semantic_planning_frame_facets import _facets_describe_network_path
from .semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from .semantic_planning_value_filters import stated_value_filters
from .semantic_target_identity import exact_target_from_constraints


def normalize_network_path_clarification(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Preserve a model-proposed network path until exact endpoint identities are supplied."""

    if frozenset(frame.subject_constraints) in {
        frozenset({"ActionType", "ResourceType", "Rule", "SignalType"}),
        frozenset({"Agent", "BusinessService", "Resource", "Workload"}),
    }:
        return proposal, frame
    facets = {facet.replace("-", "_") for facet in proposal.measure_concepts}
    targetless_topology = frame.output_shape == SemanticOutputShape.TOPOLOGY_GRAPH and (
        bool(stated_value_filters(utterance, descriptors).get(("Resource", "type")))
        or ("Resource" in frame.subject_constraints and len(frame.subject_constraints) > 1)
    )
    declared_object_types = {
        name
        for descriptor in descriptors
        if descriptor.get("kind") == "object"
        if isinstance((name := descriptor.get("name")), str)
    }
    frame_object_types = declared_object_types.intersection(frame.subject_constraints)
    multi_object_topology = (
        frame.output_shape
        in {
            SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
            SemanticOutputShape.TOPOLOGY_GRAPH,
        }
        and "Resource" in frame_object_types
        and len(frame_object_types) > 1
    )
    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape
        not in {
            SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
            SemanticOutputShape.TOPOLOGY_GRAPH,
        }
        or not (
            targetless_topology or multi_object_topology or _facets_describe_network_path(facets)
        )
        or exact_target_from_constraints(
            frame.subject_constraints,
            utterance=utterance,
            descriptors=descriptors,
        )
        is not None
    ):
        return proposal, frame
    korean = re.search(r"[가-힣]", utterance) is not None
    resolved_facets = {
        *facets,
        *(("topology_graph",) if targetless_topology or multi_object_topology else ()),
    }
    resolved = proposal.model_copy(
        update={
            "operation": SemanticOperation.SELECT,
            "subject_constraints": ("Resource",),
            "measure_concepts": tuple(sorted(resolved_facets)),
            "temporal_scope": {"kind": "current"},
            "output_shape": SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
            "evidence_requirements": (),
            "unresolved_terms": ("Resource identity",),
            "clarification_requirements": (ClarificationRequirement.SUBJECT,),
            "clarification": (
                "추적할 정확한 시작 및 대상 Resource 이름 또는 ID를 알려주세요?"
                if korean
                else "Provide the exact source and target Resource names or IDs to trace?"
            ),
            "investigation": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)

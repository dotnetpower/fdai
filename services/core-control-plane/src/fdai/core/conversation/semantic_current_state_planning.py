"""Compile exact-target current-state reads from verified request facts."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
    canonical_json,
    content_digest,
)

from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    OntologyQueryPlanVerifier,
    QueryManifest,
)
from fdai.core.ontology_platform.resource_current_state_queries import (
    RESOURCE_CURRENT_STATE_FUNCTION_NAME,
)

from .semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from .semantic_target_identity import exact_target_from_constraints

_LOGGER = logging.getLogger(__name__)
_GENERIC_RESOURCE_OUTPUTS = frozenset(
    {
        SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
        SemanticOutputShape.RESOURCE_LIST,
    }
)
_KOREAN_TARGET_CLARIFICATION = (
    "요청한 상태를 사용 가능한 근거로 검증하고 확인할 수 없는 항목을 한계로 "
    "구분할 수 있도록, 확인할 리소스의 정확한 이름 또는 리소스 ID를 알려주시겠어요?"
)
_ENGLISH_TARGET_CLARIFICATION = (
    "What is the exact resource name or resource ID to use when verifying the requested "
    "state and separating any unverified fields as limitations?"
)


def normalize_current_state_proposal(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
) -> SemanticFrameProposal:
    """Restore the exact-target family from capability-declared frame measures."""

    normalized = proposal
    if proposal.output_shape is not SemanticOutputShape.TARGET_CURRENT_STATE:
        if (
            proposal.operation is not SemanticOperation.SELECT
            or proposal.output_shape not in _GENERIC_RESOURCE_OUTPUTS
            or not _current_state_measures(descriptors).intersection(proposal.measure_concepts)
        ):
            return proposal
        normalized = proposal.model_copy(
            update={"output_shape": SemanticOutputShape.TARGET_CURRENT_STATE}
        )
    if normalized.operation is not SemanticOperation.SELECT:
        return proposal
    if normalized.unresolved_terms:
        return normalized
    if (
        exact_target_from_constraints(
            normalized.subject_constraints,
            utterance=utterance,
            descriptors=descriptors,
        )
        is not None
    ):
        return normalized
    clarification = (
        _KOREAN_TARGET_CLARIFICATION
        if any("가" <= character <= "힣" for character in utterance)
        else _ENGLISH_TARGET_CLARIFICATION
    )
    return SemanticFrameProposal.model_validate(
        {
            **normalized.model_dump(mode="python"),
            "unresolved_terms": ("resource_identity",),
            "clarification_requirements": (ClarificationRequirement.RESOURCE_IDENTITY,),
            "clarification": clarification,
        }
    )


def compile_target_current_state_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Build one exact Resource current-state projection when fully grounded."""

    if (
        frame.output_shape != SemanticOutputShape.TARGET_CURRENT_STATE
        or not _has_current_state_function(manifest.descriptors)
    ):
        return None
    target_name = exact_target_from_constraints(
        frame.subject_constraints,
        utterance=utterance,
        descriptors=manifest.descriptors,
    )
    identity_property = _resource_identity_property(manifest.descriptors)
    if target_name is None or identity_property is None:
        return None
    as_of = evaluation_time.astimezone(UTC)
    target_definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(
            ObjectPredicate(
                property=identity_property,
                operator=ObjectPredicateOperator.EQUALS,
                equals=target_name,
            ),
        ),
        as_of=as_of,
        purpose=purpose,
        limit=2,
    )
    nodes = (
        OntologyQueryNode(
            node_id="current-state-target",
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json(
                {"definition": target_definition.model_dump(mode="json")}
            ),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="resource-current-state",
            kind=QueryNodeKind.FUNCTION,
            depends_on=("current-state-target",),
            arguments_json=canonical_json(
                {
                    "function_name": RESOURCE_CURRENT_STATE_FUNCTION_NAME,
                    "arguments": {},
                    "dependency_arguments": {"current-state-target": "query_result"},
                }
            ),
            output_kind="query.table",
        ),
    )
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": frame.frame_digest,
        "purpose": purpose,
        "caller_role": manifest.principal_role.value,
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "output_node_ids": ["resource-current-state"],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=("resource-current-state",),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _resource_identity_property(descriptors: tuple[dict[str, Any], ...]) -> str | None:
    selected = tuple(
        descriptor
        for descriptor in descriptors
        if descriptor.get("kind") == "object" and descriptor.get("name") == "Resource"
    )
    if len(selected) != 1 or not isinstance(selected[0].get("properties"), Mapping):
        return None
    properties = selected[0]["properties"]
    return next((name for name in ("name", "display_name", "id") if name in properties), None)


def _has_current_state_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == RESOURCE_CURRENT_STATE_FUNCTION_NAME
        for descriptor in descriptors
    )


def _current_state_measures(
    descriptors: tuple[dict[str, Any], ...],
) -> frozenset[str]:
    selected = tuple(
        descriptor
        for descriptor in descriptors
        if descriptor.get("kind") == "function"
        and descriptor.get("name") == RESOURCE_CURRENT_STATE_FUNCTION_NAME
    )
    if len(selected) != 1:
        return frozenset()
    output_schema = selected[0].get("output_schema")
    if not isinstance(output_schema, Mapping):
        return frozenset()
    measures = output_schema.get("x-fdai-measure-concepts")
    if not isinstance(measures, list):
        return frozenset()
    return frozenset(measure for measure in measures if isinstance(measure, str))


__all__ = [
    "compile_target_current_state_plan",
    "exact_target_from_constraints",
    "normalize_current_state_proposal",
]

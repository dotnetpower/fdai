"""Compile bounded Resource operational-state transition history."""

from __future__ import annotations

from datetime import datetime, timedelta
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
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest
from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_OBSERVED_CONCEPT,
    RESOURCE_STATE_QUERY_CONCEPTS,
)
from fdai.core.ontology_platform.state_transitions import (
    RESOURCE_AVAILABILITY_STATE_TRANSITION_VALUES,
    RESOURCE_STATE_TRANSITION_TYPE,
    RESOURCE_STATE_TRANSITION_TYPES,
    RESOURCE_STATE_TRANSITION_VALUES,
    RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME,
)

from .semantic_activity_planning import activity_lookback_seconds
from .semantic_planning_frame_core import build_semantic_frame
from .semantic_planning_models import SemanticFrameProposal, SemanticOutputShape
from .semantic_resource_state_planning import resource_collection_definition

_DEFAULT_RECENT_LOOKBACK_SECONDS = 3_600
_DEFAULT_RECENT_RESULT_LIMIT = 5
_MAX_RECENT_RESULT_LIMIT = 20
_RECENT_CHANGE_FACETS = frozenset(
    {"recent_changes", "recent_state_changes", "recently_changed", "state_changes"}
)


def build_recent_resource_state_transition_frame(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Build a targetless latest-state-change collection from accepted typed facets."""

    limit = recent_resource_state_change_limit(judgment)
    if limit is None or judgment is None:
        return None
    explicit_lookback = activity_lookback_seconds(utterance)
    lookback_seconds = explicit_lookback or _DEFAULT_RECENT_LOOKBACK_SECONDS
    evidence_requirements = (
        (f"lookback_seconds.{lookback_seconds}", f"result_limit.{limit}")
        if explicit_lookback is not None
        else ("server_recent_default", f"result_limit.{limit}")
    )
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=(RESOURCE_STATE_OBSERVED_CONCEPT,),
        temporal_scope={"lookback_seconds": lookback_seconds},
        output_shape=SemanticOutputShape.RESOURCE_STATE_TRANSITIONS,
        evidence_requirements=evidence_requirements,
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def recent_resource_state_change_limit(
    judgment: SemanticJudgmentProposal | None,
) -> int | None:
    """Return a bounded requested collection limit, or reject a different activity shape."""

    if (
        judgment is None
        or judgment.primary_intent != "query.resource_change_activity"
        or judgment.action_posture != "advise_only"
        or judgment.action_subject != "none"
        or judgment.secondary_intents
        or any(target.kind != "time_range" for target in judgment.targets)
        or len(judgment.targets) > 1
        or judgment.ambiguous
        or judgment.unresolved_terms
    ):
        return None
    facets = tuple(facet.replace("-", "_") for facet in judgment.requested_facets)
    if not _RECENT_CHANGE_FACETS.intersection(facets):
        return None
    limits: list[int] = []
    for facet in facets:
        prefix, separator, value = facet.partition("_")
        if separator and prefix in {"limit", "top"} and value.isdigit():
            limits.append(int(value))
    if len(set(limits)) > 1:
        return None
    limit = limits[0] if limits else _DEFAULT_RECENT_RESULT_LIMIT
    return limit if 1 <= limit <= _MAX_RECENT_RESULT_LIMIT else None


def compile_resource_state_transition_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.RESOURCE_STATE_TRANSITIONS
        or not _has_function(manifest.descriptors)
    ):
        return None
    lookback_seconds = frame.temporal_scope.get("lookback_seconds")
    state_concepts = tuple(
        sorted(set(frame.measure_concepts).intersection(RESOURCE_STATE_QUERY_CONCEPTS))
    )
    if (
        not isinstance(lookback_seconds, int)
        or isinstance(lookback_seconds, bool)
        or not 60 <= lookback_seconds <= 86_400
        or not state_concepts
    ):
        return None
    broad_state_change = state_concepts == (RESOURCE_STATE_OBSERVED_CONCEPT,)
    state_values = tuple(
        concept.removeprefix("resource_state.")
        for concept in state_concepts
        if concept != RESOURCE_STATE_OBSERVED_CONCEPT
    )
    includes_availability = broad_state_change or any(
        state in RESOURCE_AVAILABILITY_STATE_TRANSITION_VALUES for state in state_values
    )
    definition = resource_collection_definition(
        utterance=utterance,
        descriptors=manifest.descriptors,
        evaluation_time=evaluation_time,
        purpose=purpose,
        require_operational_state_metadata=not includes_availability,
        require_state_metadata=includes_availability,
    )
    scope_id = "resource-transition-scope"
    transition_id = "resource-state-transitions"
    start_at = evaluation_time - timedelta(seconds=lookback_seconds)
    state_types = (
        RESOURCE_STATE_TRANSITION_TYPES
        if includes_availability
        else (RESOURCE_STATE_TRANSITION_TYPE,)
    )
    to_states = RESOURCE_STATE_TRANSITION_VALUES if broad_state_change else state_values
    result_limit = _result_limit(frame.evidence_requirements)
    latest_collection = result_limit is not None
    function_arguments: dict[str, object] = {
        "state_types": list(state_types),
        "to_states": list(to_states),
        "start_at": start_at.isoformat(),
        "end_at": evaluation_time.isoformat(),
        "known_at": evaluation_time.isoformat(),
        "limit": 512 if latest_collection else 256,
    }
    if result_limit is not None:
        function_arguments.update(
            {
                "result_limit": result_limit,
                "latest_first": True,
                "distinct_subjects": True,
            }
        )
    nodes = (
        OntologyQueryNode(
            node_id=scope_id,
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id=transition_id,
            kind=QueryNodeKind.FUNCTION,
            depends_on=(scope_id,),
            arguments_json=canonical_json(
                {
                    "function_name": RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME,
                    "arguments": function_arguments,
                    "dependency_arguments": {scope_id: "query_result"},
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
        "output_node_ids": [transition_id],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=(transition_id,),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _result_limit(requirements: tuple[str, ...]) -> int | None:
    limits = []
    for requirement in requirements:
        prefix, separator, value = requirement.partition(".")
        if separator and prefix == "result_limit" and value.isdigit():
            limits.append(int(value))
    if len(limits) != 1:
        return None
    return limits[0] if 1 <= limits[0] <= _MAX_RECENT_RESULT_LIMIT else None


def _has_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME
        for descriptor in descriptors
    )


__all__ = [
    "build_recent_resource_state_transition_frame",
    "compile_resource_state_transition_plan",
    "recent_resource_state_change_limit",
]

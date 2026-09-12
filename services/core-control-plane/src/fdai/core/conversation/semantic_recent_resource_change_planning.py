"""Compile targetless recent Resource change-history reads."""

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
from fdai.core.ontology_platform.recent_resource_changes import (
    RECENT_RESOURCE_CHANGES_FUNCTION_NAME,
)

from .semantic_planning_frame_core import build_semantic_frame
from .semantic_planning_models import SemanticFrameProposal, SemanticOutputShape

_CHANGE_FACETS = frozenset({"changed_resources", "recent_resource_changes", "resource_changes"})


def build_recent_resource_change_frame(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    limit = recent_resource_change_limit(judgment)
    if limit is None or judgment is None:
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=("resource_change.observed",),
        temporal_scope={"lookback_seconds": 3_600},
        output_shape=SemanticOutputShape.RESOURCE_CHANGES,
        evidence_requirements=("server_recent_default", f"result_limit.{limit}"),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def recent_resource_change_limit(judgment: SemanticJudgmentProposal | None) -> int | None:
    if (
        judgment is None
        or judgment.primary_intent != "query.resource_change_activity"
        or judgment.action_posture != "advise_only"
        or judgment.action_subject != "none"
        or judgment.secondary_intents
        or judgment.targets
        or judgment.ambiguous
        or judgment.unresolved_terms
    ):
        return None
    facets = tuple(facet.replace("-", "_") for facet in judgment.requested_facets)
    if not _CHANGE_FACETS.intersection(facets):
        return None
    limits = {
        int(value)
        for facet in facets
        for prefix, separator, value in (facet.partition("_"),)
        if separator and prefix in {"limit", "top"} and value.isdigit()
    }
    if len(limits) > 1:
        return None
    limit = next(iter(limits), 5)
    return limit if 1 <= limit <= 20 else None


def compile_recent_resource_change_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    del utterance
    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.RESOURCE_CHANGES
        or not _has_function(manifest.descriptors)
    ):
        return None
    lookback = frame.temporal_scope.get("lookback_seconds")
    limit = _result_limit(frame.evidence_requirements)
    if not isinstance(lookback, int) or isinstance(lookback, bool) or limit is None:
        return None
    node = OntologyQueryNode(
        node_id="recent-resource-changes",
        kind=QueryNodeKind.FUNCTION,
        arguments_json=canonical_json(
            {
                "function_name": RECENT_RESOURCE_CHANGES_FUNCTION_NAME,
                "arguments": {
                    "start_at": (evaluation_time - timedelta(seconds=lookback)).isoformat(),
                    "end_at": evaluation_time.isoformat(),
                    "known_at": evaluation_time.isoformat(),
                    "limit": limit,
                },
                "dependency_arguments": {},
            }
        ),
        output_kind="query.table",
    )
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": frame.frame_digest,
        "purpose": purpose,
        "caller_role": manifest.principal_role.value,
        "nodes": [node.model_dump(mode="json")],
        "output_node_ids": [node.node_id],
        "execution_authority": False,
    }
    return verifier.verify(
        OntologyQueryPlan(
            ontology_release_digest=manifest.release_digest,
            semantic_catalog_digest=manifest.manifest_digest,
            problem_frame_digest=frame.frame_digest,
            purpose=purpose,
            caller_role=manifest.principal_role.value,
            nodes=(node,),
            output_node_ids=(node.node_id,),
            plan_digest=content_digest(body),
        ),
        manifest=manifest,
    )


def _result_limit(requirements: tuple[str, ...]) -> int | None:
    values = {
        int(value)
        for item in requirements
        for prefix, separator, value in (item.partition("."),)
        if separator and prefix == "result_limit" and value.isdigit()
    }
    return next(iter(values)) if len(values) == 1 else None


def _has_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        item.get("kind") == "function" and item.get("name") == RECENT_RESOURCE_CHANGES_FUNCTION_NAME
        for item in descriptors
    )

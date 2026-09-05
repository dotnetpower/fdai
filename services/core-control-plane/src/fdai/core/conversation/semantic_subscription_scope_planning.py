"""Compile current-subscription identity reads from a verified semantic frame."""

from __future__ import annotations

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

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest
from fdai.core.ontology_platform.subscription_scope_queries import (
    SUBSCRIPTION_SCOPE_FUNCTION_NAME,
    SUBSCRIPTION_SCOPE_MEASURE_CONCEPTS,
)

from .semantic_planning_models import SemanticOutputShape


def compile_subscription_scope_plan(
    *,
    frame: SemanticProblemFrame,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Build the exact no-input subscription identity Function node."""

    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape != SemanticOutputShape.SUBSCRIPTION_SCOPE_IDENTITY
        or not frame.measure_concepts
        or not set(frame.measure_concepts) <= set(SUBSCRIPTION_SCOPE_MEASURE_CONCEPTS)
        or not _has_subscription_scope_function(manifest.descriptors)
    ):
        return None
    node = OntologyQueryNode(
        node_id="subscription-scope-identity",
        kind=QueryNodeKind.FUNCTION,
        arguments_json=canonical_json(
            {
                "function_name": SUBSCRIPTION_SCOPE_FUNCTION_NAME,
                "arguments": {},
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
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=(node,),
        output_node_ids=(node.node_id,),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _has_subscription_scope_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == SUBSCRIPTION_SCOPE_FUNCTION_NAME
        for descriptor in descriptors
    )


__all__ = ["compile_subscription_scope_plan"]

"""Compile exact-target Resource ingress configuration reads."""

from __future__ import annotations

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
from fdai.core.ontology_platform.resource_ingress_queries import (
    RESOURCE_INGRESS_FUNCTION_NAME,
)

from .semantic_current_state_planning import exact_target_from_constraints
from .semantic_planning_models import SemanticFrameProposal, SemanticOutputShape

_CONTAINER_APP_TYPE = "compute.container-app"
_GENERIC_RESOURCE_OUTPUTS = frozenset(
    {
        SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
        SemanticOutputShape.RESOURCE_LIST,
    }
)


def normalize_ingress_proposal(
    proposal: SemanticFrameProposal,
    *,
    descriptors: tuple[dict[str, Any], ...],
) -> SemanticFrameProposal:
    """Restore typed ingress output from FunctionType-declared measures."""

    if proposal.output_shape is SemanticOutputShape.TARGET_INGRESS_CONFIGURATION:
        return proposal
    if (
        proposal.operation is not SemanticOperation.SELECT
        or proposal.output_shape not in _GENERIC_RESOURCE_OUTPUTS
        or not _ingress_measures(descriptors).intersection(proposal.measure_concepts)
    ):
        return proposal
    return proposal.model_copy(
        update={"output_shape": SemanticOutputShape.TARGET_INGRESS_CONFIGURATION}
    )


def compile_target_ingress_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Build one exact typed ingress projection when identity and type are grounded."""

    if (
        frame.output_shape != SemanticOutputShape.TARGET_INGRESS_CONFIGURATION
        or not _has_ingress_function(manifest.descriptors)
    ):
        return None
    target_name = exact_target_from_constraints(
        frame.subject_constraints,
        utterance=utterance,
        descriptors=manifest.descriptors,
    )
    identity_property = _resource_property(manifest.descriptors, ("name", "display_name", "id"))
    type_property = _resource_property(manifest.descriptors, ("type",))
    if target_name is None or identity_property is None or type_property is None:
        return None
    target_definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(
            ObjectPredicate(
                property=identity_property,
                operator=ObjectPredicateOperator.EQUALS,
                equals=target_name,
            ),
            ObjectPredicate(
                property=type_property,
                operator=ObjectPredicateOperator.EQUALS,
                equals=_CONTAINER_APP_TYPE,
            ),
        ),
        as_of=evaluation_time.astimezone(UTC),
        purpose=purpose,
        limit=2,
    )
    nodes = (
        OntologyQueryNode(
            node_id="ingress-target",
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json(
                {"definition": target_definition.model_dump(mode="json")}
            ),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="resource-ingress-configuration",
            kind=QueryNodeKind.FUNCTION,
            depends_on=("ingress-target",),
            arguments_json=canonical_json(
                {
                    "function_name": RESOURCE_INGRESS_FUNCTION_NAME,
                    "arguments": {},
                    "dependency_arguments": {"ingress-target": "query_result"},
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
        "output_node_ids": ["resource-ingress-configuration"],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=("resource-ingress-configuration",),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _resource_property(
    descriptors: tuple[dict[str, Any], ...],
    candidates: tuple[str, ...],
) -> str | None:
    selected = tuple(
        descriptor
        for descriptor in descriptors
        if descriptor.get("kind") == "object" and descriptor.get("name") == "Resource"
    )
    if len(selected) != 1 or not isinstance(selected[0].get("properties"), Mapping):
        return None
    properties = selected[0]["properties"]
    return next((name for name in candidates if name in properties), None)


def _has_ingress_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == RESOURCE_INGRESS_FUNCTION_NAME
        for descriptor in descriptors
    )


def _ingress_measures(descriptors: tuple[dict[str, Any], ...]) -> frozenset[str]:
    selected = tuple(
        descriptor
        for descriptor in descriptors
        if descriptor.get("kind") == "function"
        and descriptor.get("name") == RESOURCE_INGRESS_FUNCTION_NAME
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


__all__ = ["compile_target_ingress_plan", "normalize_ingress_proposal"]

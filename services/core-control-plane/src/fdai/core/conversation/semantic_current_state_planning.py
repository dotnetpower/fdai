"""Compile exact-target current-state reads from verified request facts."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
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
    SemanticOutputShape,
)

_LOGGER = logging.getLogger(__name__)
_RUNTIME_TARGET = re.compile(
    r"(?<![A-Za-z0-9_.-])[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+){2,}"
    r"(?![A-Za-z0-9_.-])"
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
    target_name = _exact_target_from_constraints(
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


def _exact_target_from_constraints(
    subject_constraints: tuple[str, ...],
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
) -> str | None:
    scanned_utterance = utterance.rstrip(".!?")
    runtime_targets = tuple(match.group(0) for match in _RUNTIME_TARGET.finditer(scanned_utterance))
    if len(runtime_targets) == 1 and any(
        descriptor.get("kind") == "object" and descriptor.get("name") == "Resource"
        for descriptor in descriptors
    ):
        return runtime_targets[0]
    if runtime_targets:
        return None
    declared = {
        name.casefold()
        for descriptor in descriptors
        if descriptor.get("kind") in {"object", "interface"}
        if isinstance((name := descriptor.get("name")), str)
    }
    folded = utterance.casefold()
    candidates = tuple(
        subject
        for subject in subject_constraints
        if subject.casefold() not in declared
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+", subject)
        if folded.count(subject.casefold()) == 1
    )
    return candidates[0] if len(candidates) == 1 else None


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


__all__ = [
    "compile_target_current_state_plan",
]

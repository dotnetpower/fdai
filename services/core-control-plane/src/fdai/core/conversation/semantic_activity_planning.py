"""Compile exact-target bounded change-activity reads from verified request facts."""

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
from fdai.core.ontology_platform.resource_activity_queries import (
    MAX_RESOURCE_ACTIVITY_LOOKBACK_SECONDS,
    RESOURCE_ACTIVITY_FUNCTION_NAME,
)
from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistry,
    query_signal_matches,
)

from .semantic_planning_models import SemanticFrameProposal, SemanticOutputShape
from .semantic_target_identity import exact_target_from_constraints

_LOGGER = logging.getLogger(__name__)
_NORMALIZABLE_OUTPUTS = frozenset(
    {
        SemanticOutputShape.CAUSAL_EVIDENCE,
        SemanticOutputShape.EVIDENCE_VALIDATION,
        SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
        SemanticOutputShape.RESOURCE_LIST,
        SemanticOutputShape.TEMPORAL_COMPARISON,
    }
)
_READ_ONLY_OPERATIONS = frozenset(
    {
        SemanticOperation.COMPARE,
        SemanticOperation.EXPLAIN_CHANGE,
        SemanticOperation.SELECT,
        SemanticOperation.VALIDATE,
    }
)
_LOOKBACK = re.compile(
    r"(?:\b(?:last|past)\s+|지난\s*)"
    r"(?P<count>\d{1,4}|one|a)?\s*"
    r"(?:(?P<unit_en>minutes?|mins?|hours?|days?|weeks?)\b|"
    r"(?P<unit_ko>주일|시간|분|일|주)(?=$|[\s.,!?은는이가의에을를도만와과로]))"
)


def normalize_activity_proposal(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
    inventory_query_language: InventoryQueryLanguageRegistry | None,
) -> SemanticFrameProposal:
    """Restore exact bounded activity only from unambiguous catalog signals."""

    if (
        proposal.output_shape is SemanticOutputShape.TARGET_ACTIVITY
        and proposal.operation is SemanticOperation.SELECT
    ):
        return proposal
    if (
        inventory_query_language is None
        or proposal.operation not in _READ_ONLY_OPERATIONS
        or proposal.output_shape not in _NORMALIZABLE_OUTPUTS
        or proposal.investigation is not None
        or proposal.unresolved_terms
        or proposal.clarification_requirements
        or not query_signal_matches(utterance, inventory_query_language, "activity")
        or query_signal_matches(utterance, inventory_query_language, "causal_diagnosis")
        or not _has_activity_function(descriptors)
    ):
        return proposal
    lookback_seconds = _activity_lookback_seconds(utterance)
    target = exact_target_from_constraints(
        proposal.subject_constraints,
        utterance=utterance,
        descriptors=descriptors,
    )
    if lookback_seconds is None or target is None:
        return proposal
    return proposal.model_copy(
        update={
            "operation": SemanticOperation.SELECT,
            "output_shape": SemanticOutputShape.TARGET_ACTIVITY,
            "temporal_scope": {"lookback_seconds": lookback_seconds},
        }
    )


def compile_target_activity_plan(
    *,
    frame: SemanticProblemFrame,
    utterance: str,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Build one exact Resource activity read with an utterance-bound lookback."""

    if frame.output_shape != SemanticOutputShape.TARGET_ACTIVITY:
        return None
    lookback_seconds = _activity_lookback_seconds(utterance)
    target_name = exact_target_from_constraints(
        frame.subject_constraints,
        utterance=utterance,
        descriptors=manifest.descriptors,
    )
    identity_property = _resource_identity_property(manifest.descriptors)
    if (
        lookback_seconds is None
        or target_name is None
        or identity_property is None
        or not _has_activity_function(manifest.descriptors)
    ):
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
            node_id="activity-target",
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json(
                {"definition": target_definition.model_dump(mode="json")}
            ),
            output_kind="query.table",
        ),
        OntologyQueryNode(
            node_id="resource-activity",
            kind=QueryNodeKind.FUNCTION,
            depends_on=("activity-target",),
            arguments_json=canonical_json(
                {
                    "function_name": RESOURCE_ACTIVITY_FUNCTION_NAME,
                    "arguments": {"lookback_seconds": lookback_seconds},
                    "dependency_arguments": {"activity-target": "query_result"},
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
        "output_node_ids": ["resource-activity"],
        "execution_authority": False,
    }
    plan = OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=manifest.principal_role.value,
        nodes=nodes,
        output_node_ids=("resource-activity",),
        plan_digest=content_digest(body),
    )
    return verifier.verify(plan, manifest=manifest)


def _activity_lookback_seconds(utterance: str) -> int | None:
    matches = tuple(_LOOKBACK.finditer(utterance.casefold()))
    if len(matches) != 1:
        return None
    raw_count = matches[0].group("count")
    count = 1 if raw_count in {None, "a", "one"} else int(raw_count)
    unit = matches[0].group("unit_en") or matches[0].group("unit_ko")
    unit_seconds = {
        "day": 86_400,
        "days": 86_400,
        "일": 86_400,
        "week": 604_800,
        "weeks": 604_800,
        "주": 604_800,
        "주일": 604_800,
        "hour": 3_600,
        "hours": 3_600,
        "시간": 3_600,
    }.get(unit, 60)
    seconds = count * unit_seconds
    return seconds if 60 <= seconds <= MAX_RESOURCE_ACTIVITY_LOOKBACK_SECONDS else None


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


def _has_activity_function(descriptors: tuple[dict[str, Any], ...]) -> bool:
    return any(
        descriptor.get("kind") == "function"
        and descriptor.get("name") == RESOURCE_ACTIVITY_FUNCTION_NAME
        for descriptor in descriptors
    )


__all__ = ["compile_target_activity_plan", "normalize_activity_proposal"]

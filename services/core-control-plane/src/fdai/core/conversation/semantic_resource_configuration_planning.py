"""Compile typed Resource configuration comparisons without interpreting operator phrases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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

from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    OntologyQueryPlanVerifier,
    QueryManifest,
)
from fdai.core.ontology_platform.resource_configuration_queries import (
    MAX_CONFIGURATION_RESOURCES,
    MAX_CONFIGURATION_WINDOW_SECONDS,
    RESOURCE_CONFIGURATION_FUNCTION_NAME,
)
from fdai.core.ontology_platform.resource_configuration_snapshots import (
    RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME,
)

from .conversation_preflight import operational_time_is_past_hour
from .semantic_planning_frame_core import build_semantic_frame
from .semantic_planning_models import SemanticFrameProposal, SemanticOutputShape

RESOURCE_CONFIGURATION_OUTPUT_SHAPE = "resource_configuration_changes"
_SCOPE_FIELDS = frozenset({"id", "name", "type", "parent_id"})


def build_resource_configuration_frame(
    *,
    judgment: SemanticJudgmentProposal | None,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Build an exact-target configuration frame from accepted typed judgment."""
    if (
        judgment is None
        or judgment.primary_intent != "query.resource_configuration_changes"
        or judgment.action_posture != "advise_only"
        or judgment.secondary_intents
        or judgment.ambiguous
        or judgment.unresolved_terms
        or not any(
            descriptor.get("kind") == "object" and descriptor.get("name") == "Resource"
            for descriptor in descriptors
        )
    ):
        return None
    resource_targets = tuple(target for target in judgment.targets if target.kind == "resource")
    if len(resource_targets) != 1 or any(
        target.kind not in {"resource", "time_range"} for target in judgment.targets
    ):
        return None
    target = resource_targets[0]
    if utterance[target.source_start : target.source_end] != target.value:
        return None
    time_targets = tuple(target for target in judgment.targets if target.kind == "time_range")
    lookback_seconds = None
    if (
        len(time_targets) == 1
        and time_targets[0].canonical_value == "duration.PT1H"
        and operational_time_is_past_hour(time_targets[0].value)
    ):
        lookback_seconds = 3_600
    elif not time_targets and "last_hour" in judgment.requested_facets:
        lookback_seconds = 3_600
    if lookback_seconds is None:
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.COMPARE,
        subject_constraints=("Resource", f"Resource.name={target.value}"),
        measure_concepts=(),
        temporal_scope={"lookback_seconds": lookback_seconds},
        output_shape=SemanticOutputShape.RESOURCE_CONFIGURATION_CHANGES,
        evidence_requirements=(),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def compile_resource_configuration_plan(
    *,
    frame: SemanticProblemFrame,
    manifest: QueryManifest,
    verifier: OntologyQueryPlanVerifier,
    evaluation_time: datetime,
    purpose: str,
) -> OntologyQueryPlan | None:
    """Compile a secured selection and two scoped snapshot Functions into a configuration read.

    Constraints are canonical ``Resource`` plus optional exact
    ``Resource.<id|name|type|parent_id>=<value>`` predicates, never prose.
    Time is explicit ``before_as_of``/``after_as_of`` or a bounded lookback;
    both views share the server's evaluation-time knowledge cutoff.
    """
    if (
        frame.output_shape != RESOURCE_CONFIGURATION_OUTPUT_SHAPE
        or frame.operation not in {SemanticOperation.COMPARE, SemanticOperation.EXPLAIN_CHANGE}
        or frame.unresolved_terms
        or frame.investigation_intent_digest is not None
        or frame.measure_concepts
        or purpose != "operations-review"
        or evaluation_time.tzinfo is None
        or not {
            RESOURCE_CONFIGURATION_FUNCTION_NAME,
            RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME,
        }
        <= {
            descriptor.get("name")
            for descriptor in manifest.descriptors
            if descriptor.get("kind") == "function"
        }
    ):
        return None
    known_at = evaluation_time.astimezone(UTC)
    times = _comparison_times(frame.temporal_scope, known_at)
    predicates = _scope_predicates(frame.subject_constraints)
    if times is None or predicates is None:
        return None
    before_as_of, after_as_of = times
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=predicates,
        as_of=known_at,
        purpose=purpose,
        limit=MAX_CONFIGURATION_RESOURCES,
        include_relationships=False,
    )
    scope_id = "configuration-current-scope"
    before_id = "configuration-before"
    after_id = "configuration-after"
    comparison_id = "configuration-compare"
    nodes = (
        OntologyQueryNode(
            node_id=scope_id,
            kind=QueryNodeKind.OBJECT_SET,
            arguments_json=canonical_json({"definition": definition.model_dump(mode="json")}),
            output_kind="query.table",
        ),
        *(
            OntologyQueryNode(
                node_id=node_id,
                kind=QueryNodeKind.FUNCTION,
                depends_on=(scope_id,),
                arguments_json=canonical_json(
                    {
                        "function_name": RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME,
                        "arguments": {
                            "as_of": as_of.isoformat(),
                            "known_at": known_at.isoformat(),
                        },
                        "dependency_arguments": {scope_id: "query_result"},
                    }
                ),
                output_kind="resource.configuration_snapshot",
            )
            for node_id, as_of in ((before_id, before_as_of), (after_id, after_as_of))
        ),
        OntologyQueryNode(
            node_id=comparison_id,
            kind=QueryNodeKind.FUNCTION,
            depends_on=(scope_id, before_id, after_id),
            arguments_json=canonical_json(
                {
                    "function_name": RESOURCE_CONFIGURATION_FUNCTION_NAME,
                    "arguments": {
                        "before_as_of": before_as_of.isoformat(),
                        "after_as_of": after_as_of.isoformat(),
                        "known_at": known_at.isoformat(),
                    },
                    "dependency_arguments": {
                        scope_id: "query_result",
                        before_id: "before_snapshot",
                        after_id: "after_snapshot",
                    },
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
        "output_node_ids": [comparison_id],
        "execution_authority": False,
    }
    return verifier.verify(
        OntologyQueryPlan(
            ontology_release_digest=manifest.release_digest,
            semantic_catalog_digest=manifest.manifest_digest,
            problem_frame_digest=frame.frame_digest,
            purpose=purpose,
            caller_role=manifest.principal_role.value,
            nodes=nodes,
            output_node_ids=(comparison_id,),
            plan_digest=content_digest(body),
        ),
        manifest=manifest,
    )


def _scope_predicates(constraints: tuple[str, ...]) -> tuple[ObjectPredicate, ...] | None:
    if "Resource" not in constraints or len(constraints) > 5:
        return None
    predicates: dict[str, ObjectPredicate] = {}
    for constraint in constraints:
        if constraint == "Resource":
            continue
        field, separator, value = constraint.partition("=")
        if not field.startswith("Resource.") or not separator or not value.strip():
            return None
        name = field.removeprefix("Resource.")
        if name not in _SCOPE_FIELDS or name in predicates:
            return None
        predicates[name] = ObjectPredicate(
            property=name,
            operator=ObjectPredicateOperator.EQUALS,
            equals=value,
        )
    if "id" in predicates and "name" in predicates:
        return None
    return tuple(predicates[key] for key in sorted(predicates))


def _comparison_times(
    scope: dict[str, Any],
    known_at: datetime,
) -> tuple[datetime, datetime] | None:
    if set(scope) == {"lookback_seconds"}:
        seconds = scope["lookback_seconds"]
        if (
            not isinstance(seconds, int)
            or isinstance(seconds, bool)
            or not 300 <= seconds <= MAX_CONFIGURATION_WINDOW_SECONDS
        ):
            return None
        return known_at - timedelta(seconds=seconds), known_at
    if set(scope) != {"before_as_of", "after_as_of"}:
        return None
    try:
        before = _timestamp(scope["before_as_of"])
        after = _timestamp(scope["after_as_of"])
    except (TypeError, ValueError):
        return None
    if not before < after <= known_at:
        return None
    if (known_at - before).total_seconds() > MAX_CONFIGURATION_WINDOW_SECONDS:
        return None
    return before, after


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("configuration time MUST be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("configuration time MUST be timezone-aware")
    return parsed.astimezone(UTC)


__all__ = ["RESOURCE_CONFIGURATION_OUTPUT_SHAPE", "compile_resource_configuration_plan"]

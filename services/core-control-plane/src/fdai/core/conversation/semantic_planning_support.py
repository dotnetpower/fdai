"""Deterministic validation and projection helpers for semantic planning."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai_service_contracts.ontology_query import (
    IntentGraph,
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticProblemFrame,
    canonical_json,
    content_digest,
)

from fdai.core.ontology_platform import QueryManifest

from .conversation_preflight import SocialAct
from .semantic_investigation import VerifiedInvestigationIntent
from .semantic_investigation_planning import InvestigationTimeWindows
from .semantic_judgment import SemanticJudgmentObservation
from .semantic_planning_models import (
    QueryNodeProposal,
    QueryPlanProposal,
    SemanticDirectResponseIntent,
    SemanticPlanningDisposition,
    SemanticPlanningOutcome,
)
from .session import Principal, Turn

_MAX_CONTEXT_TURNS = 8
_MAX_CONTEXT_CHARS = 12_000
_MAX_DESCRIPTORS = 512
_MAX_DESCRIPTOR_BYTES = 524_288
_MAX_LOGGED_PLAN_NODES = 8
_MAX_LOGGED_PLAN_PREDICATES = 6


def _plan_node_summary(plan: OntologyQueryPlan) -> str:
    """Name the capabilities a verified plan selected, for operator diagnosis."""
    parts: list[str] = []
    for node in plan.nodes[:_MAX_LOGGED_PLAN_NODES]:
        arguments = json.loads(node.arguments_json)
        name = arguments.get("function_name") if isinstance(arguments, Mapping) else None
        rendered = f"{node.kind}:{name}" if isinstance(name, str) and name else str(node.kind)
        shape = _object_set_shape(arguments)
        parts.append(f"{rendered}{shape}" if shape else rendered)
    if len(plan.nodes) > _MAX_LOGGED_PLAN_NODES:
        parts.append(f"+{len(plan.nodes) - _MAX_LOGGED_PLAN_NODES}")
    return ",".join(parts)


def _object_set_shape(arguments: object) -> str:
    """Render an ObjectSet's selector and predicate shape without its operands."""
    if not isinstance(arguments, Mapping):
        return ""
    definition = arguments.get("definition")
    if not isinstance(definition, Mapping):
        return ""
    selector = definition.get("selector")
    name = selector.get("name") if isinstance(selector, Mapping) else None
    predicates = definition.get("predicates")
    rendered: list[str] = []
    if isinstance(predicates, list):
        for predicate in predicates[:_MAX_LOGGED_PLAN_PREDICATES]:
            if not isinstance(predicate, Mapping):
                continue
            field = predicate.get("property")
            operator = predicate.get("operator")
            if isinstance(field, str) and field and isinstance(operator, str) and operator:
                rendered.append(f"{field} {operator}")
    selected = name if isinstance(name, str) and name else "?"
    return f"[{selected}" + (f";{','.join(rendered)}]" if rendered else ";no-predicate]")


def _build_plan(
    proposal: QueryPlanProposal,
    *,
    frame: SemanticProblemFrame,
    manifest: QueryManifest,
    principal: Principal,
    purpose: str,
    evaluation_time: datetime,
) -> OntologyQueryPlan:
    current_as_of = evaluation_time.astimezone(UTC).isoformat()
    nodes = tuple(
        OntologyQueryNode(
            node_id=node.node_id,
            kind=node.kind,
            depends_on=node.depends_on,
            arguments_json=canonical_json(
                _frame_bound_node_arguments(
                    node,
                    arguments=_server_bound_node_arguments(node, current_as_of=current_as_of),
                    frame=frame,
                    descriptors=manifest.descriptors,
                )
            ),
            output_kind=node.output_kind,
        )
        for node in _canonical_plan_nodes(proposal)
    )
    payload = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": frame.frame_digest,
        "purpose": purpose,
        "caller_role": principal.role.value,
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "output_node_ids": proposal.output_node_ids,
        "execution_authority": False,
    }
    return OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=purpose,
        caller_role=principal.role.value,
        nodes=nodes,
        output_node_ids=proposal.output_node_ids,
        plan_digest=content_digest(payload),
    )


def _canonical_plan_nodes(proposal: QueryPlanProposal) -> tuple[QueryNodeProposal, ...]:
    ancestors: dict[str, frozenset[str]] = {}
    result: list[QueryNodeProposal] = []
    for node in proposal.nodes:
        dependencies = node.depends_on
        if node.kind is QueryNodeKind.EVIDENCE_JOIN:
            transitive = frozenset(
                ancestor
                for dependency in dependencies
                for ancestor in ancestors.get(dependency, ())
            )
            dependencies = tuple(
                dependency for dependency in dependencies if dependency not in transitive
            )
        result.append(node.model_copy(update={"depends_on": dependencies}))
        ancestors[node.node_id] = frozenset(
            {
                ancestor
                for dependency in dependencies
                for ancestor in (dependency, *ancestors.get(dependency, ()))
            }
        )
    return tuple(result)


def _server_bound_node_arguments(
    node: QueryNodeProposal,
    *,
    current_as_of: str,
) -> dict[str, Any]:
    arguments = copy.deepcopy(node.arguments)
    if node.kind.value != "object_set":
        return arguments
    definition = arguments.get("definition")
    if not isinstance(definition, dict):
        raise ValueError("semantic ObjectSet node requires a definition object")
    definition["as_of"] = current_as_of
    return arguments


def _frame_bound_node_arguments(
    node: QueryNodeProposal,
    *,
    arguments: dict[str, Any],
    frame: SemanticProblemFrame,
    descriptors: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bind exact frame axes that a model plan cannot safely reinterpret."""
    if frame.output_shape == "aggregation_table" and node.kind is QueryNodeKind.FUNCTION:
        function_name = arguments.get("function_name")
        function_arguments = arguments.get("arguments")
        declaration_kinds = frozenset({"action", "function", "interface", "link", "object"})
        requested_kinds = frozenset(frame.subject_constraints)
        if (
            function_name == "query.manifest"
            and isinstance(function_arguments, dict)
            and requested_kinds
            and requested_kinds <= declaration_kinds
        ):
            function_arguments["kinds"] = sorted(requested_kinds)
        return arguments
    if (
        frame.output_shape != "property_filtered_resources"
        or node.kind is not QueryNodeKind.OBJECT_SET
    ):
        return arguments
    if frame.subject_constraints != ("Resource",) or frame.measure_concepts != ("type",):
        return arguments
    definition = arguments.get("definition")
    if not isinstance(definition, dict) or definition.get("predicates"):
        return arguments
    selector = definition.get("selector")
    subject = frame.subject_constraints[0]
    if not isinstance(selector, Mapping) or selector.get("name") != subject:
        return arguments
    properties = next(
        (
            descriptor.get("properties")
            for descriptor in descriptors
            if descriptor.get("kind") == "object" and descriptor.get("name") == subject
        ),
        None,
    )
    if not isinstance(properties, Mapping):
        return arguments
    if "type" not in properties:
        return arguments
    definition["predicates"] = [{"property": "type", "operator": "exists"}]
    return arguments


def _refresh_object_set_cutoffs(
    plan: OntologyQueryPlan,
    *,
    execution_time: datetime,
) -> OntologyQueryPlan:
    current_as_of = execution_time.astimezone(UTC).isoformat()
    nodes = tuple(
        node.model_copy(
            update={
                "arguments_json": canonical_json(
                    {
                        **node.arguments,
                        "definition": {
                            **node.arguments["definition"],
                            "as_of": current_as_of,
                        },
                    }
                )
            }
        )
        if node.kind.value == "object_set"
        else node
        for node in plan.nodes
    )
    payload = {
        **plan.model_dump(mode="json", exclude={"nodes", "plan_digest"}),
        "nodes": [node.model_dump(mode="json") for node in nodes],
    }
    return OntologyQueryPlan.model_validate({**payload, "plan_digest": content_digest(payload)})


def _validated_descriptors(
    selected: Sequence[Mapping[str, Any]],
    *,
    manifest: QueryManifest,
) -> tuple[dict[str, Any], ...]:
    if len(selected) > _MAX_DESCRIPTORS:
        raise ValueError("semantic descriptor selection exceeds bound")
    available = {
        (item.get("kind"), item.get("name"), item.get("declaration_digest")): item
        for item in manifest.descriptors
    }
    result: list[dict[str, Any]] = []
    seen: set[tuple[object, object, object]] = set()
    for candidate in selected:
        key = (
            candidate.get("kind"),
            candidate.get("name"),
            candidate.get("declaration_digest"),
        )
        descriptor = available.get(key)
        if descriptor is None or key in seen:
            raise ValueError("semantic descriptor selection is not an exact manifest subset")
        seen.add(key)
        result.append(copy.deepcopy(descriptor))
    if not result:
        raise ValueError("semantic descriptor selection is empty")
    encoded = json.dumps(
        result,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > _MAX_DESCRIPTOR_BYTES:
        raise ValueError("semantic descriptor selection exceeds byte bound")
    return tuple(result)


def _validated_metric_concepts(values: Sequence[str]) -> tuple[str, ...]:
    concepts = tuple(values)
    if len(concepts) > 64 or len(concepts) != len(set(concepts)):
        raise ValueError("semantic metric concepts MUST be unique and bounded")
    if concepts != tuple(sorted(concepts)) or any(
        re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", value) is None for value in concepts
    ):
        raise ValueError("semantic metric concepts MUST be sorted machine identifiers")
    return concepts


def _bounded_context(prior_turns: Sequence[Turn]) -> tuple[str, ...]:
    selected = prior_turns[-_MAX_CONTEXT_TURNS:]
    result: list[str] = []
    remaining = _MAX_CONTEXT_CHARS
    for turn in selected:
        content = turn.content[:remaining]
        if not content:
            break
        result.append(f"{turn.direction}:{content}")
        remaining -= len(content)
        if remaining == 0:
            break
    return tuple(result)


def _clarification(unresolved_terms: tuple[str, ...]) -> str:
    safe = [term.replace("\r", " ").replace("\n", " ") for term in unresolved_terms[:4]]
    question = "Please clarify these unresolved concepts: " + ", ".join(safe) + "?"
    return question[:511] + "?" if len(question) > 512 else question


def _outcome(
    disposition: SemanticPlanningDisposition,
    reason: str,
    *,
    manifest_digest: str | None = None,
    frame: SemanticProblemFrame | None = None,
    plan: OntologyQueryPlan | None = None,
    intent_graph: IntentGraph | None = None,
    investigation_intent: VerifiedInvestigationIntent | None = None,
    clarification: str | None = None,
    direct_response_intent: SemanticDirectResponseIntent | None = None,
    direct_response_answer: str | None = None,
    social_act: SocialAct = SocialAct.NONE,
    model_observations: tuple[SemanticJudgmentObservation, ...] = (),
) -> SemanticPlanningOutcome:
    return SemanticPlanningOutcome(
        disposition=disposition,
        reason=reason,
        manifest_digest=manifest_digest,
        frame=frame,
        plan=plan,
        intent_graph=intent_graph,
        investigation_intent=investigation_intent,
        clarification=clarification,
        direct_response_intent=direct_response_intent,
        direct_response_answer=direct_response_answer,
        social_act=social_act,
        model_observations=model_observations,
    )


def _investigation_windows(
    evaluation_time: datetime,
    *,
    duration: timedelta,
) -> InvestigationTimeWindows:
    current_end = evaluation_time.astimezone(UTC)
    current_start = current_end - duration
    return InvestigationTimeWindows(
        baseline_start=current_start - duration,
        baseline_end=current_start,
        current_start=current_start,
        current_end=current_end,
        known_at=current_end,
    )


def _investigation_clarification(reason: str) -> str:
    questions = {
        "affected_target_ambiguous": "Which affected service should I investigate?",
        "entity_type_ambiguous": "Which kind of operational object does the affected target name?",
        "entity_identity_property_unavailable": (
            "Which exact operational object should I investigate?"
        ),
        "mixed_relationship_direction": "Which dependency direction should I investigate?",
    }
    return questions.get(reason, "Which exact investigation scope should I use?")

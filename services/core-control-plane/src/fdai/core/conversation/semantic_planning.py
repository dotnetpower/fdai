"""Schema-constrained semantic planning for ordinary-language read questions.

The model proposes meaning and typed nodes from the whole bounded turn. Core
rebuilds every identity, verifies the exact principal manifest, and grants no
execution authority. No phrase, regex, or keyword selects a query capability.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.ontology_query import (
    IntentGraph,
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
    canonical_json,
    content_digest,
)
from pydantic import ValidationError

from fdai.core.ontology_platform import (
    OntologyQueryPlanVerifier,
    QueryManifest,
)
from fdai.core.ontology_platform.incident_queries import (
    INCIDENT_EVIDENCE_FUNCTION_NAME,
    INCIDENT_EVIDENCE_MAX_RECORDS,
)

from .intent_graph import build_intent_graph
from .semantic_planning_cascade import ProposalRejectedError, SemanticPlanningCascade
from .semantic_planning_models import (
    BoundIncident,
    ClarificationRequirement,
    CompleteManifestSelector,
    QueryManifestProvider,
    QueryNodeProposal,
    QueryPlanProposal,
    SemanticDescriptorSelector,
    SemanticFrameProposal,
    SemanticOutputShape,
    SemanticPlanningDisposition,
    SemanticPlanningModel,
    SemanticPlanningOutcome,
)
from .session import Principal, Turn

_LOGGER = logging.getLogger(__name__)
_MAX_CONTEXT_TURNS = 8
_MAX_CONTEXT_CHARS = 12_000
_MAX_DESCRIPTORS = 512
_MAX_DESCRIPTOR_BYTES = 524_288
_MAX_LOGGED_PLAN_NODES = 8
_MAX_LOGGED_PLAN_PREDICATES = 6
_INCIDENT_EVIDENCE_FUNCTION = INCIDENT_EVIDENCE_FUNCTION_NAME
_INCIDENT_EVIDENCE_NODE_ID = "bound_incident_evidence"


class SemanticPlanningService:
    """Build a T1 proposal and escalate only a failed proposal to T2 verification."""

    def __init__(
        self,
        *,
        model: SemanticPlanningModel,
        escalation_model: SemanticPlanningModel | None = None,
        manifests: QueryManifestProvider,
        verifier: OntologyQueryPlanVerifier,
        descriptor_selector: SemanticDescriptorSelector | None = None,
        metric_concepts: Sequence[str] = (),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._manifests = manifests
        self._verifier = verifier
        self._selector = descriptor_selector or CompleteManifestSelector()
        self._metric_concepts = _validated_metric_concepts(metric_concepts)
        self._now = now or (lambda: datetime.now(UTC))
        self._cascade = SemanticPlanningCascade(
            model=model,
            escalation_model=escalation_model,
            verifier=verifier,
            frame_builder=_build_frame,
            plan_builder=_build_plan,
        )

    def plan(
        self,
        *,
        utterance: str,
        prior_turns: Sequence[Turn],
        principal: Principal,
        purpose: str,
        bound_incident: BoundIncident | None = None,
    ) -> SemanticPlanningOutcome:
        """Return a verified plan, one clarification, or a typed safe hold."""

        if not utterance.strip() or len(utterance) > 32_000:
            return _outcome(SemanticPlanningDisposition.UNSUPPORTED, "utterance_out_of_bounds")
        stage = "manifest"
        try:
            manifest = self._manifests.manifest_for(principal=principal, purpose=purpose)
            scope_mismatch = manifest.principal_role.value != principal.role.value
            if scope_mismatch or purpose not in manifest.purposes:
                raise PermissionError("principal manifest scope does not match planning request")
            selected = self._selector.select(
                utterance=utterance,
                manifest=manifest,
                limit=_MAX_DESCRIPTORS,
            )
            descriptors = _validated_descriptors(selected, manifest=manifest)
            context = _bounded_context(prior_turns)
            _LOGGER.info("semantic_planning_stage_completed", extra={"stage": stage})
            stage = "frame_proposal"
            frame_result = self._cascade.propose_frame(
                utterance=utterance,
                context=context,
                descriptors=descriptors,
                principal=principal,
                purpose=purpose,
            )
            if frame_result is None:
                return _outcome(
                    SemanticPlanningDisposition.UNAVAILABLE,
                    "semantic_frame_unavailable",
                    manifest_digest=manifest.manifest_digest,
                )
            proposal, frame = frame_result
            _LOGGER.info("semantic_planning_stage_completed", extra={"stage": stage})
            _LOGGER.info("semantic_planning_stage_completed", extra={"stage": "frame_build"})
            if bound_incident is not None:
                proposal, frame = _resolve_incident_reference(
                    proposal,
                    frame,
                    utterance=utterance,
                    context=context,
                )
            proposal, frame = _resolve_principal_scope_evidence_subject(
                proposal,
                frame,
                utterance=utterance,
                context=context,
            )
            if frame.unresolved_terms:
                clarification = proposal.clarification or _clarification(frame.unresolved_terms)
                return _outcome(
                    SemanticPlanningDisposition.CLARIFICATION,
                    "semantic_clarification_required",
                    manifest_digest=manifest.manifest_digest,
                    frame=frame,
                    clarification=clarification,
                )
            if frame.operation is SemanticOperation.ACTION_DRAFT:
                return _outcome(
                    SemanticPlanningDisposition.ACTION_DRAFT,
                    "governed_action_draft_required",
                    manifest_digest=manifest.manifest_digest,
                    frame=frame,
                )
            stage = "plan_proposal"
            evaluation_time = self._now()
            if evaluation_time.tzinfo is None:
                raise ValueError("semantic planning evaluation time MUST be timezone-aware")
            plan = self._anchored_incident_plan(
                bound_incident=bound_incident,
                frame=frame,
                descriptors=descriptors,
                manifest=manifest,
                principal=principal,
                purpose=purpose,
                evaluation_time=evaluation_time,
            )
            plan_source = "bound_incident" if plan is not None else "proposed"
            if plan is None:
                plan = self._principal_scope_evidence_plan(
                    frame=frame,
                    descriptors=descriptors,
                    manifest=manifest,
                    principal=principal,
                    purpose=purpose,
                    evaluation_time=evaluation_time,
                )
                if plan is not None:
                    plan_source = "principal_scope_evidence"
            if plan is None:
                plan = self._cascade.propose_plan(
                    frame=frame,
                    descriptors=descriptors,
                    metric_concepts=self._metric_concepts,
                    principal=principal,
                    purpose=purpose,
                    manifest=manifest,
                    evaluation_time=evaluation_time,
                )
            if plan is None:
                return _outcome(
                    SemanticPlanningDisposition.UNSUPPORTED,
                    "semantic_plan_unavailable",
                    manifest_digest=manifest.manifest_digest,
                    frame=frame,
                )
            if any(node.kind.value == "object_set" for node in plan.nodes):
                execution_time = self._now()
                if execution_time.tzinfo is None:
                    raise ValueError("semantic execution cutoff MUST be timezone-aware")
                plan = _refresh_object_set_cutoffs(plan, execution_time=execution_time)
                self._verifier.verify(plan, manifest=manifest)
            _LOGGER.info("semantic_planning_stage_completed", extra={"stage": stage})
            _LOGGER.info(
                "semantic_planning_stage_completed",
                extra={
                    "stage": "plan_verify",
                    "plan_nodes": _plan_node_summary(plan),
                    "plan_source": plan_source,
                    "output_shape": frame.output_shape,
                },
            )
            graph = build_intent_graph(
                frame=frame,
                plan=plan,
                confidence=proposal.confidence,
            )
            return _outcome(
                SemanticPlanningDisposition.PLANNED,
                "semantic_plan_verified",
                manifest_digest=manifest.manifest_digest,
                frame=frame,
                plan=plan,
                intent_graph=graph,
            )
        except PermissionError:
            return _outcome(SemanticPlanningDisposition.UNSUPPORTED, "semantic_scope_denied")
        except ProposalRejectedError as exc:
            _LOGGER.warning(
                "semantic_plan_rejected",
                extra={"stage": exc.stage, "failure_type": exc.failure_type},
            )
            return _outcome(SemanticPlanningDisposition.UNSUPPORTED, "semantic_plan_invalid")
        except (ValidationError, TypeError, ValueError) as exc:
            _LOGGER.warning(
                "semantic_plan_rejected",
                extra={"stage": stage, "failure_type": type(exc).__name__},
            )
            return _outcome(SemanticPlanningDisposition.UNSUPPORTED, "semantic_plan_invalid")
        except Exception:  # noqa: BLE001 - model/provider details never cross the boundary
            _LOGGER.exception(
                "semantic_planning_failed",
                extra={"principal_role": principal.role.value, "purpose": purpose},
            )
            return _outcome(SemanticPlanningDisposition.UNAVAILABLE, "semantic_planning_failed")

    def _anchored_incident_plan(
        self,
        *,
        bound_incident: BoundIncident | None,
        frame: SemanticProblemFrame,
        descriptors: tuple[dict[str, Any], ...],
        manifest: QueryManifest,
        principal: Principal,
        purpose: str,
        evaluation_time: datetime,
    ) -> OntologyQueryPlan | None:
        """Build the anchored incident read from the binding, never from a proposal.

        The frame still decides that this turn wants incident evidence. Reading it
        then needs only the two identities the conversation already holds, so no
        model selects the capability or transcribes an identifier. The node runs
        through the same builder and verifier as any proposed plan.
        """
        if bound_incident is None or frame.output_shape != SemanticOutputShape.INCIDENT_EVIDENCE:
            return None
        if not any(
            item.get("kind") == "function" and item.get("name") == _INCIDENT_EVIDENCE_FUNCTION
            for item in descriptors
        ):
            return None
        proposal = QueryPlanProposal(
            nodes=(
                QueryNodeProposal(
                    node_id=_INCIDENT_EVIDENCE_NODE_ID,
                    kind=QueryNodeKind.FUNCTION,
                    depends_on=(),
                    arguments={
                        "function_name": _INCIDENT_EVIDENCE_FUNCTION,
                        "arguments": {
                            "incident_id": bound_incident.incident_id,
                            "correlation_id": bound_incident.correlation_id,
                            "limit": INCIDENT_EVIDENCE_MAX_RECORDS,
                        },
                        "dependency_arguments": {},
                    },
                    output_kind="query.value",
                ),
            ),
            output_node_ids=(_INCIDENT_EVIDENCE_NODE_ID,),
        )
        plan = _build_plan(
            proposal,
            frame=frame,
            manifest=manifest,
            principal=principal,
            purpose=purpose,
            evaluation_time=evaluation_time,
        )
        self._verifier.verify(plan, manifest=manifest)
        return plan

    def _principal_scope_evidence_plan(
        self,
        *,
        frame: SemanticProblemFrame,
        descriptors: tuple[dict[str, Any], ...],
        manifest: QueryManifest,
        principal: Principal,
        purpose: str,
        evaluation_time: datetime,
    ) -> OntologyQueryPlan | None:
        if frame.output_shape != SemanticOutputShape.EVIDENCE_VALIDATION:
            return None
        if not any(
            item.get("kind") == "object" and item.get("name") == "Resource" for item in descriptors
        ):
            return None
        proposal = QueryPlanProposal(
            nodes=(
                QueryNodeProposal(
                    node_id="evidence-scope",
                    kind=QueryNodeKind.OBJECT_SET,
                    arguments={
                        "definition": {
                            "selector": {"kind": "object_type", "name": "Resource"},
                            "as_of": evaluation_time.astimezone(UTC).isoformat(),
                            "purpose": purpose,
                            "limit": 1000,
                        }
                    },
                    output_kind="query.table",
                ),
            ),
            output_node_ids=("evidence-scope",),
        )
        plan = _build_plan(
            proposal,
            frame=frame,
            manifest=manifest,
            principal=principal,
            purpose=purpose,
            evaluation_time=evaluation_time,
        )
        self._verifier.verify(plan, manifest=manifest)
        return plan


def _resolve_incident_reference(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """The binding names the incident, so never ask the operator which one it is.

    Only a turn that will read the anchored incident is answered by the binding.
    Clearing the question on any other shape would let a proposed plan read a
    different incident behind a question the operator never got to answer.
    """
    requirements = proposal.clarification_requirements
    if (
        requirements != (ClarificationRequirement.INCIDENT_REFERENCE,)
        or frame.output_shape != SemanticOutputShape.INCIDENT_EVIDENCE
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
        }
    )
    return resolved, _build_frame(resolved, utterance=utterance, context=context)


def _resolve_principal_scope_evidence_subject(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Use the server-owned Resource scope for an otherwise complete evidence frame."""
    if (
        frame.operation is not SemanticOperation.VALIDATE
        or frame.output_shape != SemanticOutputShape.EVIDENCE_VALIDATION
        or proposal.clarification_requirements
        not in {
            (ClarificationRequirement.SUBJECT,),
            (ClarificationRequirement.RESOURCE_IDENTITY,),
        }
        or proposal.subject_constraints not in {(), ("Resource",)}
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={
            "subject_constraints": ("Resource",),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
        }
    )
    return resolved, _build_frame(resolved, utterance=utterance, context=context)


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
    """Render an ObjectSet's selector and predicate shape without its operands.

    A plan that answers nothing and a plan that answers everything log the same
    node kind, so the selected type and the properties being filtered are the
    only way to tell them apart. Operand values stay out of the log because a
    predicate can carry a tenant-specific identifier.
    """
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


def _build_frame(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> SemanticProblemFrame:
    input_digest = content_digest({"utterance": utterance, "context": context})
    payload = {
        "schema_version": "1.0.0",
        "operation": proposal.operation.value,
        "subject_constraints": proposal.subject_constraints,
        "measure_concepts": proposal.measure_concepts,
        "temporal_scope": proposal.temporal_scope,
        "output_shape": proposal.output_shape.value,
        "evidence_requirements": proposal.evidence_requirements,
        "unresolved_terms": proposal.unresolved_terms,
        "input_digest": input_digest,
        "authority": "candidate_only",
        "execution_authority": False,
    }
    return SemanticProblemFrame(
        operation=proposal.operation,
        subject_constraints=proposal.subject_constraints,
        measure_concepts=proposal.measure_concepts,
        temporal_scope_json=canonical_json(proposal.temporal_scope),
        output_shape=proposal.output_shape.value,
        evidence_requirements=proposal.evidence_requirements,
        unresolved_terms=proposal.unresolved_terms,
        input_digest=input_digest,
        frame_digest=content_digest(payload),
    )


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
                _server_bound_node_arguments(node, current_as_of=current_as_of)
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
    clarification: str | None = None,
) -> SemanticPlanningOutcome:
    return SemanticPlanningOutcome(
        disposition=disposition,
        reason=reason,
        manifest_digest=manifest_digest,
        frame=frame,
        plan=plan,
        intent_graph=intent_graph,
        clarification=clarification,
    )


__all__ = [
    "CompleteManifestSelector",
    "QueryManifestProvider",
    "QueryNodeProposal",
    "QueryPlanProposal",
    "SemanticDescriptorSelector",
    "SemanticFrameProposal",
    "SemanticPlanningDisposition",
    "SemanticPlanningModel",
    "SemanticPlanningOutcome",
    "SemanticPlanningService",
]

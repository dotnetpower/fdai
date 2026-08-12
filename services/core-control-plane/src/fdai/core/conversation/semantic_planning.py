"""Schema-constrained semantic planning for ordinary-language read questions.

The model proposes meaning and typed nodes from the whole bounded turn. Core
rebuilds every identity, verifies the exact principal manifest, and grants no
execution authority. No phrase, regex, or keyword selects a query capability.
"""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from fdai_service_contracts.ontology_query import (
    IntentGraph,
    OntologyQueryNode,
    OntologyQueryPlan,
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

from .intent_graph import build_intent_graph
from .semantic_planning_models import (
    CompleteManifestSelector,
    QueryManifestProvider,
    QueryNodeProposal,
    QueryPlanProposal,
    SemanticDescriptorSelector,
    SemanticFrameProposal,
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


class SemanticPlanningService:
    """Build and verify a semantic read plan without language-specific routing."""

    def __init__(
        self,
        *,
        model: SemanticPlanningModel,
        manifests: QueryManifestProvider,
        verifier: OntologyQueryPlanVerifier,
        descriptor_selector: SemanticDescriptorSelector | None = None,
    ) -> None:
        self._model = model
        self._manifests = manifests
        self._verifier = verifier
        self._selector = descriptor_selector or CompleteManifestSelector()

    def plan(
        self,
        *,
        utterance: str,
        prior_turns: Sequence[Turn],
        principal: Principal,
        purpose: str,
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
            frame_proposal_raw = self._model.propose_frame(
                utterance=utterance,
                context=context,
                descriptors=descriptors,
                principal_role=principal.role.value,
                purpose=purpose,
            )
            if frame_proposal_raw is None:
                return _outcome(
                    SemanticPlanningDisposition.UNAVAILABLE,
                    "semantic_frame_unavailable",
                    manifest_digest=manifest.manifest_digest,
                )
            _LOGGER.info("semantic_planning_stage_completed", extra={"stage": stage})
            stage = "frame_validation"
            proposal = SemanticFrameProposal.model_validate(frame_proposal_raw)
            stage = "frame_build"
            frame = _build_frame(proposal, utterance=utterance, context=context)
            _LOGGER.info("semantic_planning_stage_completed", extra={"stage": stage})
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
            plan_proposal_raw = self._model.propose_plan(
                frame=frame,
                descriptors=descriptors,
                principal_role=principal.role.value,
                purpose=purpose,
            )
            if plan_proposal_raw is None:
                return _outcome(
                    SemanticPlanningDisposition.UNSUPPORTED,
                    "semantic_plan_unavailable",
                    manifest_digest=manifest.manifest_digest,
                    frame=frame,
                )
            _LOGGER.info("semantic_planning_stage_completed", extra={"stage": stage})
            stage = "plan_validation"
            plan_proposal = QueryPlanProposal.model_validate(plan_proposal_raw)
            stage = "plan_build"
            plan = _build_plan(
                plan_proposal,
                frame=frame,
                manifest=manifest,
                principal=principal,
                purpose=purpose,
            )
            stage = "plan_verify"
            self._verifier.verify(plan, manifest=manifest)
            _LOGGER.info("semantic_planning_stage_completed", extra={"stage": stage})
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
        "output_shape": proposal.output_shape,
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
        output_shape=proposal.output_shape,
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
) -> OntologyQueryPlan:
    nodes = tuple(
        OntologyQueryNode(
            node_id=node.node_id,
            kind=node.kind,
            depends_on=node.depends_on,
            arguments_json=canonical_json(node.arguments),
            output_kind=node.output_kind,
        )
        for node in proposal.nodes
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

"""Schema-constrained semantic planning for ordinary-language read questions.

The model proposes meaning and typed nodes from the whole bounded turn. Core
rebuilds every identity, verifies the exact principal manifest, and grants no
execution authority. No phrase, regex, or keyword selects a query capability.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
)
from fdai_service_contracts.semantic_judgment import (
    SemanticDiscourseMode,
    SemanticJudgmentProposal,
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
from fdai.rule_catalog.schema.inventory_query_language import InventoryQueryLanguageRegistry

from .intent_graph import build_intent_graph
from .semantic_judgment import SemanticJudgmentBoundary
from .semantic_planning_cascade import (
    BOUNDED_T2_ESCALATION_POLICY,
    ProposalRejectedError,
    SemanticPlanningCascade,
    SemanticPlanningEscalationPolicy,
)
from .semantic_planning_frame import (
    build_semantic_frame as _build_frame,
)
from .semantic_planning_frame_checks import (
    deterministic_pre_frame_outcome,
    normalize_and_gate_frame,
)
from .semantic_planning_models import (
    BoundIncident,
    BoundInvestigationContinuation,
    BoundResourceContext,
    CompleteManifestSelector,
    QueryManifestProvider,
    QueryNodeProposal,
    QueryPlanProposal,
    SemanticDescriptorSelector,
    SemanticDirectResponseIntent,
    SemanticFrameProposal,
    SemanticOutputShape,
    SemanticPlanningDisposition,
    SemanticPlanningModel,
    SemanticPlanningOutcome,
)
from .semantic_planning_plan_dispatch import PlanDispatchResult, dispatch_semantic_plan
from .semantic_planning_support import (
    _MAX_DESCRIPTORS,
    _bounded_context,
    _build_plan,
    _outcome,
    _plan_node_summary,
    _validated_descriptors,
    _validated_metric_concepts,
)
from .semantic_planning_value_filters import (
    ground_stated_value_filters,
    stated_subject_fragment,
    stated_value_filters,
)
from .session import Principal, Turn

_LOGGER = logging.getLogger(__name__)

_SAFE_VALIDATION_REASONS = frozenset(
    {
        "investigation declaration is absent or ambiguous",
        "investigation target has no readable properties",
        "investigation relationship direction is invalid",
        "investigation relationship path endpoint does not compose",
        "investigation relationship path is empty",
        "investigation query side is absent or ambiguous",
        "query plan output_node_ids MUST reference declared nodes",
        "query extension arguments violate their registered schema",
        "metric concept is absent from the reviewed registry",
        "metric_scope_series MUST read one scoped query.table",
        "metric_scope_series dependency MUST be a scoped query.table",
        "semantic enum predicate operand is not grounded in the utterance",
        "relationship traversal requires one entity dependency",
        "relationship traversal source MUST be an object_set table",
        "relationship traversal target is absent from the manifest",
        "relationship traversal LinkType is absent from the manifest",
        "relationship traversal source endpoint type does not match",
        "relationship traversal target endpoint type is invalid",
        "relationship traversal target endpoint type does not match",
        "function dependencies MUST all have argument bindings",
        "function node omits required arguments",
        "function node supplies unknown arguments",
        "query node arguments do not match the closed schema",
    }
)

_INCIDENT_EVIDENCE_FUNCTION = INCIDENT_EVIDENCE_FUNCTION_NAME
_INCIDENT_EVIDENCE_NODE_ID = "bound_incident_evidence"
_DIRECT_RESPONSE_FACETS = {
    SemanticDirectResponseIntent.GREETING: frozenset(),
    SemanticDirectResponseIntent.SELF_INTRODUCTION: frozenset(
        {"identity", "role", "capabilities", "authority", "authority_boundary"}
    ),
}


def _direct_response_intent(
    proposal: SemanticJudgmentProposal | None,
) -> SemanticDirectResponseIntent | None:
    """Validate one canonical direct-answer intent selected by semantic judgment."""

    if (
        proposal is None
        or proposal.discourse_mode is not SemanticDiscourseMode.DIRECT
        or proposal.secondary_intents
        or proposal.targets
    ):
        return None
    try:
        intent = SemanticDirectResponseIntent(proposal.primary_intent)
    except ValueError:
        return None
    if not set(proposal.requested_facets).issubset(_DIRECT_RESPONSE_FACETS[intent]):
        return None
    return intent


def _safe_validation_reason(exc: ValidationError | TypeError | ValueError) -> str:
    reason = str(exc)
    if reason in _SAFE_VALIDATION_REASONS:
        return reason
    if reason.startswith("query node kind "):
        return "query node kind is unavailable or has no verifier schema"
    return "validation_reason_not_allowlisted"


def _is_temporal_comparison(frame: SemanticProblemFrame | None) -> bool:
    return (
        frame is not None
        and frame.operation is SemanticOperation.COMPARE
        and frame.output_shape == SemanticOutputShape.TEMPORAL_COMPARISON
    )


def _semantic_judgment_capabilities(
    descriptors: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Project principal-scoped ontology descriptors without authority or schemas."""

    kind_map = {
        "action": "action_type",
        "function": "function_type",
        "interface": "interface_type",
        "link": "link_type",
        "object": "object_type",
    }
    capabilities: list[dict[str, Any]] = []
    for descriptor in descriptors:
        kind = descriptor.get("kind")
        name = descriptor.get("name")
        if kind not in kind_map or not isinstance(name, str):
            continue
        capability = {"kind": kind_map[kind], "name": name}
        operation = descriptor.get("operation")
        if kind == "action" and isinstance(operation, str):
            capability["operation"] = operation
        capabilities.append(capability)
    return tuple(capabilities)


class SemanticPlanningService:
    """Build a T1 proposal and apply an explicit policy to bounded T2 fallback."""

    def __init__(
        self,
        *,
        model: SemanticPlanningModel,
        escalation_model: SemanticPlanningModel | None = None,
        manifests: QueryManifestProvider,
        verifier: OntologyQueryPlanVerifier,
        descriptor_selector: SemanticDescriptorSelector | None = None,
        semantic_judgment: SemanticJudgmentBoundary | None = None,
        metric_concepts: Sequence[str] = (),
        inventory_query_language: InventoryQueryLanguageRegistry | None = None,
        investigation_window_seconds: int = 900,
        resource_freshness_seconds: int | None = None,
        escalation_policy: SemanticPlanningEscalationPolicy = BOUNDED_T2_ESCALATION_POLICY,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._manifests = manifests
        self._verifier = verifier
        self._selector = descriptor_selector or CompleteManifestSelector()
        self._semantic_judgment = semantic_judgment
        self._metric_concepts = _validated_metric_concepts(metric_concepts)
        self._inventory_query_language = inventory_query_language
        if not 60 <= investigation_window_seconds <= 86_400:
            raise ValueError("investigation_window_seconds MUST be in [60, 86400]")
        self._investigation_window = timedelta(seconds=investigation_window_seconds)
        if resource_freshness_seconds is not None and not 1 <= resource_freshness_seconds <= 86_400:
            raise ValueError("resource_freshness_seconds MUST be in [1, 86400]")
        self._resource_freshness_seconds = resource_freshness_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._cascade = SemanticPlanningCascade(
            model=model,
            escalation_model=escalation_model,
            verifier=verifier,
            frame_builder=_build_frame,
            plan_builder=_build_plan,
            inventory_query_language=inventory_query_language,
            escalation_policy=escalation_policy,
        )

    def plan(
        self,
        *,
        utterance: str,
        prior_turns: Sequence[Turn],
        principal: Principal,
        purpose: str,
        bound_incident: BoundIncident | None = None,
        bound_resource_context: BoundResourceContext | None = None,
        bound_investigation_continuation: BoundInvestigationContinuation | None = None,
        escalation_policy: SemanticPlanningEscalationPolicy | None = None,
    ) -> SemanticPlanningOutcome:
        """Return a verified plan, one clarification, or a typed safe hold."""

        if not utterance.strip() or len(utterance) > 32_000:
            return _outcome(SemanticPlanningDisposition.UNSUPPORTED, "utterance_out_of_bounds")
        stage = "manifest"
        manifest_digest: str | None = None
        accepted_frame: SemanticProblemFrame | None = None
        try:
            manifest = self._manifests.manifest_for(principal=principal, purpose=purpose)
            manifest_digest = manifest.manifest_digest
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
            semantic_judgment = None
            if self._semantic_judgment is not None:
                judgment_capabilities = _semantic_judgment_capabilities(descriptors)
                bound_subject_types = (
                    ("Incident",)
                    if bound_incident is not None
                    and any(
                        capability.get("kind") == "object_type"
                        and capability.get("name") == "Incident"
                        for capability in judgment_capabilities
                    )
                    else ()
                )
                judgment_result = self._semantic_judgment.judge(
                    utterance=utterance,
                    context=context,
                    capabilities=judgment_capabilities,
                    allow_escalation=False,
                    bound_subject_types=bound_subject_types,
                )
                judgment_posture = (
                    judgment_result.proposal.action_posture
                    if judgment_result.proposal is not None
                    else judgment_result.receipt.disposition.value
                )
                _LOGGER.info(
                    f"semantic_planning_judgment_{judgment_posture}",
                    extra={
                        "disposition": judgment_result.receipt.disposition.value,
                        "tier": (
                            judgment_result.receipt.tier.value
                            if judgment_result.receipt.tier is not None
                            else None
                        ),
                        "action_posture": judgment_posture,
                        "primary_intent": (
                            judgment_result.proposal.primary_intent
                            if judgment_result.proposal is not None
                            else None
                        ),
                        "secondary_intents": (
                            ",".join(judgment_result.proposal.secondary_intents)
                            if judgment_result.proposal is not None
                            else ""
                        ),
                        "discourse_mode": (
                            judgment_result.proposal.discourse_mode.value
                            if judgment_result.proposal is not None
                            else None
                        ),
                        "requested_facets": (
                            ",".join(judgment_result.proposal.requested_facets)
                            if judgment_result.proposal is not None
                            else ""
                        ),
                        "target_count": (
                            len(judgment_result.proposal.targets)
                            if judgment_result.proposal is not None
                            else 0
                        ),
                        "target_kinds": (
                            ",".join(target.kind for target in judgment_result.proposal.targets)
                            if judgment_result.proposal is not None
                            else ""
                        ),
                        "canonical_target_types": (
                            ",".join(
                                sorted(
                                    {
                                        target.canonical_value
                                        for target in judgment_result.proposal.targets
                                        if target.canonical_value is not None
                                    }
                                )
                            )
                            if judgment_result.proposal is not None
                            else ""
                        ),
                    },
                )
                if judgment_result.accepted and judgment_result.proposal is not None:
                    semantic_judgment = judgment_result.proposal.model_dump(mode="json")
            _LOGGER.info("semantic_planning_stage_completed", extra={"stage": stage})
            judgment_proposal = (
                judgment_result.proposal if self._semantic_judgment is not None else None
            )
            direct_response_intent = _direct_response_intent(
                judgment_result.proposal
                if self._semantic_judgment is not None
                and judgment_result.accepted
                and judgment_result.proposal is not None
                else None
            )
            if direct_response_intent is not None:
                return _outcome(
                    SemanticPlanningDisposition.DIRECT_RESPONSE,
                    "semantic_direct_response",
                    manifest_digest=manifest.manifest_digest,
                    direct_response_intent=direct_response_intent,
                    model_observations=judgment_result.observations,
                )
            pre_frame_outcome = deterministic_pre_frame_outcome(
                judgment=judgment_proposal,
                utterance=utterance,
                context=context,
                descriptors=descriptors,
                manifest_digest=manifest.manifest_digest,
                bound_incident=bound_incident is not None,
            )
            if pre_frame_outcome is not None:
                return pre_frame_outcome
            stage = "frame_proposal"
            frame_result = self._cascade.propose_frame(
                utterance=utterance,
                context=context,
                descriptors=descriptors,
                metric_concepts=self._metric_concepts,
                principal=principal,
                purpose=purpose,
                semantic_judgment=semantic_judgment,
                bound_investigation_continuation=bound_investigation_continuation,
                escalation_policy=escalation_policy,
            )
            if frame_result is None:
                return _outcome(
                    SemanticPlanningDisposition.UNAVAILABLE,
                    "semantic_frame_unavailable",
                    manifest_digest=manifest.manifest_digest,
                )
            proposal, frame, investigation_intent = frame_result
            _LOGGER.info("semantic_planning_stage_completed", extra={"stage": stage})
            _LOGGER.info("semantic_planning_stage_completed", extra={"stage": "frame_build"})
            declared_subject_types = {
                descriptor["name"]
                for descriptor in descriptors
                if descriptor.get("kind") in {"object", "interface"}
                and isinstance(descriptor.get("name"), str)
            }
            subject_types = ",".join(
                sorted(set(frame.subject_constraints).intersection(declared_subject_types))
            )
            measure_concepts = ",".join(
                sorted(set(frame.measure_concepts).intersection(self._metric_concepts))
            )
            _LOGGER.info(
                "semantic_planning_frame_observed "
                "operation=%s output_shape=%s subject_types=%s measure_concepts=%s "
                "unresolved_count=%d structured_investigation=%s",
                frame.operation.value,
                frame.output_shape,
                subject_types,
                measure_concepts,
                len(frame.unresolved_terms),
                investigation_intent is not None,
                extra={"output_shape": frame.output_shape},
            )
            normalized_frame = normalize_and_gate_frame(
                proposal=proposal,
                frame=frame,
                investigation_intent=investigation_intent,
                judgment=judgment_proposal,
                utterance=utterance,
                context=context,
                descriptors=descriptors,
                manifest_digest=manifest.manifest_digest,
                bound_incident=bound_incident is not None,
                inventory_query_language=self._inventory_query_language,
            )
            if isinstance(normalized_frame, SemanticPlanningOutcome):
                return normalized_frame
            proposal, frame, investigation_intent = normalized_frame
            accepted_frame = frame
            stage = "plan_proposal"
            dispatched = dispatch_semantic_plan(
                utterance=utterance,
                context=context,
                proposal=proposal,
                frame=frame,
                investigation_intent=investigation_intent,
                descriptors=descriptors,
                manifest=manifest,
                principal=principal,
                purpose=purpose,
                bound_incident=bound_incident,
                bound_resource_context=bound_resource_context,
                bound_investigation_continuation=bound_investigation_continuation,
                verifier=self._verifier,
                metric_concepts=self._metric_concepts,
                inventory_query_language=self._inventory_query_language,
                investigation_window=self._investigation_window,
                resource_freshness_seconds=self._resource_freshness_seconds,
                now=self._now,
                cascade=self._cascade,
                escalation_policy=escalation_policy,
                anchored_incident_plan_builder=self._anchored_incident_plan,
                stated_value_filter_plan_builder=self._stated_value_filter_plan,
            )
            if isinstance(dispatched, SemanticPlanningOutcome):
                return dispatched
            dispatch_result: PlanDispatchResult = dispatched
            proposal = dispatch_result.proposal
            frame = dispatch_result.frame
            investigation_intent = dispatch_result.investigation_intent
            plan = dispatch_result.plan
            plan_source = dispatch_result.plan_source
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
                investigation_intent=investigation_intent,
            )
        except PermissionError:
            return _outcome(SemanticPlanningDisposition.UNSUPPORTED, "semantic_scope_denied")
        except ProposalRejectedError as exc:
            _LOGGER.warning(
                "semantic_plan_rejected",
                extra={"stage": exc.stage, "failure_type": exc.failure_type},
            )
            disposition = (
                SemanticPlanningDisposition.UNAVAILABLE
                if _is_temporal_comparison(accepted_frame)
                else SemanticPlanningDisposition.UNSUPPORTED
            )
            reason = (
                "semantic_temporal_comparison_unavailable"
                if disposition is SemanticPlanningDisposition.UNAVAILABLE
                else "semantic_plan_invalid"
            )
            return _outcome(
                disposition,
                reason,
                manifest_digest=manifest_digest,
                frame=accepted_frame,
            )
        except (ValidationError, TypeError, ValueError) as exc:
            _LOGGER.warning(
                "semantic_plan_rejected",
                extra={
                    "stage": stage,
                    "failure_type": type(exc).__name__,
                    "validation_reason": _safe_validation_reason(exc),
                },
            )
            disposition = (
                SemanticPlanningDisposition.UNAVAILABLE
                if _is_temporal_comparison(accepted_frame)
                else SemanticPlanningDisposition.UNSUPPORTED
            )
            reason = (
                "semantic_temporal_comparison_unavailable"
                if disposition is SemanticPlanningDisposition.UNAVAILABLE
                else "semantic_plan_invalid"
            )
            return _outcome(
                disposition,
                reason,
                manifest_digest=manifest_digest,
                frame=accepted_frame,
            )
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

    def _stated_value_filter_plan(
        self,
        *,
        frame: SemanticProblemFrame,
        utterance: str,
        descriptors: tuple[dict[str, Any], ...],
        manifest: QueryManifest,
        principal: Principal,
        purpose: str,
        evaluation_time: datetime,
    ) -> OntologyQueryPlan | None:
        """Build a model-free ObjectSet for an explicit catalog value filter."""
        if frame.operation is not SemanticOperation.SELECT or frame.output_shape not in {
            SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
            SemanticOutputShape.RESOURCE_LIST,
        }:
            return None
        filters = stated_value_filters(utterance, descriptors)
        object_types = {object_type for object_type, _property_name in filters}
        if not filters or len(object_types) != 1:
            return None
        object_type = next(iter(object_types))
        subject_fragment = stated_subject_fragment(
            utterance,
            frame.subject_constraints,
            descriptors,
        )
        fragment_property = None
        if subject_fragment is not None:
            properties = next(
                (
                    descriptor.get("properties")
                    for descriptor in descriptors
                    if descriptor.get("kind") == "object" and descriptor.get("name") == object_type
                ),
                None,
            )
            if not isinstance(properties, Mapping):
                return None
            fragment_property = next(
                (
                    property_name
                    for property_name in ("name", "label", "id")
                    if isinstance(properties.get(property_name), Mapping)
                    and not isinstance(properties[property_name].get("values"), list)
                ),
                None,
            )
            if fragment_property is None:
                return None
        predicates = []
        if fragment_property is not None:
            predicates.append({"property": fragment_property, "operator": "exists"})
        predicates.extend(
            {"property": property_name, "operator": "exists"}
            for filter_type, property_name in sorted(filters)
            if filter_type == object_type
        )
        proposal = QueryPlanProposal(
            nodes=(
                QueryNodeProposal(
                    node_id="stated-value-filter",
                    kind=QueryNodeKind.OBJECT_SET,
                    arguments={
                        "definition": {
                            "selector": {"kind": "object_type", "name": object_type},
                            "predicates": predicates,
                            "as_of": evaluation_time.astimezone(UTC).isoformat(),
                            "purpose": purpose,
                            "limit": 1000,
                        }
                    },
                    output_kind="query.table",
                ),
            ),
            output_node_ids=("stated-value-filter",),
        )
        plan = _build_plan(
            proposal,
            frame=frame,
            manifest=manifest,
            principal=principal,
            purpose=purpose,
            evaluation_time=evaluation_time,
        )
        plan, grounded = ground_stated_value_filters(
            plan,
            utterance=utterance,
            descriptors=descriptors,
            subject_constraints=frame.subject_constraints,
        )
        required_grounding = {
            f"{filter_type}.{property_name}" for filter_type, property_name in filters
        }
        if not required_grounding <= set(grounded):
            return None
        self._verifier.verify(plan, manifest=manifest)
        return plan


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

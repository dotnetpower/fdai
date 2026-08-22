"""Schema-constrained semantic planning for ordinary-language read questions.

The model proposes meaning and typed nodes from the whole bounded turn. Core
rebuilds every identity, verifies the exact principal manifest, and grants no
execution authority. No phrase, regex, or keyword selects a query capability.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
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
from .semantic_activity_planning import compile_target_activity_plan
from .semantic_current_state_planning import (
    compile_target_current_state_plan,
    exact_target_from_constraints,
)
from .semantic_error_activity_planning import compile_target_error_activity_plan
from .semantic_health_planning import compile_target_health_plan
from .semantic_impact_planning import compile_target_impact_plan
from .semantic_ingress_planning import compile_target_ingress_plan
from .semantic_investigation_planning import (
    InvestigationClarificationRequiredError,
    compile_investigation_plan,
)
from .semantic_planning_cascade import (
    BOUNDED_T2_ESCALATION_POLICY,
    ProposalRejectedError,
    SemanticPlanningCascade,
    SemanticPlanningEscalationPolicy,
)
from .semantic_planning_frame import (
    build_semantic_frame as _build_frame,
)
from .semantic_planning_frame import (
    resolve_incident_reference as _resolve_incident_reference,
)
from .semantic_planning_frame import (
    resolve_principal_scope_evidence_subject as _resolve_principal_scope_evidence_subject,
)
from .semantic_planning_models import (
    BoundIncident,
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
from .semantic_planning_support import (
    _MAX_DESCRIPTORS,
    _bounded_context,
    _build_plan,
    _clarification,
    _investigation_clarification,
    _investigation_windows,
    _outcome,
    _plan_node_summary,
    _refresh_object_set_cutoffs,
    _validated_descriptors,
    _validated_metric_concepts,
)
from .semantic_planning_value_filters import (
    ground_stated_value_filters,
    stated_subject_fragment,
    stated_value_filters,
    verify_stated_value_filter_operands,
)
from .semantic_resource_event_planning import compile_resource_event_plan
from .semantic_resource_health_planning import compile_resource_health_plan
from .semantic_resource_metric_planning import (
    compile_exact_resource_metric_plan,
    compile_exact_resource_metric_series_plan,
    compile_resource_metric_plan,
)
from .semantic_resource_state_planning import compile_resource_state_plan
from .semantic_service_health_planning import compile_service_health_plan
from .semantic_target_candidate_planning import (
    build_resource_target_candidates_fallback,
    compile_resource_target_candidates_plan,
    resolve_resource_target_candidates,
    resource_target_candidates_apply_to_utterance,
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
_EXACT_RESOURCE_TARGET_OUTPUTS = frozenset(
    {
        SemanticOutputShape.CAUSAL_EVIDENCE,
        SemanticOutputShape.INVENTORY_IMPACT,
        SemanticOutputShape.TARGET_ACTIVITY,
        SemanticOutputShape.TARGET_CURRENT_STATE,
        SemanticOutputShape.TARGET_ERROR_ACTIVITY_CORRELATION,
        SemanticOutputShape.TARGET_HEALTH_ASSESSMENT,
        SemanticOutputShape.TARGET_INGRESS_CONFIGURATION,
        SemanticOutputShape.TARGET_RESOURCE_METRIC,
        SemanticOutputShape.TARGET_RESOURCE_METRIC_SERIES,
        SemanticOutputShape.TEMPORAL_COMPARISON,
        SemanticOutputShape.TOPOLOGY_GRAPH,
    }
)


def _safe_validation_reason(exc: ValidationError | TypeError | ValueError) -> str:
    reason = str(exc)
    if reason in _SAFE_VALIDATION_REASONS:
        return reason
    if reason.startswith("query node kind "):
        return "query node kind is unavailable or has no verifier schema"
    return "validation_reason_not_allowlisted"


def _resource_target_clarification(
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> str | None:
    """Ask for one exact Resource before a target-scoped first-turn read."""
    if context or frame.output_shape in {
        SemanticOutputShape.RESOURCE_STATE_LIST,
        SemanticOutputShape.RESOURCE_TARGET_CANDIDATES,
    }:
        return None
    filters = stated_value_filters(utterance, descriptors)
    resource_filters = {
        property_name: values
        for (object_type, property_name), values in filters.items()
        if object_type == "Resource"
    }
    residual_subject = stated_subject_fragment(
        utterance,
        frame.subject_constraints,
        descriptors,
    )
    target_scoped = frame.output_shape in _EXACT_RESOURCE_TARGET_OUTPUTS or (
        residual_subject is not None and bool(frame.measure_concepts)
    )
    if (
        not resource_filters
        or not target_scoped
        or exact_target_from_constraints(
            frame.subject_constraints,
            utterance=utterance,
            descriptors=descriptors,
        )
        is not None
    ):
        return None
    korean = re.search(r"[가-힣]", utterance) is not None
    if frame.output_shape == SemanticOutputShape.TEMPORAL_COMPARISON:
        return (
            "확인할 리소스의 정확한 이름 또는 리소스 ID를 알려주세요. "
            "대상을 지정하면 요청한 기간의 변경 이력과 사용 가능한 근거를 검증하고, "
            "확인할 수 없는 항목은 한계로 구분하겠습니다."
            if korean
            else (
                "Provide the exact resource name or resource ID. Once identified, I will verify "
                "the change history for the requested period against available evidence and "
                "separate any unverified fields as limitations."
            )
        )
    return (
        "확인할 리소스의 정확한 이름 또는 리소스 ID를 알려주세요. "
        "대상을 지정하면 요청한 상태와 사용 가능한 근거를 검증하고, "
        "확인할 수 없는 항목은 한계로 구분하겠습니다."
        if korean
        else (
            "Provide the exact resource name or resource ID. Once identified, I will verify "
            "the requested state against available evidence and separate any unverified fields "
            "as limitations."
        )
    )


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
        metric_concepts: Sequence[str] = (),
        inventory_query_language: InventoryQueryLanguageRegistry | None = None,
        investigation_window_seconds: int = 900,
        escalation_policy: SemanticPlanningEscalationPolicy = BOUNDED_T2_ESCALATION_POLICY,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._manifests = manifests
        self._verifier = verifier
        self._selector = descriptor_selector or CompleteManifestSelector()
        self._metric_concepts = _validated_metric_concepts(metric_concepts)
        self._inventory_query_language = inventory_query_language
        if not 60 <= investigation_window_seconds <= 86_400:
            raise ValueError("investigation_window_seconds MUST be in [60, 86400]")
        self._investigation_window = timedelta(seconds=investigation_window_seconds)
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
        escalation_policy: SemanticPlanningEscalationPolicy | None = None,
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
                metric_concepts=self._metric_concepts,
                principal=principal,
                purpose=purpose,
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
            proposal, frame = resolve_resource_target_candidates(
                proposal,
                frame,
                utterance=utterance,
                context=context,
                descriptors=descriptors,
                inventory_query_language=self._inventory_query_language,
            )
            if frame.output_shape == SemanticOutputShape.RESOURCE_TARGET_CANDIDATES:
                investigation_intent = None
            resource_clarification = _resource_target_clarification(
                frame,
                utterance=utterance,
                context=context,
                descriptors=descriptors,
            )
            if resource_clarification is not None:
                return _outcome(
                    SemanticPlanningDisposition.CLARIFICATION,
                    "semantic_clarification_required",
                    manifest_digest=manifest.manifest_digest,
                    frame=frame,
                    clarification=resource_clarification,
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
            if frame.output_shape == SemanticOutputShape.EVIDENCE_VALIDATION:
                return _outcome(
                    SemanticPlanningDisposition.UNSUPPORTED,
                    "semantic_evidence_validation_unavailable",
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
                plan = compile_resource_target_candidates_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                )
                if plan is not None:
                    plan_source = "server_resource_target_candidates"
            if plan is None:
                plan = compile_target_error_activity_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                )
                if plan is not None:
                    plan_source = "server_target_error_activity"
            if plan is None:
                plan = compile_target_health_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                )
                if plan is not None:
                    plan_source = "server_target_health"
            if plan is None:
                plan = compile_target_ingress_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                )
                if plan is not None:
                    plan_source = "server_target_ingress"
            if plan is None:
                plan = compile_target_current_state_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                )
                if plan is not None:
                    plan_source = "server_target_current_state"
            if plan is None:
                plan = compile_service_health_plan(
                    frame=frame,
                    manifest=manifest,
                    verifier=self._verifier,
                    purpose=purpose,
                )
                if plan is not None:
                    plan_source = "server_subscription_service_health"
            if plan is None:
                plan = compile_resource_event_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                )
                if plan is not None:
                    plan_source = "server_resource_event_history"
            if plan is None:
                plan = compile_resource_health_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                )
                if plan is not None:
                    plan_source = "server_resource_health_inventory"
            if plan is None:
                plan = compile_exact_resource_metric_series_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                    available_metric_concepts=self._metric_concepts,
                )
                if plan is not None:
                    plan_source = "server_target_resource_metric_series"
            if plan is None:
                plan = compile_exact_resource_metric_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                    available_metric_concepts=self._metric_concepts,
                )
                if plan is not None:
                    plan_source = "server_target_resource_metric"
            if plan is None:
                plan = compile_resource_metric_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                    available_metric_concepts=self._metric_concepts,
                )
                if plan is not None:
                    plan_source = "server_resource_metric_inventory"
            if plan is None:
                plan = compile_resource_state_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                )
                if plan is not None:
                    plan_source = "server_resource_state_inventory"
            if plan is None:
                plan = compile_target_activity_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                )
                if plan is not None:
                    plan_source = "server_target_activity"
            if plan is None:
                plan = compile_target_impact_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                )
                if plan is not None:
                    plan_source = "server_target_impact"
            if plan is None and investigation_intent is not None:
                try:
                    plan = compile_investigation_plan(
                        investigation_intent,
                        manifest=manifest,
                        verifier=self._verifier,
                        windows=_investigation_windows(
                            evaluation_time,
                            duration=self._investigation_window,
                        ),
                        purpose=purpose,
                        problem_frame_digest=frame.frame_digest,
                    )
                except InvestigationClarificationRequiredError as exc:
                    return _outcome(
                        SemanticPlanningDisposition.CLARIFICATION,
                        exc.reason,
                        manifest_digest=manifest.manifest_digest,
                        frame=frame,
                        clarification=_investigation_clarification(exc.reason),
                    )
                plan_source = "server_investigation"
            if plan is None and resource_target_candidates_apply_to_utterance(
                frame,
                utterance=utterance,
                descriptors=descriptors,
                inventory_query_language=self._inventory_query_language,
            ):
                fallback = build_resource_target_candidates_fallback(
                    utterance=utterance,
                    context=context,
                    descriptors=descriptors,
                    confidence=proposal.confidence,
                    inventory_query_language=self._inventory_query_language,
                )
                if fallback is not None:
                    proposal, frame = fallback
                    investigation_intent = None
                    plan = compile_resource_target_candidates_plan(
                        frame=frame,
                        utterance=utterance,
                        manifest=manifest,
                        verifier=self._verifier,
                        evaluation_time=evaluation_time,
                        purpose=purpose,
                    )
                    if plan is not None:
                        plan_source = "server_resource_target_candidates"
            if plan is None:
                plan = self._stated_value_filter_plan(
                    frame=frame,
                    utterance=utterance,
                    descriptors=descriptors,
                    manifest=manifest,
                    principal=principal,
                    purpose=purpose,
                    evaluation_time=evaluation_time,
                )
                if plan is not None:
                    plan_source = "server_stated_filter"
            if plan is None:
                plan = self._cascade.propose_plan(
                    frame=frame,
                    descriptors=descriptors,
                    metric_concepts=self._metric_concepts,
                    principal=principal,
                    purpose=purpose,
                    manifest=manifest,
                    evaluation_time=evaluation_time,
                    escalation_policy=escalation_policy,
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
                plan, grounded = ground_stated_value_filters(
                    plan,
                    utterance=utterance,
                    descriptors=descriptors,
                    subject_constraints=(
                        ()
                        if frame.output_shape
                        in {
                            SemanticOutputShape.RESOURCE_STATE_LIST,
                            SemanticOutputShape.RESOURCE_TARGET_CANDIDATES,
                        }
                        else frame.subject_constraints
                    ),
                )
                if grounded:
                    _LOGGER.info(
                        "semantic_plan_filter_grounded",
                        extra={"grounded_properties": ",".join(grounded)},
                    )
                if plan_source == "proposed":
                    verify_stated_value_filter_operands(
                        plan,
                        utterance=utterance,
                        descriptors=descriptors,
                    )
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
                investigation_intent=investigation_intent,
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
                extra={
                    "stage": stage,
                    "failure_type": type(exc).__name__,
                    "validation_reason": _safe_validation_reason(exc),
                },
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

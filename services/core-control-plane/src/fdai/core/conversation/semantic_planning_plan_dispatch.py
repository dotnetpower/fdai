"""Sequential plan-dispatch helpers for semantic planning.

This module preserves the existing planner ordering, fallback behavior, and
plan_source reporting from SemanticPlanningService.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fdai_service_contracts.ontology_query import OntologyQueryPlan, SemanticOperation

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest
from fdai.rule_catalog.schema.inventory_query_language import InventoryQueryLanguageRegistry

from .semantic_activity_planning import compile_target_activity_plan
from .semantic_contextual_resource_planning import compile_contextual_resource_plan
from .semantic_current_state_planning import compile_target_current_state_plan
from .semantic_error_activity_planning import compile_target_error_activity_plan
from .semantic_health_planning import compile_target_health_plan
from .semantic_impact_planning import compile_target_impact_plan
from .semantic_ingress_planning import compile_target_ingress_plan
from .semantic_investigation import VerifiedInvestigationIntent
from .semantic_investigation_planning import (
    InvestigationClarificationRequiredError,
    compile_investigation_plan,
)
from .semantic_kubernetes_pod_recovery_planning import compile_kubernetes_pod_recovery_plan
from .semantic_kubernetes_rollout_planning import compile_kubernetes_rollout_plan
from .semantic_latency_recovery_planning import (
    LatencyRecoveryWindowPendingError,
    compile_latency_recovery_plan,
)
from .semantic_mysql_pressure_planning import compile_mysql_pressure_plan
from .semantic_planning_cascade import SemanticPlanningCascade, SemanticPlanningEscalationPolicy
from .semantic_planning_models import (
    BoundIncident,
    BoundInvestigationContinuation,
    BoundResourceContext,
    SemanticOutputShape,
    SemanticPlanningDisposition,
    SemanticPlanningOutcome,
)
from .semantic_planning_support import (
    _investigation_clarification,
    _investigation_windows,
    _outcome,
    _refresh_object_set_cutoffs,
)
from .semantic_planning_value_filters import (
    ground_stated_value_filters,
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
    resource_target_candidates_apply_to_utterance,
)
from .session import Principal

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PlanDispatchResult:
    proposal: Any
    frame: Any
    investigation_intent: VerifiedInvestigationIntent | None
    plan: OntologyQueryPlan
    plan_source: str


def _is_temporal_comparison(frame: Any) -> bool:
    return (
        frame is not None
        and frame.operation is SemanticOperation.COMPARE
        and frame.output_shape == SemanticOutputShape.TEMPORAL_COMPARISON
    )


def dispatch_semantic_plan(
    *,
    utterance: str,
    context: tuple[str, ...],
    proposal: Any,
    frame: Any,
    investigation_intent: VerifiedInvestigationIntent | None,
    descriptors: tuple[dict[str, Any], ...],
    manifest: QueryManifest,
    principal: Principal,
    purpose: str,
    bound_incident: BoundIncident | None,
    bound_resource_context: BoundResourceContext | None,
    bound_investigation_continuation: BoundInvestigationContinuation | None,
    verifier: OntologyQueryPlanVerifier,
    metric_concepts: tuple[str, ...],
    inventory_query_language: InventoryQueryLanguageRegistry | None,
    investigation_window: timedelta,
    resource_freshness_seconds: int | None,
    now: Callable[[], datetime],
    cascade: SemanticPlanningCascade,
    escalation_policy: SemanticPlanningEscalationPolicy | None,
    anchored_incident_plan_builder: Callable[..., OntologyQueryPlan | None],
    stated_value_filter_plan_builder: Callable[..., OntologyQueryPlan | None],
) -> PlanDispatchResult | SemanticPlanningOutcome:
    """Compile a verified read plan using the existing deterministic order."""

    evaluation_time = now()
    if evaluation_time.tzinfo is None:
        raise ValueError("semantic planning evaluation time MUST be timezone-aware")
    if frame.output_shape == SemanticOutputShape.CONTEXTUAL_RESOURCE_LIST:
        plan = (
            compile_contextual_resource_plan(
                frame=frame,
                utterance=utterance,
                descriptors=descriptors,
                manifest=manifest,
                verifier=verifier,
                evaluation_time=evaluation_time,
                purpose=purpose,
                bound_context=bound_resource_context,
            )
            if (
                bound_resource_context is not None
                and bound_resource_context.principal_id == principal.id
                and bound_resource_context.ontology_release_digest == manifest.release_digest
            )
            else None
        )
        if plan is None:
            plan_source = "proposed"
        else:
            plan_source = "server_contextual_resource"
    else:
        plan = None
    if frame.output_shape != SemanticOutputShape.CONTEXTUAL_RESOURCE_LIST:
        plan = anchored_incident_plan_builder(
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
        try:
            plan = compile_latency_recovery_plan(
                frame=frame,
                continuation=bound_investigation_continuation,
                manifest=manifest,
                verifier=verifier,
                evaluation_time=evaluation_time,
                purpose=purpose,
                available_metric_concepts=metric_concepts,
            )
        except LatencyRecoveryWindowPendingError:
            return _outcome(
                SemanticPlanningDisposition.UNAVAILABLE,
                "semantic_recovery_window_pending",
                manifest_digest=manifest.manifest_digest,
                frame=frame,
            )
        if plan is not None:
            plan_source = "server_latency_recovery"
    if plan is None:
        plan = compile_resource_target_candidates_plan(
            frame=frame,
            utterance=utterance,
            manifest=manifest,
            verifier=verifier,
            evaluation_time=evaluation_time,
            purpose=purpose,
        )
        if plan is not None:
            plan_source = "server_resource_target_candidates"
    if plan is None:
        plan = compile_kubernetes_pod_recovery_plan(
            frame=frame,
            investigation_intent=investigation_intent,
            manifest=manifest,
            verifier=verifier,
            evaluation_time=evaluation_time,
            purpose=purpose,
            available_metric_concepts=metric_concepts,
        )
        if plan is not None:
            plan_source = "server_kubernetes_pod_recovery"
    if plan is None:
        plan = compile_target_error_activity_plan(
            frame=frame,
            utterance=utterance,
            manifest=manifest,
            verifier=verifier,
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
            verifier=verifier,
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
            verifier=verifier,
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
            verifier=verifier,
            evaluation_time=evaluation_time,
            purpose=purpose,
            freshness_seconds=resource_freshness_seconds,
        )
        if plan is not None:
            plan_source = "server_target_current_state"
    if plan is None:
        plan = compile_service_health_plan(
            frame=frame,
            manifest=manifest,
            verifier=verifier,
            purpose=purpose,
        )
        if plan is not None:
            plan_source = "server_subscription_service_health"
    if plan is None:
        plan = compile_resource_event_plan(
            frame=frame,
            utterance=utterance,
            manifest=manifest,
            verifier=verifier,
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
            verifier=verifier,
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
            verifier=verifier,
            evaluation_time=evaluation_time,
            purpose=purpose,
            available_metric_concepts=metric_concepts,
        )
        if plan is not None:
            plan_source = "server_target_resource_metric_series"
    if plan is None:
        plan = compile_exact_resource_metric_plan(
            frame=frame,
            utterance=utterance,
            manifest=manifest,
            verifier=verifier,
            evaluation_time=evaluation_time,
            purpose=purpose,
            available_metric_concepts=metric_concepts,
        )
        if plan is not None:
            plan_source = "server_target_resource_metric"
    if plan is None:
        plan = compile_resource_metric_plan(
            frame=frame,
            utterance=utterance,
            manifest=manifest,
            verifier=verifier,
            evaluation_time=evaluation_time,
            purpose=purpose,
            available_metric_concepts=metric_concepts,
        )
        if plan is not None:
            plan_source = "server_resource_metric_inventory"
    if plan is None:
        plan = compile_resource_state_plan(
            frame=frame,
            utterance=utterance,
            manifest=manifest,
            verifier=verifier,
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
            verifier=verifier,
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
            verifier=verifier,
            evaluation_time=evaluation_time,
            purpose=purpose,
        )
        if plan is not None:
            plan_source = "server_target_impact"
    if plan is None:
        plan = compile_kubernetes_rollout_plan(
            frame=frame,
            investigation_intent=investigation_intent,
            manifest=manifest,
            verifier=verifier,
            evaluation_time=evaluation_time,
            purpose=purpose,
        )
        if plan is not None:
            plan_source = "server_kubernetes_rollout"
    if plan is None:
        plan = compile_mysql_pressure_plan(
            investigation_intent=investigation_intent,
            manifest=manifest,
            verifier=verifier,
            windows=_investigation_windows(
                evaluation_time,
                duration=investigation_window,
            ),
            purpose=purpose,
            problem_frame_digest=frame.frame_digest,
            available_metric_concepts=metric_concepts,
        )
        if plan is not None:
            plan_source = "server_mysql_pressure"
    if plan is None and investigation_intent is not None:
        try:
            plan = compile_investigation_plan(
                investigation_intent,
                manifest=manifest,
                verifier=verifier,
                windows=_investigation_windows(
                    evaluation_time,
                    duration=investigation_window,
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
        inventory_query_language=inventory_query_language,
    ):
        fallback = build_resource_target_candidates_fallback(
            utterance=utterance,
            context=context,
            descriptors=descriptors,
            confidence=proposal.confidence,
            inventory_query_language=inventory_query_language,
        )
        if fallback is not None:
            proposal, frame = fallback
            investigation_intent = None
            plan = compile_resource_target_candidates_plan(
                frame=frame,
                utterance=utterance,
                manifest=manifest,
                verifier=verifier,
                evaluation_time=evaluation_time,
                purpose=purpose,
            )
            if plan is not None:
                plan_source = "server_resource_target_candidates"
    if plan is None:
        plan = stated_value_filter_plan_builder(
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
        if frame.output_shape == SemanticOutputShape.CONTEXTUAL_RESOURCE_LIST:
            return _outcome(
                (
                    SemanticPlanningDisposition.CLARIFICATION
                    if bound_resource_context is None
                    else SemanticPlanningDisposition.UNAVAILABLE
                ),
                (
                    "contextual_resource_scope_required"
                    if bound_resource_context is None
                    else "contextual_resource_query_unavailable"
                ),
                manifest_digest=manifest.manifest_digest,
                frame=frame,
                clarification=(
                    "Select the screen or resource group to query."
                    if bound_resource_context is None
                    else None
                ),
            )
        plan = cascade.propose_plan(
            frame=frame,
            descriptors=descriptors,
            metric_concepts=metric_concepts,
            principal=principal,
            purpose=purpose,
            manifest=manifest,
            evaluation_time=evaluation_time,
            escalation_policy=escalation_policy,
        )
    if plan is None:
        if _is_temporal_comparison(frame):
            return _outcome(
                SemanticPlanningDisposition.UNAVAILABLE,
                "semantic_temporal_comparison_unavailable",
                manifest_digest=manifest.manifest_digest,
                frame=frame,
            )
        return _outcome(
            SemanticPlanningDisposition.UNSUPPORTED,
            "semantic_plan_unavailable",
            manifest_digest=manifest.manifest_digest,
            frame=frame,
        )
    if any(node.kind.value == "object_set" for node in plan.nodes):
        execution_time = now()
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
        verifier.verify(plan, manifest=manifest)
    return PlanDispatchResult(
        proposal=proposal,
        frame=frame,
        investigation_intent=investigation_intent,
        plan=plan,
        plan_source=plan_source,
    )


__all__ = ["PlanDispatchResult", "dispatch_semantic_plan"]

"""Schema-constrained semantic planning for ordinary-language read questions.

The model proposes meaning and typed nodes from the whole bounded turn. Core
rebuilds every identity, verifies the exact principal manifest, and grants no
execution authority. No phrase, regex, or keyword selects a query capability.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from functools import partial

from fdai_service_contracts.ontology_query import SemanticProblemFrame
from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentDisposition,
    SemanticJudgmentTier,
)
from fdai_service_contracts.semantic_turn import SemanticConversationModelTier
from pydantic import ValidationError

from fdai.core.ontology_platform import OntologyQueryPlanVerifier
from fdai.rule_catalog.schema.inventory_query_language import InventoryQueryLanguageRegistry

from .conversation_preflight import (
    ConversationPreflightResult,
    preflight_operational_judgment,
)
from .conversation_preflight_targets import (
    collection_summary_exact_target_requested,
    resource_catalog_constraints,
)
from .intent_graph import build_intent_graph
from .semantic_judgment import SemanticJudgmentBoundary, SemanticJudgmentObservation
from .semantic_planning_alignment import verify_frame_plan_alignment
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
    deterministic_pre_frame_selection,
    normalize_and_gate_frame,
)
from .semantic_planning_judgment import (
    _descriptors_for_judgment,
    _descriptors_for_operational_intent,
    _direct_response,
    _is_temporal_comparison,
    _JudgmentDecision,
    _operational_frame_matches_accepted_judgment,
    _safe_validation_reason,
    _semantic_judgment_capabilities,
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
    SemanticFrameProposal,
    SemanticOutputShape,
    SemanticPlanningDisposition,
    SemanticPlanningModel,
    SemanticPlanningOutcome,
)
from .semantic_planning_plan_dispatch import PlanDispatchResult, dispatch_semantic_plan
from .semantic_planning_preflight import (
    DIRECT_RESPONSE_PROFILE,
)
from .semantic_planning_preflight import (
    preflight_descriptor_intent as _preflight_descriptor_intent,
)
from .semantic_planning_preflight_router import PreflightDirectResponseRouter
from .semantic_planning_specialized_plans import (
    build_anchored_incident_plan,
    build_stated_value_filter_plan,
)
from .semantic_planning_support import (
    _MAX_DESCRIPTORS,
    _bounded_context,
    _build_plan,
    _outcome,
    _plan_node_summary,
    _validated_descriptors,
    _validated_metric_concepts,
)
from .semantic_resource_state_planning import resource_condition_intents_grounded
from .semantic_target_candidate_planning import build_stated_resource_filter_frame
from .semantic_test_context import test_context_capability, test_context_planning_outcome
from .session import Principal, Turn

_LOGGER = logging.getLogger(__name__)


_SAFE_UNACCEPTED_DESCRIPTOR_INTENTS = frozenset(
    {
        "query.gateway_diagnostic_evidence",
        "query.resource_configuration_changes",
        "query.resource_event_history",
    }
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
        locale: str = "en",
        bound_incident: BoundIncident | None = None,
        bound_resource_context: BoundResourceContext | None = None,
        bound_investigation_continuation: BoundInvestigationContinuation | None = None,
        escalation_policy: SemanticPlanningEscalationPolicy | None = None,
        conversation_model_tier: SemanticConversationModelTier | None = None,
        conversation_profile: Mapping[str, str] | None = None,
        preflight_result: ConversationPreflightResult | None = None,
        required_document_evidence: bool = False,
    ) -> SemanticPlanningOutcome:
        """Return a verified plan, one clarification, or a typed safe hold."""

        if not utterance.strip() or len(utterance) > 32_000:
            return _outcome(SemanticPlanningDisposition.UNSUPPORTED, "utterance_out_of_bounds")
        stage = "manifest"
        manifest_digest: str | None = None
        accepted_frame: SemanticProblemFrame | None = None
        model_observations: list[SemanticJudgmentObservation] = []
        response_profile = dict(DIRECT_RESPONSE_PROFILE)
        if conversation_profile is not None:
            response_profile["identity"] = conversation_profile["identity"]
            response_profile["role"] = conversation_profile["role"]
        unbound_conversation = bound_incident is None and bound_investigation_continuation is None
        preflight_router = PreflightDirectResponseRouter(
            semantic_judgment=self._semantic_judgment,
            utterance=utterance,
            locale=locale,
            response_profile=response_profile,
            unbound_conversation=unbound_conversation,
            supplied_preflight_result=preflight_result,
            model_observations=model_observations,
        )

        try:
            context = _bounded_context(prior_turns)
            preflight_outcome = preflight_router.run(context)
            if preflight_outcome is not None and not required_document_evidence:
                return preflight_router.finish(preflight_outcome)
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
            preflight_intent = _preflight_descriptor_intent(preflight_router.effective_result)
            promoted_preflight = (
                preflight_operational_judgment(
                    preflight_router.effective_result,
                    utterance=utterance,
                )
                if self._semantic_judgment is not None
                and preflight_router.effective_result is not None
                else None
            )
            if promoted_preflight is not None:
                stated_filter = build_stated_resource_filter_frame(
                    semantic_judgment=promoted_preflight.model_dump(mode="json"),
                    utterance=utterance,
                    context=context,
                    descriptors=descriptors,
                    inventory_query_language=self._inventory_query_language,
                )
                if stated_filter is not None:
                    stated_proposal, stated_frame = stated_filter
                    if stated_frame.unresolved_terms:
                        return preflight_router.finish(
                            _outcome(
                                SemanticPlanningDisposition.CLARIFICATION,
                                "semantic_clarification_required",
                                manifest_digest=manifest.manifest_digest,
                                frame=stated_frame,
                                clarification=stated_proposal.clarification,
                            )
                        )
            if preflight_intent is not None:
                descriptors = _descriptors_for_operational_intent(descriptors, preflight_intent)
                _LOGGER.info(
                    "semantic_preflight_descriptor_selection_completed",
                    extra={
                        "primary_intent": preflight_intent,
                        "descriptor_count": len(descriptors),
                    },
                )
            semantic_judgment = None
            judgment_decision: _JudgmentDecision | None = None
            if self._semantic_judgment is not None:
                judgment_capabilities = _semantic_judgment_capabilities(descriptors)
                judgment_capabilities = (*judgment_capabilities, test_context_capability())
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
                if promoted_preflight is not None:
                    _LOGGER.info(
                        "semantic_planning_judgment_reused_preflight",
                        extra={"primary_intent": promoted_preflight.primary_intent},
                    )
                    judgment_decision = _JudgmentDecision(
                        proposal=promoted_preflight,
                        disposition=SemanticJudgmentDisposition.ACCEPTED,
                        tier=SemanticJudgmentTier.T1,
                        accepted=True,
                    )
                else:
                    judgment_result = self._semantic_judgment.judge(
                        utterance=utterance,
                        context=context,
                        capabilities=judgment_capabilities,
                        allow_escalation=False,
                        bound_subject_types=bound_subject_types,
                        locale=locale,
                        direct_response_profile=response_profile,
                    )
                    context_outcome = test_context_planning_outcome(
                        judgment=judgment_result,
                        utterance=utterance,
                        locale=locale,
                        observations=tuple(model_observations),
                    )
                    if context_outcome is not None:
                        return context_outcome
                    judgment_decision = _JudgmentDecision(
                        proposal=judgment_result.proposal,
                        disposition=judgment_result.receipt.disposition,
                        tier=judgment_result.receipt.tier,
                        reason_code=getattr(judgment_result.receipt, "reason_code", None),
                        observations=judgment_result.observations,
                        accepted=judgment_result.accepted,
                    )
                model_observations.extend(judgment_decision.observations)
                if judgment_decision.reason_code in {
                    "semantic_judgment_review_conflict",
                    "semantic_judgment_review_unavailable",
                }:
                    return preflight_router.finish(
                        _outcome(
                            SemanticPlanningDisposition.UNAVAILABLE,
                            judgment_decision.reason_code,
                            manifest_digest=manifest.manifest_digest,
                            model_observations=tuple(model_observations),
                        )
                    )
                judgment_posture = (
                    judgment_decision.proposal.action_posture
                    if judgment_decision.proposal is not None
                    else judgment_decision.disposition.value
                )
                _LOGGER.info(
                    f"semantic_planning_judgment_{judgment_posture}",
                    extra={
                        "disposition": judgment_decision.disposition.value,
                        "tier": (
                            judgment_decision.tier.value
                            if judgment_decision.tier is not None
                            else None
                        ),
                        "action_posture": judgment_posture,
                        "primary_intent": (
                            judgment_decision.proposal.primary_intent
                            if judgment_decision.proposal is not None
                            else None
                        ),
                        "secondary_intents": (
                            ",".join(judgment_decision.proposal.secondary_intents)
                            if judgment_decision.proposal is not None
                            else ""
                        ),
                        "discourse_mode": (
                            judgment_decision.proposal.discourse_mode.value
                            if judgment_decision.proposal is not None
                            else None
                        ),
                        "requested_facets": (
                            ",".join(judgment_decision.proposal.requested_facets)
                            if judgment_decision.proposal is not None
                            else ""
                        ),
                        "target_count": (
                            len(judgment_decision.proposal.targets)
                            if judgment_decision.proposal is not None
                            else 0
                        ),
                        "target_kinds": (
                            ",".join(target.kind for target in judgment_decision.proposal.targets)
                            if judgment_decision.proposal is not None
                            else ""
                        ),
                        "canonical_target_types": (
                            ",".join(
                                sorted(
                                    {
                                        target.canonical_value
                                        for target in judgment_decision.proposal.targets
                                        if target.canonical_value is not None
                                    }
                                )
                            )
                            if judgment_decision.proposal is not None
                            else ""
                        ),
                    },
                )
                if judgment_decision.proposal is not None and (
                    judgment_decision.accepted
                    or judgment_decision.proposal.primary_intent
                    in _SAFE_UNACCEPTED_DESCRIPTOR_INTENTS
                ):
                    descriptors = _descriptors_for_judgment(
                        descriptors,
                        judgment_decision.proposal,
                    )
                    _LOGGER.info(
                        "semantic_descriptor_selection_completed",
                        extra={
                            "primary_intent": judgment_decision.proposal.primary_intent,
                            "descriptor_count": len(descriptors),
                            "descriptor_bytes": len(
                                json.dumps(
                                    descriptors,
                                    allow_nan=False,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                    sort_keys=True,
                                ).encode()
                            ),
                        },
                    )
                if judgment_decision.accepted and judgment_decision.proposal is not None:
                    semantic_judgment = judgment_decision.proposal.model_dump(mode="json")
            _LOGGER.info("semantic_planning_stage_completed", extra={"stage": stage})
            judgment_proposal = (
                judgment_decision.proposal if judgment_decision is not None else None
            )
            direct_response = _direct_response(
                judgment_decision.proposal
                if judgment_decision is not None
                and judgment_decision.accepted
                and judgment_decision.proposal is not None
                else None
            )
            if direct_response is not None and required_document_evidence:
                direct_response = None
                semantic_judgment = None
                judgment_proposal = None
            if direct_response is not None:
                if not preflight_router.ran:
                    preflight_outcome = preflight_router.run(context)
                    if preflight_outcome is not None:
                        return preflight_router.finish(preflight_outcome)
                if not preflight_router.vetoes_direct:
                    return preflight_router.finish(
                        _outcome(
                            SemanticPlanningDisposition.UNAVAILABLE,
                            "social_response_narrator_unavailable",
                        )
                    )
                _LOGGER.info(
                    "semantic_direct_response_blocked_by_preflight",
                    extra={"social_act": preflight_router.social_act.value},
                )
                semantic_judgment = None
                judgment_proposal = None
            pre_frame_outcome = deterministic_pre_frame_outcome(
                judgment=judgment_proposal,
                utterance=utterance,
                context=context,
                descriptors=descriptors,
                manifest_digest=manifest.manifest_digest,
                bound_incident=bound_incident is not None,
                judgment_accepted=(judgment_decision is not None and judgment_decision.accepted),
                locale=locale,
            )
            if pre_frame_outcome is not None:
                return preflight_router.finish(pre_frame_outcome)
            stage = "frame_proposal"
            frame_result = deterministic_pre_frame_selection(
                judgment=judgment_proposal,
                judgment_accepted=judgment_decision is not None and judgment_decision.accepted,
                utterance=utterance,
                context=context,
                descriptors=descriptors,
                manifest_descriptors=manifest.descriptors,
                inventory_query_language=self._inventory_query_language,
                bound_incident=bound_incident is not None,
            )
            if (
                frame_result is None
                and judgment_decision is not None
                and judgment_decision.accepted
                and judgment_proposal is not None
                and judgment_proposal.primary_intent == "query.resource_configuration_changes"
            ):
                return preflight_router.finish(
                    _outcome(
                        SemanticPlanningDisposition.UNAVAILABLE,
                        "semantic_configuration_frame_unavailable",
                        manifest_digest=manifest.manifest_digest,
                    )
                )
            if frame_result is None:
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
                    conversation_model_tier=conversation_model_tier,
                    observations=model_observations,
                )
            if frame_result is None:
                return preflight_router.finish(
                    _outcome(
                        SemanticPlanningDisposition.UNAVAILABLE,
                        "semantic_frame_unavailable",
                        manifest_digest=manifest.manifest_digest,
                    )
                )
            proposal, frame, investigation_intent = frame_result
            if not _operational_frame_matches_accepted_judgment(
                output_shape=frame.output_shape,
                judgment=judgment_proposal,
                judgment_accepted=(judgment_decision is not None and judgment_decision.accepted),
                judgment_evaluated=judgment_decision is not None,
                utterance=utterance,
                exact_resource_targeted=collection_summary_exact_target_requested(
                    utterance,
                    subject_constraints=frame.subject_constraints,
                    catalog_constraints=resource_catalog_constraints(descriptors),
                ),
                derived_resource_intents_grounded=resource_condition_intents_grounded(
                    utterance,
                    registry=self._inventory_query_language,
                    descriptors=descriptors,
                ),
            ):
                return preflight_router.finish(
                    _outcome(
                        SemanticPlanningDisposition.UNAVAILABLE,
                        "semantic_operational_judgment_required",
                        manifest_digest=manifest.manifest_digest,
                    )
                )
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
                judgment_accepted=(judgment_decision is not None and judgment_decision.accepted),
                utterance=utterance,
                context=context,
                descriptors=descriptors,
                manifest_digest=manifest.manifest_digest,
                bound_incident=bound_incident is not None,
                inventory_query_language=self._inventory_query_language,
                required_document_evidence=required_document_evidence,
            )
            if isinstance(normalized_frame, SemanticPlanningOutcome):
                return preflight_router.finish(normalized_frame)
            proposal, frame, investigation_intent = normalized_frame
            accepted_frame = frame
            lookback_seconds = frame.temporal_scope.get("lookback_seconds")
            normalized_measures = ",".join(sorted(frame.measure_concepts))
            temporal_keys = ",".join(sorted(frame.temporal_scope))
            temporal_kind = frame.temporal_scope.get("kind")
            lookback_value = frame.temporal_scope.get("lookback")
            window_value = frame.temporal_scope.get("window")
            bounded_lookback_seconds = (
                lookback_seconds
                if isinstance(lookback_seconds, int) and not isinstance(lookback_seconds, bool)
                else None
            )
            _LOGGER.info(
                "semantic_planning_frame_normalized output_shape=%s measure_concepts=%s "
                "temporal_keys=%s temporal_kind=%s lookback_seconds=%s "
                "lookback_type=%s lookback_keys=%s window_type=%s window_keys=%s "
                "clarification_count=%d",
                frame.output_shape,
                normalized_measures,
                temporal_keys,
                temporal_kind,
                bounded_lookback_seconds,
                type(lookback_value).__name__ if lookback_value is not None else None,
                (
                    ",".join(sorted(lookback_value))
                    if isinstance(lookback_value, dict)
                    and all(isinstance(key, str) for key in lookback_value)
                    else ""
                ),
                type(window_value).__name__ if window_value is not None else None,
                (
                    ",".join(sorted(window_value))
                    if isinstance(window_value, dict)
                    and all(isinstance(key, str) for key in window_value)
                    else ""
                ),
                len(proposal.clarification_requirements),
                extra={
                    "output_shape": frame.output_shape,
                    "measure_concepts": normalized_measures,
                    "temporal_keys": temporal_keys,
                    "temporal_kind": temporal_kind,
                    "lookback_seconds": bounded_lookback_seconds,
                    "clarification_count": len(proposal.clarification_requirements),
                },
            )
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
                conversation_model_tier=conversation_model_tier,
                model_observations=model_observations,
                anchored_incident_plan_builder=partial(
                    build_anchored_incident_plan,
                    verifier=self._verifier,
                ),
                stated_value_filter_plan_builder=partial(
                    build_stated_value_filter_plan,
                    verifier=self._verifier,
                ),
            )
            if isinstance(dispatched, SemanticPlanningOutcome):
                return preflight_router.finish(dispatched)
            dispatch_result: PlanDispatchResult = dispatched
            proposal = dispatch_result.proposal
            frame = dispatch_result.frame
            investigation_intent = dispatch_result.investigation_intent
            plan = dispatch_result.plan
            plan_source = dispatch_result.plan_source
            if frame.output_shape == SemanticOutputShape.PROPERTY_FILTERED_RESOURCES:
                verify_frame_plan_alignment(
                    frame,
                    plan,
                    descriptors=manifest.descriptors,
                    allow_bound_contextual=bound_resource_context is not None,
                )
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
            return preflight_router.finish(
                _outcome(
                    SemanticPlanningDisposition.PLANNED,
                    "semantic_plan_verified",
                    manifest_digest=manifest.manifest_digest,
                    frame=frame,
                    plan=plan,
                    intent_graph=graph,
                    investigation_intent=investigation_intent,
                )
            )
        except PermissionError:
            return preflight_router.finish(
                _outcome(
                    SemanticPlanningDisposition.UNSUPPORTED,
                    "semantic_scope_denied",
                )
            )
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
            return preflight_router.finish(
                _outcome(
                    disposition,
                    reason,
                    manifest_digest=manifest_digest,
                    frame=accepted_frame,
                )
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
            return preflight_router.finish(
                _outcome(
                    disposition,
                    reason,
                    manifest_digest=manifest_digest,
                    frame=accepted_frame,
                )
            )
        except Exception:  # noqa: BLE001 - model/provider details never cross the boundary
            _LOGGER.exception(
                "semantic_planning_failed",
                extra={"principal_role": principal.role.value, "purpose": purpose},
            )
            return preflight_router.finish(
                _outcome(
                    SemanticPlanningDisposition.UNAVAILABLE,
                    "semantic_planning_failed",
                )
            )

    def preflight(
        self,
        *,
        utterance: str,
        prior_turns: Sequence[Turn],
        locale: str,
        conversation_profile: Mapping[str, str] | None = None,
        cancelled: asyncio.Event | None = None,
        conversation_model_tier: SemanticConversationModelTier | None = None,
    ) -> ConversationPreflightResult:
        """Classify routing before the optional adaptive explanation path."""
        if self._semantic_judgment is None:
            return ConversationPreflightResult(proposal=None)
        response_profile = dict(DIRECT_RESPONSE_PROFILE)
        if conversation_profile is not None:
            response_profile["identity"] = conversation_profile["identity"]
            response_profile["role"] = conversation_profile["role"]
        return self._semantic_judgment.preflight(
            utterance=utterance,
            context=_bounded_context(prior_turns),
            locale=locale,
            direct_response_profile=response_profile,
            cancelled=cancelled,
            conversation_model_tier=conversation_model_tier,
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

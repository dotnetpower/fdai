"""Schema-constrained semantic planning for ordinary-language read questions.

The model proposes meaning and typed nodes from the whole bounded turn. Core
rebuilds every identity, verifies the exact principal manifest, and grants no
execution authority. No phrase, regex, or keyword selects a query capability.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from fdai_service_contracts.ontology_query import (
    SemanticOperation,
    SemanticProblemFrame,
)
from fdai_service_contracts.semantic_judgment import (
    SemanticDiscourseMode,
    SemanticJudgmentDisposition,
    SemanticJudgmentProposal,
    SemanticJudgmentTier,
)
from pydantic import ValidationError

from fdai.core.ontology_platform import OntologyQueryPlanVerifier
from fdai.rule_catalog.schema.inventory_query_language import InventoryQueryLanguageRegistry

from .conversation_preflight import (
    DIRECT_SOCIAL_ACTS,
    ContextDependency,
    ConversationPreflightResult,
    OperationalSignal,
    SocialAct,
    preflight_operational_judgment,
)
from .intent_graph import build_intent_graph
from .semantic_judgment import SemanticJudgmentBoundary, SemanticJudgmentObservation
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
from .session import Principal, Turn

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _JudgmentDecision:
    proposal: SemanticJudgmentProposal | None
    disposition: SemanticJudgmentDisposition
    tier: SemanticJudgmentTier | None
    observations: tuple[SemanticJudgmentObservation, ...] = ()
    accepted: bool = False


_OPERATIONAL_DESCRIPTOR_NAMES = {
    "create.document": frozenset({"Resource"}),
    "query.resource_configuration_changes": frozenset(
        {
            "Resource",
            "query.resource_configuration_changes",
            "query.resource_configuration_snapshot",
        }
    ),
    "query.gateway_diagnostic_evidence": frozenset(
        {
            "Resource",
            "routes_to",
            "query.gateway_diagnostic_evidence",
            "query.resource_configuration_changes",
            "query.resource_configuration_snapshot",
        }
    ),
}

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
        "ontology relationship endpoints must exist in the principal manifest",
        "query node arguments do not match the closed schema",
    }
)

_DIRECT_RESPONSE_FACETS = {
    SemanticDirectResponseIntent.GREETING: frozenset(),
    SemanticDirectResponseIntent.SELF_INTRODUCTION: frozenset(
        {"identity", "role", "capabilities", "authority", "authority_boundary"}
    ),
}
_DIRECT_RESPONSE_PROFILE = {
    "schema_version": "1.0.0",
    "identity": "Bragi",
    "product": "FDAI Console",
    "role": "read-only conversation interface",
    "voice": ("calm", "precise", "respectful", "evidence-first"),
    "interaction_style": (
        "acknowledge conversation continuity",
        "offer a concise operationally relevant next step",
        "avoid repeating a full self-introduction",
    ),
    "capabilities": (
        "explain current-screen and operational information from verified evidence",
        "prepare bounded requests for FDAI governed paths",
    ),
    "authority_boundaries": (
        "does not execute managed-resource changes",
        "does not approve its own requests",
        "does not claim verification without evidence",
    ),
}
_PREFLIGHT_DIRECT_CONFIDENCE = 0.9


def _direct_response(
    proposal: SemanticJudgmentProposal | None,
) -> tuple[SemanticDirectResponseIntent, str] | None:
    """Validate one canonical direct-answer intent selected by semantic judgment."""

    if (
        proposal is None
        or proposal.discourse_mode is not SemanticDiscourseMode.DIRECT
        or proposal.secondary_intents
        or proposal.targets
        or proposal.direct_response is None
    ):
        return None
    try:
        intent = SemanticDirectResponseIntent(proposal.primary_intent)
    except ValueError:
        return None
    if not set(proposal.requested_facets).issubset(_DIRECT_RESPONSE_FACETS[intent]):
        return None
    return intent, proposal.direct_response.answer


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
        locale: str = "en",
        bound_incident: BoundIncident | None = None,
        bound_resource_context: BoundResourceContext | None = None,
        bound_investigation_continuation: BoundInvestigationContinuation | None = None,
        escalation_policy: SemanticPlanningEscalationPolicy | None = None,
        conversation_profile: Mapping[str, str] | None = None,
        preflight_result: ConversationPreflightResult | None = None,
    ) -> SemanticPlanningOutcome:
        """Return a verified plan, one clarification, or a typed safe hold."""

        if not utterance.strip() or len(utterance) > 32_000:
            return _outcome(SemanticPlanningDisposition.UNSUPPORTED, "utterance_out_of_bounds")
        stage = "manifest"
        manifest_digest: str | None = None
        accepted_frame: SemanticProblemFrame | None = None
        model_observations: list[SemanticJudgmentObservation] = []
        preflight_social_act = SocialAct.NONE
        preflight_vetoes_direct = False
        preflight_ran = False
        response_profile = dict(_DIRECT_RESPONSE_PROFILE)
        if conversation_profile is not None:
            response_profile["identity"] = conversation_profile["identity"]
            response_profile["role"] = conversation_profile["role"]
        unbound_conversation = bound_incident is None and bound_investigation_continuation is None
        supplied_preflight_consumed = False
        effective_preflight_result: ConversationPreflightResult | None = None

        def finish(outcome: SemanticPlanningOutcome) -> SemanticPlanningOutcome:
            updated = outcome
            recorded_observations = tuple(model_observations)
            if recorded_observations and outcome.model_observations != recorded_observations:
                updated = replace(updated, model_observations=recorded_observations)
            if updated.social_act is not preflight_social_act:
                updated = replace(updated, social_act=preflight_social_act)
            return updated

        def run_preflight(context: Sequence[str]) -> SemanticPlanningOutcome | None:
            nonlocal preflight_ran, preflight_social_act, preflight_vetoes_direct
            nonlocal effective_preflight_result, supplied_preflight_consumed
            if self._semantic_judgment is None:
                return None
            preflight_ran = True
            if preflight_result is not None and not supplied_preflight_consumed:
                preflight = preflight_result
                supplied_preflight_consumed = True
            else:
                preflight = self._semantic_judgment.preflight(
                    utterance=utterance,
                    context=context,
                    locale=locale,
                    direct_response_profile=response_profile,
                )
            effective_preflight_result = preflight
            model_observations.extend(preflight.observations)
            preflight_vetoes_direct = preflight.failure_kind == "malformed"
            proposal = preflight.proposal
            if proposal is None:
                return None
            preflight_vetoes_direct = (
                proposal.social_act is SocialAct.ACKNOWLEDGEMENT
                or proposal.operational_signal is not OperationalSignal.NONE
                or proposal.context_dependency
                not in {ContextDependency.NONE, ContextDependency.SOCIAL_CONTINUITY}
            )
            preflight_social_act = proposal.social_act
            direct_intent = (
                SemanticDirectResponseIntent.SELF_INTRODUCTION
                if proposal.social_act is SocialAct.SELF_INTRODUCTION
                else SemanticDirectResponseIntent.GREETING
                if proposal.social_act in DIRECT_SOCIAL_ACTS
                else None
            )
            if (
                direct_intent is None
                or proposal.confidence < _PREFLIGHT_DIRECT_CONFIDENCE
                or proposal.operational_signal is not OperationalSignal.NONE
                or proposal.context_dependency
                not in {ContextDependency.NONE, ContextDependency.SOCIAL_CONTINUITY}
                or not unbound_conversation
            ):
                return None
            narrated = self._semantic_judgment.narrate_social(
                utterance=utterance,
                locale=locale,
                social_act=proposal.social_act,
                continued=proposal.context_dependency is ContextDependency.SOCIAL_CONTINUITY,
                direct_response_profile=response_profile,
            )
            model_observations.extend(narrated.observations)
            response = narrated.draft
            if response is None:
                return _outcome(
                    SemanticPlanningDisposition.UNAVAILABLE,
                    "social_response_narrator_unavailable",
                    social_act=proposal.social_act,
                )
            return _outcome(
                SemanticPlanningDisposition.DIRECT_RESPONSE,
                "conversation_preflight_direct_response",
                direct_response_intent=direct_intent,
                direct_response_answer=response.answer,
                social_act=proposal.social_act,
            )

        try:
            context = _bounded_context(prior_turns)
            preflight_outcome = run_preflight(context)
            if preflight_outcome is not None:
                return finish(preflight_outcome)
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
            semantic_judgment = None
            judgment_decision: _JudgmentDecision | None = None
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
                promoted_preflight = (
                    preflight_operational_judgment(
                        effective_preflight_result,
                        utterance=utterance,
                    )
                    if effective_preflight_result is not None
                    else None
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
                    judgment_decision = _JudgmentDecision(
                        proposal=judgment_result.proposal,
                        disposition=judgment_result.receipt.disposition,
                        tier=judgment_result.receipt.tier,
                        observations=judgment_result.observations,
                        accepted=judgment_result.accepted,
                    )
                model_observations.extend(judgment_decision.observations)
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
                if judgment_decision.accepted and judgment_decision.proposal is not None:
                    semantic_judgment = judgment_decision.proposal.model_dump(mode="json")
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
            if direct_response is not None:
                if not preflight_ran:
                    preflight_outcome = run_preflight(context)
                    if preflight_outcome is not None:
                        return finish(preflight_outcome)
                if not preflight_vetoes_direct:
                    return finish(
                        _outcome(
                            SemanticPlanningDisposition.UNAVAILABLE,
                            "social_response_narrator_unavailable",
                        )
                    )
                _LOGGER.info(
                    "semantic_direct_response_blocked_by_preflight",
                    extra={"social_act": preflight_social_act.value},
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
            )
            if pre_frame_outcome is not None:
                return finish(pre_frame_outcome)
            stage = "frame_proposal"
            frame_result = deterministic_pre_frame_selection(
                judgment=judgment_proposal,
                judgment_accepted=judgment_decision is not None and judgment_decision.accepted,
                utterance=utterance,
                context=context,
                descriptors=descriptors,
                manifest_descriptors=manifest.descriptors,
                inventory_query_language=self._inventory_query_language,
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
                    observations=model_observations,
                )
            if frame_result is None:
                return finish(
                    _outcome(
                        SemanticPlanningDisposition.UNAVAILABLE,
                        "semantic_frame_unavailable",
                        manifest_digest=manifest.manifest_digest,
                    )
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
                return finish(normalized_frame)
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
                return finish(dispatched)
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
            return finish(
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
            return finish(
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
            return finish(
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
            return finish(
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
            return finish(
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
    ) -> ConversationPreflightResult:
        """Classify routing before the optional adaptive explanation path."""
        if self._semantic_judgment is None:
            return ConversationPreflightResult(proposal=None)
        response_profile = dict(_DIRECT_RESPONSE_PROFILE)
        if conversation_profile is not None:
            response_profile["identity"] = conversation_profile["identity"]
            response_profile["role"] = conversation_profile["role"]
        return self._semantic_judgment.preflight(
            utterance=utterance,
            context=_bounded_context(prior_turns),
            locale=locale,
            direct_response_profile=response_profile,
        )


def _descriptors_for_judgment(
    descriptors: tuple[dict[str, Any], ...],
    judgment: SemanticJudgmentProposal,
) -> tuple[dict[str, Any], ...]:
    """Narrow known operational families after model-backed intent classification."""
    required = _OPERATIONAL_DESCRIPTOR_NAMES.get(judgment.primary_intent)
    if required is None:
        return descriptors
    selected = tuple(descriptor for descriptor in descriptors if descriptor.get("name") in required)
    selected_names = {descriptor.get("name") for descriptor in selected}
    if not required <= selected_names:
        return descriptors
    return selected


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

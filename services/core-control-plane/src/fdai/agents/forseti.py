"""Forseti owns typed judgment, cross-domain arbitration and bounded planning.

Evidence, current policy and RBAC govern verdicts; planning never grants execution authority.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.incident_intervention import INCIDENT_INTERVENTION_EVENT_TYPE

from fdai.agents._framework.action_semantics import (
    ActionSemanticsCatalog,
)
from fdai.agents._framework.alert_noise_callbacks import ForsetiAlertNoiseMixin
from fdai.agents._framework.anomaly_action import AnomalyActionSource
from fdai.agents._framework.assignment_workflow import AssignmentJudgmentMixin
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.cross_vertical_candidates import (
    CrossVerticalCandidateAccumulator,
    is_cross_vertical_candidate,
)
from fdai.agents._framework.forseti_arbitration import (
    _MAX_RESOURCES,
    ForsetiArbitrationMixin,
    _DecisionProjection,
)
from fdai.agents._framework.forseti_decision_helpers import (
    ChangeAssessor,
)
from fdai.agents._framework.forseti_judgment import RISK_VERDICT as _RISK_VERDICT
from fdai.agents._framework.forseti_judgment import RULE_MATCH as _RULE_MATCH
from fdai.agents._framework.forseti_judgment import ForsetiJudgmentMixin
from fdai.agents._framework.forseti_telemetry_introspection import telemetry_recipe_facts
from fdai.agents._framework.handover_knowledge import HandoverKnowledgeMixin
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    attach_agent_state_evidence,
    capability_facts,
    evidence_backed_result,
    mentioned,
    semantic_intents,
)
from fdai.agents._framework.pantheon import _FORSETI
from fdai.agents._framework.role_answers import forseti_role_answer
from fdai.agents._framework.specialist_ingress import SPECIALIST_EVENT_PREFIX
from fdai.core.architecture_review import (
    ArchitectureReviewObservation,
    OntologyArchitectureReviewLoop,
)
from fdai.core.capacity import (
    CapacityGraduationRecommendation,
    GraduationRecommendationStatus,
)
from fdai.core.decision_case import (
    DomainDecisionCoordinator,
)
from fdai.core.impact_analysis import (
    ChangeGraphEvidenceReceipt,
    change_graph_evidence_from_snapshot,
)
from fdai.core.operational_context import OperationalContextMaterializer
from fdai.core.operational_context.test_context import TestContextSource
from fdai.core.operational_planning import (
    KineticActionProposalSource,
    SpecialistPlanningCoordinator,
)
from fdai.core.operational_planning.prospective_lineage import (
    ProspectiveLineageFinalizer,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Deterministic tables (wave 3 defaults)
# ---------------------------------------------------------------------------

# ``event_type -> proposed ActionType id`` (rule match). Wave 3 uses a
# tiny in-memory table; real T0 loader consumes rule catalog YAML.
# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

# An absent deployment policy grants no operator authority. Tests and composition
# roots that need an allowed principal inject an explicit mapping.
_DEFAULT_RBAC: dict[str, frozenset[str]] = {}

# LRU cap on the per-resource domain-advice maps, so a long-lived judge that
# sees advice for many resources without a conflict cannot leak memory.


# The topic whose single owner is the pantheon's arbitration authority.
# Resolved from the registry so the fail-closed path can never name a
# second arbiter or drift from the fixed pantheon.


class Forseti(
    Agent,
    ForsetiJudgmentMixin,
    ForsetiArbitrationMixin,
    HandoverKnowledgeMixin,
    AssignmentJudgmentMixin,
    ForsetiAlertNoiseMixin,
):
    """Wave-3 Forseti: rule match + risk verdict + RBAC + SecurityEvent."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        rbac: dict[str, frozenset[str]] | None = None,
        action_semantics: ActionSemanticsCatalog | None = None,
        operational_context: OperationalContextMaterializer | None = None,
        test_context_source: TestContextSource | None = None,
        test_context_admission: DecisionEvidenceAdmissionProvider | None = None,
        test_context_clock: Callable[[], datetime] | None = None,
        decision_coordinator: DomainDecisionCoordinator | None = None,
        operational_planner: SpecialistPlanningCoordinator | None = None,
        kinetic_proposal_source: KineticActionProposalSource | None = None,
        prospective_lineage_finalizer: ProspectiveLineageFinalizer | None = None,
        change_assessor: ChangeAssessor | None = None,
        architecture_review_loop: OntologyArchitectureReviewLoop | None = None,
        agent_availability: Callable[[], Iterable[str]] | None = None,
        cross_vertical_timeout_seconds: float = 30.0,
        anomaly_action_sources: Mapping[str, AnomalyActionSource] | None = None,
    ) -> None:
        if cross_vertical_timeout_seconds <= 0.0 or cross_vertical_timeout_seconds > 300.0:
            raise ValueError("cross_vertical_timeout_seconds MUST be in (0, 300]")
        super().__init__(spec=_FORSETI)
        self.bus = bus
        self.initialize_assignment_checks()
        self._rbac = rbac if rbac is not None else _DEFAULT_RBAC
        self._action_semantics = action_semantics
        self._operational_context = operational_context
        self._test_context_source = test_context_source
        self._test_context_admission = test_context_admission
        self._test_context_clock = test_context_clock or (lambda: datetime.now(tz=UTC))
        self._decision_coordinator = decision_coordinator or DomainDecisionCoordinator()
        self._operational_planner = operational_planner
        self._kinetic_proposal_source = kinetic_proposal_source
        self._prospective_lineage_finalizer = prospective_lineage_finalizer
        self._change_assessor = change_assessor
        self._anomaly_action_sources = dict(anomaly_action_sources or {})
        if len(self._anomaly_action_sources) > 32 or any(
            not key or key != key.strip() or len(key) > 128 for key in self._anomaly_action_sources
        ):
            raise ValueError("anomaly action bindings must contain bounded exact signal names")
        self._architecture_review_loop = architecture_review_loop
        # Optional runtime probe; an absent probe never invents agent unavailability.
        self._agent_availability = agent_availability
        self._cross_vertical_timeout_seconds = cross_vertical_timeout_seconds
        self._cross_vertical_candidates = CrossVerticalCandidateAccumulator(
            max_pending=_MAX_RESOURCES
        )
        self._cross_vertical_timeout_tasks: dict[str, asyncio.Task[None]] = {}
        self._pending_arbitration_principals: BoundedLruDict[str, dict[str, str]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        # Latest arbitration winner per correlation id (populated when Odin
        # resolves a cross-vertical conflict Forseti raised).
        self.arbitrations: dict[str, str] = {}
        # Correlations whose arbitration Odin flagged as too close to settle
        # (near-tie, unknown domain, non-finite impact). They gate the
        # verdict to HIL; cleared once a human-visible verdict is issued.
        self._unresolved_arbitrations: BoundedLruDict[str, dict[str, Any]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        # Resource id per arbitration request, so the escalation verdict can
        # name the resource a human must look at. Odin's decision carries the
        # correlation but not the resource.
        self._arbitration_resources: BoundedLruDict[str, str] = BoundedLruDict(_MAX_RESOURCES)
        # Bounded advice joins cost/capacity signals per resource for conflict arbitration.
        self._domain_advice: BoundedLruDict[str, dict[str, str]] = BoundedLruDict(_MAX_RESOURCES)
        # Measured [0,1] domain impacts let Odin weigh magnitude instead of priority alone.
        self._domain_impact: BoundedLruDict[str, dict[str, float]] = BoundedLruDict(_MAX_RESOURCES)
        self._domain_observed_at: BoundedLruDict[str, str] = BoundedLruDict(_MAX_RESOURCES)
        self._domain_arguments: BoundedLruDict[str, dict[str, dict[str, object]]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        self._pending_decision_cases: BoundedLruDict[str, _DecisionProjection] = BoundedLruDict(
            _MAX_RESOURCES
        )
        self._pending_change_assessments: BoundedLruDict[str, dict[str, Any]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        self._detection_readiness: BoundedLruDict[str, dict[str, str]] = BoundedLruDict(
            _MAX_RESOURCES
        )

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    def bind_agent_availability(self, probe: Callable[[], Iterable[str]]) -> None:
        """Bind the runtime health probe that reports unreachable agents."""
        self._agent_availability = probe

    # ---- typed port ----------------------------------------------------

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if await self._handover_message(topic, payload):
            return
        if await self._assignment_message(topic, payload):
            return
        if await self._alert_noise_message(topic, payload):
            return
        if is_cross_vertical_candidate(topic, payload):
            await self._ingest_cross_vertical_candidate(topic, payload)
            return
        if topic == "object.change":
            await self._observe_architecture_change(payload)
            return
        if (
            topic == "object.event"
            and payload.get("event_type") == INCIDENT_INTERVENTION_EVENT_TYPE
        ):
            if payload.get("producer_principal") != "Huginn":
                raise ValueError("incident guidance requires the Huginn-owned normalized Event")
            self.record_behavior("incident_guidance:deferred")
            return
        if topic == "object.event" and str(payload.get("event_type") or "").startswith(
            "control_plane.t2_proposer_"
        ):
            self.record_behavior("t2_proposer_observation:deferred")
            return
        if topic == "object.event" and str(payload.get("event_type") or "").startswith(
            SPECIALIST_EVENT_PREFIX
        ):
            self.record_behavior("specialist_signal:deferred")
            return
        if topic == "object.event" and payload.get("event_type") == (
            "detection.readiness.observed"
        ):
            self.record_behavior("detection_readiness:observation_deferred")
            return
        if topic == "object.drift" and payload.get("kind") == "detection_readiness":
            self._record_detection_readiness(payload)
            return
        if payload.get("kind") == "document_ingestion":
            if topic == "object.event" and payload.get("event_type") == "document.received":
                await self.judge_document_ingestion(payload)
            elif topic == "object.anomaly" and payload.get("stage") == "protection_check":
                await self.judge_document_safety(payload)
            return
        if topic in ("object.event", "object.anomaly", "object.drift", "object.forecast"):
            if topic == "object.event":
                await self._attach_change_assessment(payload)
            arbitration = await self.maybe_request_arbitration(payload)
            if arbitration is not None:
                return
            await self.judge(payload)
        elif topic == "object.cost-anomaly":
            await self._ingest_domain_signal("cost", payload)
        elif topic == "object.capacity-forecast":
            await self._ingest_domain_signal("capacity", payload)
        elif topic == "object.capacity-graduation-recommendation":
            await self._judge_capacity_graduation(payload)
        elif topic == "object.arbitration-decision":
            await self._record_arbitration(payload)

    async def _judge_capacity_graduation(self, payload: dict[str, Any]) -> None:
        """Issue one observation-only verdict over Freyr's shadow recommendation."""

        try:
            recommendation = CapacityGraduationRecommendation.model_validate(
                {
                    field: payload[field]
                    for field in CapacityGraduationRecommendation.model_fields
                    if field in payload
                }
            )
        except (KeyError, ValueError):
            self.record_behavior("capacity_graduation:invalid")
            return
        accepted = recommendation.status is GraduationRecommendationStatus.RECOMMEND
        verdict = {
            "kind": "capacity_graduation",
            "producer_principal": "Forseti",
            "correlation_id": str(payload.get("correlation_id") or ""),
            "idempotency_key": f"verdict:{recommendation.id}",
            "resource_id": recommendation.target_ref,
            "recommendation_id": recommendation.id,
            "transition": recommendation.transition.value,
            "target_profile": recommendation.target_profile,
            "risk_verdict": "shadow" if accepted else "deny",
            "reason": "recommendation_accepted" if accepted else "recommendation_held",
            "reason_codes": list(recommendation.reason_codes),
            "shadow_only": True,
            "execution_authority": False,
        }
        self.record_behavior("capacity_graduation:" + ("accepted" if accepted else "held"))
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.verdict", verdict)

    async def _observe_architecture_change(self, payload: dict[str, Any]) -> None:
        """Judge one planned Change through the observation-only ARB seam."""

        if self._architecture_review_loop is None:
            return
        try:
            observation = await self._architecture_review_loop.evaluate(payload)
        except Exception as exc:  # noqa: BLE001 - fail closed and audit the hold
            self.record_behavior("architecture_review:failed")
            observation = ArchitectureReviewObservation.hold(
                change_id=str(payload.get("id") or payload.get("event_id") or "unknown"),
                idempotency_key=str(payload.get("idempotency_key") or "unknown"),
                correlation_id=str(payload.get("correlation_id") or "unknown"),
                target_ref=str(payload.get("target_ref") or "unknown"),
                change_digest="unknown",
                reason=f"observation_review_failed:{type(exc).__name__}",
            )
        if observation.replayed:
            self.record_behavior("architecture_review:duplicate")
            return
        self.record_behavior(f"architecture_review:{observation.recommendation}")
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.verdict", observation.to_mapping())

    async def _attach_change_assessment(self, event: dict[str, Any]) -> None:
        change = event.get("normalized_change")
        if not isinstance(change, Mapping) or change.get("intent_kind") != "planned":
            return
        if self._change_assessor is None:
            event["change_assessment_status"] = "unavailable"
            event["human_approval_required"] = True
            self.record_behavior("change_assessment:unavailable")
            return
        try:
            graph_evidence = await self._planned_change_graph_evidence(change)
            assessment = await self._change_assessor.assess(
                change,
                graph_evidence=graph_evidence,
            )
        except Exception:  # noqa: BLE001 - missing impact evidence lowers authority
            event["change_assessment_status"] = "failed"
            event["human_approval_required"] = True
            self.record_behavior("change_assessment:failed")
            return
        event["change_assessment_status"] = "review" if assessment.review_required else "clear"
        event["change_assessment"] = assessment.to_mapping()
        if assessment.review_required:
            event["human_approval_required"] = True
        self.record_behavior(f"change_assessment:{event['change_assessment_status']}")

    async def _planned_change_graph_evidence(
        self,
        change: Mapping[str, Any],
    ) -> ChangeGraphEvidenceReceipt:
        expected_release = str(change.get("ontology_release_digest") or "").strip()
        if self._operational_context is None or not expected_release:
            return ChangeGraphEvidenceReceipt.unavailable()
        occurred_at = datetime.fromisoformat(
            str(change.get("occurred_at") or "").replace("Z", "+00:00")
        )
        if occurred_at.tzinfo is None:
            raise ValueError("planned change occurred_at MUST be timezone-aware")
        snapshot = await self._operational_context.materialize(
            target_resource_id=str(change.get("target_ref") or ""),
            cutoff=occurred_at,
            catalog_versions=None,
            require_verified_links=True,
        )
        return change_graph_evidence_from_snapshot(
            snapshot,
            expected_ontology_release=expected_release,
        )

    # ---- cross-vertical arbitration -----------------------------------

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Report whether any judged runtime state backs this turn.
        The risk table and rule matches are configuration. Answering "why
        was this denied" from them alone presents a default as if it were
        a decision, so the turn is grounded only once an arbitration, a
        readiness ceiling, or an unresolved conflict has been recorded.
        """
        return bool(self.arbitrations or self._detection_readiness or self._unresolved_arbitrations)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            **telemetry_recipe_facts(),
            "known_action_verdicts": dict(_RISK_VERDICT),
            "rule_matches": dict(_RULE_MATCH),
            "arbitrations_recorded": len(self.arbitrations),
            # Both gates that force an otherwise-auto verdict to human
            # review. The charter tells Forseti to report them as exactly
            # that, so they MUST be readable through the judgment tool.
            "unresolved_arbitrations": len(self._unresolved_arbitrations),
            "readiness_limited_resources": len(self._detection_readiness),
            "rca_evidence_available": False,
        }
        if "rca_evidence" in semantic_intents(context):
            statement = "No grounded RCA record is retained by this conversational projection"
            return evidence_backed_result(self.spec.name, facts, statement)
        actions = mentioned(question, _RISK_VERDICT)
        if actions:
            action = actions[0]
            verdict = _RISK_VERDICT[action]
            facts.update({"action_type": action, "risk_verdict": verdict})
            statement = f"Action {action!r} has configured default risk verdict {verdict!r}"
            return evidence_backed_result(self.spec.name, facts, statement)
        evidence_ref = attach_agent_state_evidence(self.spec.name, facts)
        answer = forseti_role_answer(str(context.get("locale")), facts, evidence_ref)
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Forseti"]

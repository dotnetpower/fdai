"""Forseti owns typed judgment, cross-domain arbitration and bounded planning.

Evidence, current policy and RBAC govern verdicts; planning never grants execution authority.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from weakref import WeakValueDictionary

from fdai_service_contracts.incident_intervention import INCIDENT_INTERVENTION_EVENT_TYPE

from fdai.agents._framework import forseti_durability
from fdai.agents._framework.action_semantics import (
    ActionSemanticsCatalog,
)
from fdai.agents._framework.alert_noise_callbacks import ForsetiAlertNoiseMixin
from fdai.agents._framework.anomaly_action import AnomalyActionSource
from fdai.agents._framework.assignment_workflow import AssignmentJudgmentMixin
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
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
from fdai.agents._framework.forseti_development_authority import (
    ForsetiDevelopmentAuthorityMixin,
)
from fdai.agents._framework.forseti_judgment import (
    DEFAULT_JUDGMENT_TABLE,
    ForsetiJudgmentMixin,
    JudgmentTable,
)
from fdai.agents._framework.forseti_telemetry_introspection import telemetry_recipe_facts
from fdai.agents._framework.forseti_what_if import (
    MAX_WHAT_IF_SAMPLES,
    build_what_if_batch,
    judgment_table_from_request,
)
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
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.role_answers import forseti_role_answer
from fdai.agents._framework.specialist_ingress import SPECIALIST_EVENT_PREFIX
from fdai.agents._framework.topics import stable_idempotency_key
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
from fdai.core.operational_context import OperationalContextMaterializer, SourceFreshness
from fdai.core.operational_context.test_context import TestContextSource
from fdai.core.operational_planning import (
    KineticActionProposalSource,
    SpecialistPlanningCoordinator,
)
from fdai.core.operational_planning.prospective_lineage import (
    ProspectiveLineageFinalizer,
)
from fdai.shared.contracts.models import (
    FullAuthorityDevelopmentProfile,
    RegisteredDevelopmentAction,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.development_authority import DevelopmentAuthorityBindingSource
from fdai.shared.providers.state_store import StateStore

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
_DEFAULT_RULE_STALENESS_WINDOW = timedelta(hours=1)
_QUALITY_SAMPLE_LIMIT = 512

# LRU cap on the per-resource domain-advice maps, so a long-lived judge that
# sees advice for many resources without a conflict cannot leak memory.


# The topic whose single owner is the pantheon's arbitration authority.
# Resolved from the registry so the fail-closed path can never name a
# second arbiter or drift from the fixed pantheon.


def _ratio_kpi(numerator: int, denominator: int, *, unit: str = "ratio") -> dict[str, object]:
    if denominator <= 0:
        return {
            "value": None,
            "evidence_state": "insufficient_sample",
            "numerator": numerator,
            "denominator": denominator,
            "unit": unit,
        }
    return {
        "value": numerator / denominator,
        "evidence_state": "measured",
        "numerator": numerator,
        "denominator": denominator,
        "unit": unit,
    }


def _rule_revision(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _rule_updated_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return None
    return timestamp


def _rule_state_is_newer(
    current: Mapping[str, str],
    *,
    incoming_revision: int | None,
    incoming_updated_at: datetime | None,
    incoming_source_digest: str,
) -> bool:
    current_revision = _rule_revision(current.get("revision"))
    if current_revision is not None or incoming_revision is not None:
        return incoming_revision is not None and (
            current_revision is None or incoming_revision > current_revision
        )
    current_updated_at = _rule_updated_at(current.get("updated_at"))
    if current_updated_at is not None or incoming_updated_at is not None:
        return incoming_updated_at is not None and (
            current_updated_at is None or incoming_updated_at > current_updated_at
        )
    current_digest = str(current.get("source_digest") or "")
    return bool(incoming_source_digest and incoming_source_digest != current_digest)


class Forseti(
    Agent,
    ForsetiDevelopmentAuthorityMixin,
    ForsetiJudgmentMixin,
    ForsetiArbitrationMixin,
    HandoverKnowledgeMixin,
    AssignmentJudgmentMixin,
    ForsetiAlertNoiseMixin,
):
    """Wave-3 Forseti: rule match + risk verdict + RBAC + SecurityEvent.

    ``governed_execution_selected`` is the explicit add-on selection. Its default keeps
    forecasts and prediction-fed capacity arbitration advisory: they publish ActionType-free
    Verdicts, and only the selected add-on lets them reach the existing action gates.
    """

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        rbac: dict[str, frozenset[str]] | None = None,
        action_semantics: ActionSemanticsCatalog | None = None,
        judgment_table: JudgmentTable | None = None,
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
        architecture_review_timeout_seconds: float = 30.0,
        change_assessment_timeout_seconds: float = 30.0,
        anomaly_action_sources: Mapping[str, AnomalyActionSource] | None = None,
        development_profile: FullAuthorityDevelopmentProfile | None = None,
        development_binding_source: DevelopmentAuthorityBindingSource | None = None,
        development_executor_principal: str | None = None,
        development_action_types: Mapping[str, RegisteredDevelopmentAction] | None = None,
        governed_execution_selected: bool = False,
        rule_staleness_window: timedelta = _DEFAULT_RULE_STALENESS_WINDOW,
        state_store: StateStore | None = None,
    ) -> None:
        if cross_vertical_timeout_seconds <= 0.0 or cross_vertical_timeout_seconds > 300.0:
            raise ValueError("cross_vertical_timeout_seconds MUST be in (0, 300]")
        if architecture_review_timeout_seconds <= 0.0:
            raise ValueError("architecture_review_timeout_seconds MUST be positive")
        if change_assessment_timeout_seconds <= 0.0:
            raise ValueError("change_assessment_timeout_seconds MUST be positive")
        if rule_staleness_window <= timedelta(0):
            raise ValueError("rule_staleness_window MUST be positive")
        super().__init__(spec=_FORSETI)
        self.bus = bus
        # Observation-first by default: learned and predicted input stays advisory (#1541).
        self._governed_execution_selected = governed_execution_selected is True
        self._advisory_arbitrations: BoundedLruDict[str, dict[str, Any]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        self.initialize_assignment_checks()
        self._rbac = rbac if rbac is not None else _DEFAULT_RBAC
        self._action_semantics = action_semantics
        self._judgment_table = judgment_table or DEFAULT_JUDGMENT_TABLE
        self._forseti_state_store = state_store
        self._operational_context = operational_context
        self._test_context_source = test_context_source
        self._test_context_admission = test_context_admission
        self._test_context_clock = test_context_clock or (lambda: datetime.now(tz=UTC))
        self._rule_staleness_window = rule_staleness_window
        self._rule_staleness_started_at = self._now()
        self._last_owner_rule_update_at: datetime | None = None
        self._rule_cache_stale = False
        self._decision_coordinator = decision_coordinator or DomainDecisionCoordinator()
        self._operational_planner = operational_planner
        self._kinetic_proposal_source = kinetic_proposal_source
        self._prospective_lineage_finalizer = prospective_lineage_finalizer
        self._change_assessor = change_assessor
        self._anomaly_action_sources = dict(anomaly_action_sources or {})
        self.initialize_development_authority(
            profile=development_profile,
            binding_source=development_binding_source,
            executor_principal=development_executor_principal,
            action_types=development_action_types,
            clock=self._test_context_clock,
        )
        if len(self._anomaly_action_sources) > 32 or any(
            not key or key != key.strip() or len(key) > 128 for key in self._anomaly_action_sources
        ):
            raise ValueError("anomaly action bindings must contain bounded exact signal names")
        self._architecture_review_loop = architecture_review_loop
        self._architecture_review_timeout_seconds = architecture_review_timeout_seconds
        self._change_assessment_timeout_seconds = change_assessment_timeout_seconds
        # Optional runtime probe; an absent probe never invents agent unavailability.
        self._agent_availability = agent_availability
        self._cross_vertical_timeout_seconds = cross_vertical_timeout_seconds
        self._cross_vertical_candidates = CrossVerticalCandidateAccumulator(
            max_pending=_MAX_RESOURCES
        )
        self._cross_vertical_timeout_tasks: dict[str, asyncio.Task[None]] = {}
        self._cross_vertical_timeout_deadlines: dict[str, float] = {}
        self._cross_vertical_timeout_heap: list[tuple[float, str]] = []
        self._cross_vertical_timeout_max = _MAX_RESOURCES
        self._cross_vertical_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
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
        self._domain_observed_at: BoundedLruDict[str, dict[str, str]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        self._domain_correlation_ids: BoundedLruDict[str, dict[str, str]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        self._domain_source_freshness: BoundedLruDict[
            str, dict[str, tuple[SourceFreshness, ...]]
        ] = BoundedLruDict(_MAX_RESOURCES)
        self._domain_arguments: BoundedLruDict[str, dict[str, dict[str, object]]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        self._domain_cost_annotations: BoundedLruDict[str, dict[str, Any]] = BoundedLruDict(
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
        self._rule_state: BoundedLruDict[str, dict[str, str]] = BoundedLruDict(_MAX_RESOURCES)
        self._no_rule_folds: BoundedLruDict[str, int] = BoundedLruDict(_MAX_RESOURCES)
        self._verdict_quality_samples: BoundedLruDict[str, dict[str, str]] = BoundedLruDict(
            _QUALITY_SAMPLE_LIMIT
        )
        self._last_verdict_coherence: dict[str, object] = {
            "evidence_state": "not_observed",
            "sample_size": 0,
            "disagreements": 0,
            "unit": "count",
        }
        self._last_novelty_drift: dict[str, object] = {
            "evidence_state": "not_observed",
            "sample_size": 0,
            "tier_mix": {"T0": 0, "T1": 0, "T2": 0},
            "t2_ratio": None,
            "unit": "ratio",
        }
        self._published_what_if_inputs: BoundedLruSet[str] = BoundedLruSet(_QUALITY_SAMPLE_LIMIT)
        self._last_retrospective_what_if: dict[str, object] = {
            "evidence_state": "not_requested",
            "sample_size": 0,
            "disagreements": 0,
            "unit": "count",
        }

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
        if (
            topic == "object.event"
            and payload.get("event_type") == INCIDENT_INTERVENTION_EVENT_TYPE
            and payload.get("producer_principal") not in {None, "Huginn"}
        ):
            raise ValueError("incident guidance requires the Huginn-owned normalized Event")
        owner_rejection_behaviors = {
            "object.change": "typed_input:rejected_owner",
            "object.event": "typed_input:rejected_owner",
            "object.anomaly": "typed_input:rejected_owner",
            "object.drift": "typed_input:rejected_owner",
            "object.forecast": "typed_input:rejected_owner",
            "object.resilience-score": "typed_input:rejected_owner",
            "object.cost-anomaly": "specialist_advice:rejected_owner",
            "object.capacity-forecast": "specialist_advice:rejected_owner",
            "object.capacity-graduation-recommendation": "typed_input:rejected_owner",
            "object.arbitration-decision": "arbitration_decision:rejected_owner",
            "object.rule": "rule_state:rejected_owner",
        }
        if topic in owner_rejection_behaviors and require_topic_owner(
            self,
            topic,
            payload,
            behavior=owner_rejection_behaviors[topic],
        ):
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
            await self._record_detection_readiness(payload)
            return
        if topic == "object.event" and payload.get("kind") == "retrospective_what_if_request":
            await self._run_retrospective_what_if(payload)
            return
        if payload.get("kind") == "document_ingestion":
            if topic == "object.event" and payload.get("event_type") == "document.received":
                await self.judge_document_ingestion(payload)
            elif topic == "object.anomaly" and payload.get("stage") == "protection_check":
                await self.judge_document_safety(payload)
            return
        if topic == "object.forecast":
            await self._judge_forecast(payload)
            return
        if topic in ("object.event", "object.anomaly", "object.drift"):
            if topic == "object.event":
                await self._attach_change_assessment(payload)
            arbitration = await self.maybe_request_arbitration(payload)
            if arbitration is not None:
                return
            await self.judge(payload)
        elif topic == "object.cost-anomaly":
            await self._ingest_domain_signal("cost", payload)
        elif topic == "object.capacity-forecast":
            arbitration = await self._ingest_domain_signal("capacity", payload)
            if arbitration is None:
                await self._judge_capacity_forecast(payload)
        elif topic == "object.capacity-graduation-recommendation":
            await self._judge_capacity_graduation(payload)
        elif topic == "object.arbitration-decision":
            await self._record_arbitration(payload)
        elif topic == "object.rule":
            await self._record_rule_state(payload)

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
            self.record_behavior("architecture_review:unbound")
            return
        try:
            async with asyncio.timeout(self._architecture_review_timeout_seconds):
                observation = await self._architecture_review_loop.evaluate(payload)
        except TimeoutError:
            self.record_behavior("architecture_review:timeout")
            change_id = str(payload.get("id") or payload.get("event_id") or "unknown")
            correlation_id = str(
                payload.get("correlation_id") or f"architecture-review:{change_id}"
            )
            observation = ArchitectureReviewObservation.hold(
                change_id=change_id,
                idempotency_key=str(
                    payload.get("idempotency_key") or f"architecture-review-timeout:{change_id}"
                ),
                correlation_id=correlation_id,
                target_ref=str(payload.get("target_ref") or "unknown"),
                change_digest="unknown",
                reason="observation_review_timeout",
            )
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
            async with asyncio.timeout(self._change_assessment_timeout_seconds):
                graph_evidence = await self._planned_change_graph_evidence(change)
            async with asyncio.timeout(self._change_assessment_timeout_seconds):
                assessment = await self._change_assessor.assess(
                    change,
                    graph_evidence=graph_evidence,
                )
        except TimeoutError:
            event["change_assessment_status"] = "failed"
            event["human_approval_required"] = True
            self.record_behavior("change_assessment:timeout")
            return
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

    def health(self) -> dict[str, Any]:
        behavior = self.behavior_snapshot()
        unavailable_peers: tuple[str, ...] = ()
        if self._agent_availability is not None:
            try:
                unavailable_peers = tuple(sorted(str(name) for name in self._agent_availability()))
            except Exception:  # noqa: BLE001 - health must stay bounded
                unavailable_peers = ("availability_probe_unavailable",)
        t2_escalations = int(behavior.get("t2:escalated", 0) or 0)
        verdicts = sum(
            int(count)
            for key, count in behavior.items()
            if isinstance(key, str) and key.startswith("verdict:") and isinstance(count, int)
        )
        grounding_missing = int(behavior.get("grounding:missing", 0) or 0) + len(
            self._no_rule_folds
        )
        model_disagreements = int(behavior.get("model:disagreement", 0) or 0)
        fallback_closures = int(behavior.get("arbitration:fallback_terminal_hil", 0) or 0)
        return {
            "agent": "Forseti",
            "status": "degraded" if self._rule_cache_stale else "ok",
            "judgment_table_digest": self._judgment_table.digest,
            "action_semantics_bound": self._action_semantics is not None,
            "architecture_review_bound": self._architecture_review_loop is not None,
            "rule_state_cached": len(self._rule_state),
            "rule_cache_fresh": not self._rule_cache_stale,
            "rule_staleness_window_seconds": self._rule_staleness_window.total_seconds(),
            "last_owner_rule_update_at": (
                self._last_owner_rule_update_at.isoformat()
                if self._last_owner_rule_update_at is not None
                else ""
            ),
            "unavailable_required_peers": list(unavailable_peers),
            "open_arbitrations": len(self._unresolved_arbitrations),
            "fallback_terminal_hil_closures": fallback_closures,
            "operator_alert": {
                "required": "Odin" in unavailable_peers,
                "status": "pending" if "Odin" in unavailable_peers else "not_required",
            },
            "no_verdict_fallback": "Forseti" in unavailable_peers,
            "judgment_counters": {
                "verdicts": verdicts,
                "t2_escalations": t2_escalations,
                "grounding_missing": grounding_missing,
                "model_disagreements": model_disagreements,
            },
            "verdict_coherence_self_test": dict(self._last_verdict_coherence),
            "novelty_drift_signal": dict(self._last_novelty_drift),
            "retrospective_what_if": dict(self._last_retrospective_what_if),
            "kpis": {
                "t2_escalation_rate": _ratio_kpi(t2_escalations, verdicts),
                "mixed_model_disagreement_rate": _ratio_kpi(model_disagreements, verdicts),
                "grounding_missing_rate": _ratio_kpi(
                    grounding_missing, verdicts + grounding_missing
                ),
            },
            "no_rule_folds": dict(self._no_rule_folds.items()),
            "behavior": behavior,
        }

    def _now(self) -> datetime:
        current = self._test_context_clock()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("Forseti clock MUST return a timezone-aware datetime")
        return current

    async def _record_rule_state(self, payload: dict[str, Any]) -> None:
        if payload.get("producer_principal") != "Mimir":
            self.record_behavior("rule_state:rejected_owner")
            return
        action_type = str(
            payload.get("action_type")
            or payload.get("remediates")
            or payload.get("action_type_id")
            or ""
        )
        state = str(payload.get("state") or payload.get("outcome") or "").strip().lower()
        if not action_type or state not in {"active", "promoted", "retired", "revoked"}:
            self.record_behavior("rule_state:invalid")
            return
        normalized = "active" if state == "promoted" else state
        incoming_revision = _rule_revision(payload.get("revision"))
        incoming_updated_at = _rule_updated_at(payload.get("updated_at"))
        incoming_source_digest = str(
            payload.get("source_digest")
            or payload.get("reviewed_package_digest")
            or payload.get("package_digest")
            or ""
        )
        current = self._rule_state.get(action_type)
        if current is not None and not _rule_state_is_newer(
            current,
            incoming_revision=incoming_revision,
            incoming_updated_at=incoming_updated_at,
            incoming_source_digest=incoming_source_digest,
        ):
            self.record_behavior("rule_state:stale")
            return
        record = {
            "state": normalized,
            "rule_id": str(payload.get("rule_id") or payload.get("id") or ""),
            "correlation_id": str(payload.get("correlation_id") or ""),
            "revision": "" if incoming_revision is None else str(incoming_revision),
            "updated_at": "" if incoming_updated_at is None else incoming_updated_at.isoformat(),
            "source_digest": incoming_source_digest,
        }
        self._rule_state.set(action_type, record)
        if self._forseti_state_store is not None:
            await self._forseti_state_store.write_state(
                f"pantheon/forseti/rule-state|{action_type}",
                {
                    "kind": "rule_state",
                    "action_type": action_type,
                    **record,
                    "recorded_at": self._now().isoformat(),
                },
            )
        self._last_owner_rule_update_at = self._now()
        self._rule_cache_stale = False
        self.record_behavior(f"rule_state:{normalized}")

    async def rehydrate(self) -> int:
        """Restore durable judgment-lowering projections before typed consumers start."""
        store = self._forseti_state_store
        if store is None:
            return 0
        restored = 0
        for prefix, target in (
            ("pantheon/forseti/detection-readiness|", self._detection_readiness),
            ("pantheon/forseti/rule-state|", self._rule_state),
        ):
            rows, total = await store.read_state_page(prefix, limit=_MAX_RESOURCES)
            if total > _MAX_RESOURCES:
                raise RuntimeError("Forseti durable projection count exceeds its bound")
            for row in rows:
                if prefix.endswith("detection-readiness|"):
                    resource_id = str(row.get("resource_id") or "")
                    if resource_id:
                        target.set(
                            resource_id,
                            {
                                "decision": str(row.get("decision") or ""),
                                "authority_ceiling": str(row.get("authority_ceiling") or ""),
                            },
                        )
                        restored += 1
                else:
                    action_type = str(row.get("action_type") or "")
                    if action_type:
                        target.set(
                            action_type,
                            {
                                "state": str(row.get("state") or ""),
                                "rule_id": str(row.get("rule_id") or ""),
                                "correlation_id": str(row.get("correlation_id") or ""),
                                "revision": str(row.get("revision") or ""),
                                "updated_at": str(row.get("updated_at") or ""),
                                "source_digest": str(row.get("source_digest") or ""),
                            },
                        )
                        restored += 1
        restored += await forseti_durability.rehydrate_arbitration_state(self)
        return restored

    async def maintenance_tick(self) -> None:
        await super().maintenance_tick()
        reference = self._last_owner_rule_update_at or self._rule_staleness_started_at
        stale = self._now() - reference > self._rule_staleness_window
        self._rule_cache_stale = stale
        if stale:
            self.record_behavior("rule_cache:stale")
        self._run_verdict_coherence_self_test()
        self._refresh_novelty_drift_signal()

    def _remember_verdict_for_quality(
        self,
        event: Mapping[str, Any],
        verdict: Mapping[str, Any],
    ) -> None:
        correlation_id = str(verdict.get("correlation_id") or event.get("correlation_id") or "")
        idempotency_key = str(verdict.get("idempotency_key") or "")
        key = correlation_id or idempotency_key
        if not key:
            return
        tier = str(event.get("judgment_tier") or event.get("source_tier") or "T0").upper()
        if tier not in {"T0", "T1", "T2"}:
            tier = "T0"
        self._verdict_quality_samples.set(
            key,
            {
                "event_type": str(event.get("event_type") or ""),
                "action_type": str(verdict.get("action_type") or ""),
                "risk_verdict": str(verdict.get("risk_verdict") or ""),
                "tier": tier,
            },
        )

    async def _run_retrospective_what_if(self, request: Mapping[str, Any]) -> None:
        what_if_table = judgment_table_from_request(request.get("judgment_table"))
        correlation_id = str(request.get("correlation_id") or "")
        if what_if_table is None or not correlation_id:
            self._last_retrospective_what_if = {
                "evidence_state": "invalid_request",
                "sample_size": 0,
                "disagreements": 0,
                "unit": "count",
            }
            self.record_behavior("retrospective_what_if:invalid")
            return
        raw_limit = request.get("sample_limit", MAX_WHAT_IF_SAMPLES)
        sample_limit = (
            raw_limit if isinstance(raw_limit, int) and not isinstance(raw_limit, bool) else 1
        )
        batch = build_what_if_batch(
            correlation_id=correlation_id,
            active_table=self._judgment_table,
            what_if_table=what_if_table,
            retained_samples=self._verdict_quality_samples.items(),
            sample_limit=sample_limit,
        )
        if batch is None:
            self._last_retrospective_what_if = {
                "evidence_state": "insufficient_sample",
                "sample_size": 0,
                "disagreements": 0,
                "unit": "count",
            }
            self.record_behavior("retrospective_what_if:no_samples")
            return
        new_keys = tuple(
            key for key in batch.idempotency_keys if key not in self._published_what_if_inputs
        )
        if not new_keys:
            self.record_behavior("retrospective_what_if:duplicate")
            return
        for key in new_keys:
            self._published_what_if_inputs.add(key)
        payload = {
            **batch.payload,
            "idempotency_key": stable_idempotency_key(
                "forseti-retrospective-what-if",
                correlation_id,
                self._judgment_table.digest,
                what_if_table.digest,
                new_keys,
            ),
        }
        outcomes = payload["outcomes"]
        disagreement_count = int(payload["disagreement_count"])
        self._last_retrospective_what_if = {
            "evidence_state": "measured",
            "sample_size": len(outcomes),
            "disagreements": disagreement_count,
            "contract_version": payload["what_if_contract"]["contract_version"],
            "what_if_judgment_table_digest": what_if_table.digest,
            "unit": "count",
        }
        self.record_behavior("retrospective_what_if:published")
        if disagreement_count:
            self.record_behavior("retrospective_what_if:disagreement", disagreement_count)
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.verdict", payload)

    def _run_verdict_coherence_self_test(self) -> None:
        disagreements = 0
        sample_size = 0
        for _key, sample in self._verdict_quality_samples.items():
            sample_size += 1
            action_type = sample["action_type"] or self._judgment_table.rule_match.get(
                sample["event_type"],
                "",
            )
            expected = self._judgment_table.risk_verdict.get(action_type, "hil")
            if sample["risk_verdict"] != expected:
                disagreements += 1
        self._last_verdict_coherence = {
            "evidence_state": "measured" if sample_size else "insufficient_sample",
            "sample_size": sample_size,
            "disagreements": disagreements,
            "unit": "count",
        }
        if disagreements:
            self.record_behavior("verdict_coherence:disagreement", disagreements)
        else:
            self.record_behavior("verdict_coherence:checked")

    def _refresh_novelty_drift_signal(self) -> None:
        tier_mix = {"T0": 0, "T1": 0, "T2": 0}
        for _key, sample in self._verdict_quality_samples.items():
            tier = sample["tier"]
            tier_mix[tier] = tier_mix.get(tier, 0) + 1
        sample_size = sum(tier_mix.values())
        t2_ratio = (tier_mix["T2"] / sample_size) if sample_size else None
        self._last_novelty_drift = {
            "evidence_state": "measured" if sample_size else "insufficient_sample",
            "sample_size": sample_size,
            "tier_mix": tier_mix,
            "t2_ratio": t2_ratio,
            "unit": "ratio",
        }
        if t2_ratio is not None and t2_ratio > 0.1:
            self.record_behavior("novelty_drift:t2_ratio_high")
        else:
            self.record_behavior("novelty_drift:checked")

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            **telemetry_recipe_facts(),
            "known_action_verdicts": dict(self._judgment_table.risk_verdict),
            "rule_matches": dict(self._judgment_table.rule_match),
            "judgment_table_digest": self._judgment_table.digest,
            "arbitrations_recorded": len(self.arbitrations),
            # Both gates that force an otherwise-auto verdict to human
            # review. The charter tells Forseti to report them as exactly
            # that, so they MUST be readable through the judgment tool.
            "unresolved_arbitrations": len(self._unresolved_arbitrations),
            "readiness_limited_resources": len(self._detection_readiness),
            "rca_evidence_available": False,
            "action_type": None,
            "risk_verdict": None,
        }
        if "rca_evidence" in semantic_intents(context):
            statement = "No grounded RCA record is retained by this conversational projection"
            return evidence_backed_result(self.spec.name, facts, statement)
        actions = mentioned(question, self._judgment_table.risk_verdict)
        if actions:
            action = actions[0]
            verdict = self._judgment_table.risk_verdict[action]
            facts.update({"action_type": action, "risk_verdict": verdict})
            statement = f"Action {action!r} has configured default risk verdict {verdict!r}"
            return evidence_backed_result(self.spec.name, facts, statement)
        evidence_ref = attach_agent_state_evidence(self.spec.name, facts)
        answer = forseti_role_answer(str(context.get("locale")), facts, evidence_ref)
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Forseti"]

"""Forseti - Judge (Wave 3 behavior).

Forseti issues verdicts (auto / hil / deny) based on:
- a rule-match table (deterministic keyword -> ActionType id)
- a risk_verdict table (deterministic ActionType id -> auto/hil/deny)
- an RBAC hook (initiator principal + role → deny + SecurityEvent)

Wave 3 keeps rule matching intentionally simple; the real T0 loader is
in :mod:`fdai.rule_catalog`. Mixed-model cross-check and grounding
(T2) land in later waves.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from fdai.agents._framework.action_semantics import (
    ActionSemanticsCatalog,
    quorum_for,
    rollback_contract_for,
)
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.forseti_decision_helpers import (
    change_assessment_mapping as _change_assessment_mapping,
)
from fdai.agents._framework.forseti_decision_helpers import (
    decision_case_mapping as _decision_case_mapping,
)
from fdai.agents._framework.forseti_decision_helpers import (
    is_conflict as _is_conflict,
)
from fdai.agents._framework.forseti_decision_helpers import (
    signal_impact as _signal_impact,
)
from fdai.agents._framework.forseti_decision_helpers import (
    source_freshness as _source_freshness,
)
from fdai.agents._framework.forseti_judgment import RISK_VERDICT as _RISK_VERDICT
from fdai.agents._framework.forseti_judgment import RULE_MATCH as _RULE_MATCH
from fdai.agents._framework.forseti_judgment import ForsetiJudgmentMixin
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    mentioned,
    semantic_intents,
)
from fdai.agents._framework.pantheon import _FORSETI
from fdai.agents._framework.specialist_ingress import SPECIALIST_EVENT_PREFIX
from fdai.core.decision_case import DomainDecisionCoordinator, DomainDecisionProjection
from fdai.core.impact_analysis import (
    ChangeAssessment,
    ChangeGraphEvidenceReceipt,
    change_graph_evidence_from_snapshot,
)
from fdai.core.operational_context import OperationalContextMaterializer, SourceFreshness
from fdai.core.operational_planning import (
    KineticActionProposal,
    KineticActionProposalSource,
    SpecialistPlanningCoordinator,
    SpecialistPlanningProjection,
    validate_operational_plan_identity,
)
from fdai.core.readiness import AuthorityCeiling, DetectionReadinessDecision

# ---------------------------------------------------------------------------
# Deterministic tables (wave 3 defaults)
# ---------------------------------------------------------------------------

# ``event_type -> proposed ActionType id`` (rule match). Wave 3 uses a
# tiny in-memory table; real T0 loader consumes rule catalog YAML.
# ---------------------------------------------------------------------------
# RBAC (wave 3 minimal model)
# ---------------------------------------------------------------------------

# principal -> set of allowed action ids. Fork RBAC seam replaces this.
_DEFAULT_RBAC: dict[str, frozenset[str]] = {
    "operator@example.com": frozenset(_RISK_VERDICT.keys()) - {"remediate.delete-storage"},
    "guest@example.com": frozenset({"ops.restart-service"}),
}

# LRU cap on the per-resource domain-advice maps, so a long-lived judge that
# sees advice for many resources without a conflict cannot leak memory.
_MAX_RESOURCES = 10_000

_DecisionProjection = DomainDecisionProjection | SpecialistPlanningProjection


class _ChangeAssessor(Protocol):
    async def assess(
        self,
        change: Mapping[str, Any],
        *,
        graph_evidence: ChangeGraphEvidenceReceipt,
        unresolved_conflicts: tuple[str, ...] = (),
    ) -> ChangeAssessment: ...


class Forseti(Agent, ForsetiJudgmentMixin):
    """Wave-3 Forseti: rule match + risk verdict + RBAC + SecurityEvent."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        rbac: dict[str, frozenset[str]] | None = None,
        action_semantics: ActionSemanticsCatalog | None = None,
        operational_context: OperationalContextMaterializer | None = None,
        decision_coordinator: DomainDecisionCoordinator | None = None,
        operational_planner: SpecialistPlanningCoordinator | None = None,
        kinetic_proposal_source: KineticActionProposalSource | None = None,
        change_assessor: _ChangeAssessor | None = None,
    ) -> None:
        super().__init__(spec=_FORSETI)
        self.bus = bus
        self._rbac = rbac if rbac is not None else _DEFAULT_RBAC
        self._action_semantics = action_semantics
        self._operational_context = operational_context
        self._decision_coordinator = decision_coordinator or DomainDecisionCoordinator()
        self._operational_planner = operational_planner
        self._kinetic_proposal_source = kinetic_proposal_source
        self._change_assessor = change_assessor
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
        # Accumulated domain advice per resource id: {resource: {domain:
        # recommendation}}. Fed by object.cost-anomaly / capacity-forecast
        # so conflicting advice arriving on separate signals still triggers
        # arbitration. Bounded (LRU): non-conflicting advice that never gets
        # popped would otherwise grow one entry per resource forever.
        self._domain_advice: BoundedLruDict[str, dict[str, str]] = BoundedLruDict(_MAX_RESOURCES)
        # Measured impact magnitude per (resource, domain) in [0, 1], derived
        # from the signal (cost overspend ratio, capacity forecast util). Fed
        # to Odin so arbitration weighs magnitude, not just priority.
        self._domain_impact: BoundedLruDict[str, dict[str, float]] = BoundedLruDict(_MAX_RESOURCES)
        self._domain_observed_at: BoundedLruDict[str, str] = BoundedLruDict(_MAX_RESOURCES)
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

    # ---- typed port ----------------------------------------------------

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
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
            await self.maybe_request_arbitration(payload)
            await self.judge(payload)
        elif topic == "object.cost-anomaly":
            await self._ingest_domain_signal("cost", payload)
        elif topic == "object.capacity-forecast":
            await self._ingest_domain_signal("capacity", payload)
        elif topic == "object.arbitration-decision":
            await self._record_arbitration(payload)

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

    def _record_detection_readiness(self, payload: dict[str, Any]) -> None:
        resource_id = str(payload.get("resource_id") or "")
        try:
            decision = DetectionReadinessDecision(str(payload.get("decision") or ""))
            ceiling = AuthorityCeiling(str(payload.get("authority_ceiling") or ""))
        except ValueError:
            self.record_behavior("detection_readiness:invalid")
            return
        if not resource_id:
            self.record_behavior("detection_readiness:invalid")
            return
        self._detection_readiness.set(
            resource_id,
            {"decision": decision.value, "authority_ceiling": ceiling.value},
        )
        self.record_behavior(f"detection_readiness:{decision.value}")

    # ---- cross-vertical arbitration -----------------------------------

    async def maybe_request_arbitration(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Raise an ArbitrationRequest when inline domain advice conflicts.

        Domain specialists (Njord / Freyr / Loki) may attach advice to an
        event under ``domain_advice`` (``{domain: recommendation}``). When
        two or more domains disagree on the same resource, Forseti - the
        sole writer of ``object.arbitration-request`` - asks Odin to break
        the tie by priority. Unanimous or single-domain advice needs no
        arbitration.
        """
        advice = event.get("domain_advice")
        if not isinstance(advice, dict) or len(advice) < 2:
            return None
        normalized = {str(k): str(v) for k, v in advice.items()}
        if not _is_conflict(normalized):
            return None
        correlation_id = str(event.get("correlation_id") or "")
        resource_id = str(event.get("resource_id") or "")
        if not correlation_id or not resource_id:
            self.record_behavior("arbitration_invalid_identity")
            raise ValueError("arbitration input identities MUST be non-empty")
        return await self._emit_arbitration_request(
            resource_id=resource_id,
            advice=normalized,
            correlation_id=correlation_id,
            observed_at=str(event.get("detected_at") or ""),
            change_assessment=_change_assessment_mapping(event),
            source_freshness=_source_freshness(event.get("source_freshness")),
        )

    async def _ingest_domain_signal(
        self, domain: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Accumulate a domain recommendation and arbitrate on conflict.

        Cost anomalies and capacity forecasts arrive as separate signals;
        Forseti keys them by resource id so a cost 'scale_down' and a
        capacity 'scale_up' on the same resource surface as a conflict.
        """
        resource_id = str(payload.get("resource_id") or payload.get("scope") or "")
        recommendation = str(payload.get("recommendation", ""))
        if not resource_id or not recommendation:
            return None
        advice = self._domain_advice.get(resource_id)
        if advice is None:
            advice = {}
            self._domain_advice.set(resource_id, advice)
        advice[domain] = recommendation
        impacts = self._domain_impact.get(resource_id)
        if impacts is None:
            impacts = {}
            self._domain_impact.set(resource_id, impacts)
        impacts[domain] = _signal_impact(domain, payload)
        observed_at = str(payload.get("observed_at") or "")
        if observed_at:
            self._domain_observed_at.set(resource_id, observed_at)
        if not _is_conflict(advice):
            return None
        correlation_id = str(payload.get("correlation_id") or "")
        if not correlation_id:
            self.record_behavior("arbitration_invalid_identity")
            raise ValueError("arbitration input correlation_id MUST be non-empty")
        request = await self._emit_arbitration_request(
            resource_id=resource_id,
            advice=dict(advice),
            correlation_id=correlation_id,
            impacts=dict(impacts),
            observed_at=self._domain_observed_at.get(resource_id) or "",
            source_freshness=_source_freshness(payload.get("source_freshness")),
        )
        # Consume the accumulated advice once the conflict is surfaced.
        # Leaving it in place would (a) grow both maps without bound over
        # every resource ever seen (memory leak) and (b) make the stale
        # opposing recommendation re-trigger a duplicate arbitration on the
        # very next signal for this resource. Fresh signals re-accumulate.
        self._domain_advice.pop(resource_id, None)
        self._domain_impact.pop(resource_id, None)
        self._domain_observed_at.pop(resource_id, None)
        return request

    async def _emit_arbitration_request(
        self,
        *,
        resource_id: Any,
        advice: dict[str, str],
        correlation_id: str,
        impacts: dict[str, float] | None = None,
        observed_at: str = "",
        change_assessment: dict[str, Any] | None = None,
        source_freshness: tuple[SourceFreshness, ...] = (),
    ) -> dict[str, Any]:
        if not correlation_id or not str(resource_id or ""):
            raise ValueError("arbitration request identities MUST be non-empty")
        request = {
            "producer_principal": "Forseti",
            "correlation_id": correlation_id,
            "resource_id": resource_id,
            "domains_in_conflict": sorted(advice),
            "advice": advice,
            "impacts": impacts or {},
        }
        projection = await self._build_domain_decision_projection(
            resource_id=str(resource_id or ""),
            correlation_id=correlation_id,
            advice=advice,
            impacts=impacts or {},
            observed_at=observed_at,
            source_freshness=source_freshness,
        )
        if projection is not None:
            request["decision_case"] = _decision_case_mapping(projection, change_assessment)
            self._pending_decision_cases.set(correlation_id, projection)
            if change_assessment is not None:
                self._pending_change_assessments.set(correlation_id, change_assessment)
        self._arbitration_resources.set(correlation_id, str(resource_id))
        # Decision semantics: the judge decided to raise arbitration. Recorded
        # independent of a bus (delivery is measured by the bus metrics, not
        # here), so a bus-less unit still measures the decision.
        self.record_behavior("arbitration_requested")
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.arbitration-request", request)
        return request

    async def _record_arbitration(self, decision: dict[str, Any]) -> None:
        correlation_id = str(decision.get("correlation_id", ""))
        if not correlation_id:
            return
        self.arbitrations[correlation_id] = str(decision.get("winning_domain", ""))
        # Bound the map: it is keyed by correlation id (one per arbitrated
        # event, forever), so an unbounded dict would leak on a long-lived
        # judge - the same reason _domain_advice / _domain_impact are LRU.
        # Dict preserves insertion order, so the first key is the oldest; a
        # re-recorded correlation updates in place (order unchanged) and never
        # triggers a spurious eviction.
        if len(self.arbitrations) > _MAX_RESOURCES:
            self.arbitrations.pop(next(iter(self.arbitrations)))
        if decision.get("escalate_hil") is True:
            await self._escalate_arbitration(correlation_id, decision)
            return
        projection = self._pending_decision_cases.get(correlation_id)
        if projection is None:
            if self._arbitration_resources.get(correlation_id) is not None:
                await self._escalate_arbitration(correlation_id, decision)
            return
        if projection.selection.requires_human_approval:
            await self._escalate_arbitration(correlation_id, decision)
            return
        change_assessment = self._pending_change_assessments.get(correlation_id)
        if change_assessment is not None and change_assessment.get("review_required") is True:
            await self._escalate_arbitration(correlation_id, decision)
            return
        winning_domain = str(decision.get("winning_domain") or "")
        option = projection.option_for_domain(winning_domain)
        eligible_options = {
            option_id for option_id, _score in projection.selection.objective_scores
        }
        if option is None or option.option_id not in eligible_options or option.action_type is None:
            await self._escalate_arbitration(correlation_id, decision)
            return
        await self._publish_resolved_arbitration_verdict(
            correlation_id=correlation_id,
            decision=decision,
            projection=projection,
            action_type=option.action_type,
        )

    async def _build_domain_decision_projection(
        self,
        *,
        resource_id: str,
        correlation_id: str,
        advice: dict[str, str],
        impacts: dict[str, float],
        observed_at: str,
        source_freshness: tuple[SourceFreshness, ...],
    ) -> DomainDecisionProjection | SpecialistPlanningProjection | None:
        if self._operational_context is None or not resource_id or not observed_at:
            return None
        try:
            cutoff = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            if cutoff.tzinfo is None:
                return None
            context = await self._operational_context.materialize(
                target_resource_id=resource_id,
                cutoff=cutoff,
                catalog_versions={},
                source_freshness=source_freshness,
            )
            if context.review_required:
                return None
            if self._operational_planner is not None:
                return await self._operational_planner.build(
                    correlation_id=correlation_id,
                    context=context,
                    advice=advice,
                    impacts=impacts,
                    created_at=cutoff,
                )
            return self._decision_coordinator.build(
                correlation_id=correlation_id,
                context=context,
                advice=advice,
                impacts=impacts,
                created_at=cutoff,
            )
        except (TypeError, ValueError):
            self.record_behavior("decision_case:invalid")
            return None
        except Exception:  # noqa: BLE001 - optional decision projection fails closed
            self.record_behavior("decision_case:unavailable")
            return None

    async def _publish_resolved_arbitration_verdict(
        self,
        *,
        correlation_id: str,
        decision: dict[str, Any],
        projection: _DecisionProjection,
        action_type: str,
    ) -> None:
        self._pending_decision_cases.pop(correlation_id, None)
        risk_verdict = _RISK_VERDICT.get(action_type, "hil")
        kinetic_proposal, invalid_kinetic_proposal = await self._resolve_kinetic_proposal(
            correlation_id=correlation_id,
            projection=projection,
            action_type=action_type,
        )
        if invalid_kinetic_proposal:
            risk_verdict = "deny"
        verdict = {
            "producer_principal": "Forseti",
            "correlation_id": correlation_id,
            "idempotency_key": correlation_id,
            "resource_id": self._arbitration_resources.get(correlation_id) or "",
            "action_type": action_type,
            "risk_verdict": risk_verdict,
            "reason": "arbitration_resolved",
            "arbitration": {
                "winning_domain": decision.get("winning_domain"),
                "losing_domains": decision.get("losing_domains") or [],
                "margin": decision.get("margin"),
            },
            "decision_case": _decision_case_mapping(
                projection,
                self._pending_change_assessments.pop(correlation_id, None),
            ),
            "quorum_required": quorum_for(action_type, self._action_semantics),
            "rollback_contract": rollback_contract_for(action_type, self._action_semantics),
            "initiator_principal": None,
        }
        if kinetic_proposal is not None:
            verdict["params"] = kinetic_proposal.arguments()
            verdict["kinetic_proposal"] = kinetic_proposal.model_dump(mode="json")
        self.record_behavior(f"verdict:{risk_verdict}")
        self.record_behavior("arbitration_resolved")
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.verdict", verdict)

    async def _escalate_arbitration(
        self,
        correlation_id: str,
        decision: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Turn Odin's unresolved arbitration into a human-visible verdict.

        Odin flags a near-tie, an unknown domain, or a non-finite impact
        rather than auto-picking. Recording the winner and stopping there
        would drop the conflict: the accumulated domain advice is already
        consumed, so nothing else would ever surface it, and the escalation
        would exist only inside Odin's payload. Fail toward safety instead
        (``agent-pantheon.md`` 3.1) and issue the ``hil`` verdict that puts
        the conflict in front of a human.

        Idempotent by correlation id: a redelivered decision re-records the
        winner but does not publish a second verdict.
        """
        if self._unresolved_arbitrations.get(correlation_id) is not None:
            return None
        losing = [str(domain) for domain in decision.get("losing_domains") or []]
        winning_domain = str(decision.get("winning_domain", ""))
        grounding = {
            "winning_domain": winning_domain,
            "losing_domains": losing,
            "margin": decision.get("margin"),
        }
        projection = self._pending_decision_cases.pop(correlation_id, None)
        change_assessment = self._pending_change_assessments.pop(correlation_id, None)
        winning_option = (
            projection.option_for_domain(winning_domain) if projection is not None else None
        )
        action_type = (
            winning_option.action_type
            if winning_option is not None and winning_option.action_type is not None
            else ""
        )
        kinetic_proposal, invalid_kinetic_proposal = await self._resolve_kinetic_proposal(
            correlation_id=correlation_id,
            projection=projection,
            action_type=action_type,
        )
        risk_verdict = "deny" if invalid_kinetic_proposal else "hil"
        self._unresolved_arbitrations.set(correlation_id, grounding)
        self.record_behavior(f"verdict:{risk_verdict}")
        self.record_behavior("arbitration_escalated")
        verdict = {
            "producer_principal": "Forseti",
            "correlation_id": correlation_id,
            "idempotency_key": correlation_id,
            "resource_id": self._arbitration_resources.get(correlation_id) or "",
            # Odin's winner is the concrete recommendation under review; the
            # complete DecisionCase keeps every alternative visible.
            "action_type": action_type,
            "risk_verdict": risk_verdict,
            "reason": "arbitration_unresolved",
            "arbitration": grounding,
            "decision_case": (
                _decision_case_mapping(projection, change_assessment)
                if projection is not None
                else None
            ),
            "quorum_required": quorum_for(action_type, self._action_semantics),
            "rollback_contract": rollback_contract_for(action_type, self._action_semantics),
            "initiator_principal": None,
        }
        if kinetic_proposal is not None:
            verdict["params"] = kinetic_proposal.arguments()
            verdict["kinetic_proposal"] = kinetic_proposal.model_dump(mode="json")
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.verdict", verdict)
        return verdict

    async def _resolve_kinetic_proposal(
        self,
        *,
        correlation_id: str,
        projection: _DecisionProjection | None,
        action_type: str,
    ) -> tuple[KineticActionProposal | None, bool]:
        """Resolve exact A0 evidence without creating or upgrading a mutation plan."""

        if self._kinetic_proposal_source is None or not isinstance(
            projection, SpecialistPlanningProjection
        ):
            return None, False
        operational_plan = projection.plan
        try:
            validate_operational_plan_identity(operational_plan)
            proposal = await self._kinetic_proposal_source.resolve(operational_plan)
            if proposal is None:
                return None, False
            if not isinstance(proposal, KineticActionProposal):
                raise ValueError("kinetic proposal source returned an invalid contract")
            proposal = KineticActionProposal.model_validate_json(proposal.model_dump_json())
        except Exception:  # noqa: BLE001 - optional proposal evidence fails closed
            self.record_behavior("kinetic_proposal:invalid")
            return None, True

        selected_option_id = operational_plan.selection.selected_option_id
        selected_option = next(
            (
                option
                for option in operational_plan.decision_case.options
                if option.option_id == selected_option_id
            ),
            None,
        )
        if (
            not operational_plan.complete
            or selected_option_id is None
            or selected_option is None
            or selected_option.action_type != action_type
            or operational_plan.decision_case.correlation_id != correlation_id
            or proposal.correlation_id != correlation_id
            or proposal.process_id != operational_plan.process_id
            or proposal.operational_plan_id != operational_plan.plan_id
            or proposal.selected_option_id != selected_option_id
            or proposal.plan.action_type_ref.name != action_type
            or proposal.target_resource_ref != operational_plan.target_resource_id
        ):
            self.record_behavior("kinetic_proposal:invalid")
            return None, True
        self.record_behavior("kinetic_proposal:resolved")
        return proposal, False

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
            return IntrospectionResult(
                answer="No grounded RCA record is retained by this conversational projection.",
                facts=facts,
            )
        actions = mentioned(question, _RISK_VERDICT)
        if actions:
            action = actions[0]
            verdict = _RISK_VERDICT[action]
            facts.update({"action_type": action, "risk_verdict": verdict})
            answer = f"Action {action!r} has default risk verdict {verdict!r}."
            return IntrospectionResult(answer=answer, facts=facts)
        answer = (
            "I judge events into auto/hil/deny verdicts; "
            f"{len(_RISK_VERDICT)} action verdict(s) and {len(_RULE_MATCH)} "
            "rule match(es) known."
        )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Forseti"]

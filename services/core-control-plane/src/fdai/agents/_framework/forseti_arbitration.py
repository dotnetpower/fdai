"""Cross-vertical arbitration and prospective-lineage judgment for Forseti."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any
from weakref import WeakValueDictionary

from fdai.agents._framework import forseti_durability as _durability
from fdai.agents._framework.action_semantics import (
    ActionSemanticsCatalog,
    quorum_for,
    rollback_contract_for,
)
from fdai.agents._framework.bounded import BoundedLruDict
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.cross_vertical_candidates import (
    INITIAL_VERTICAL_DOMAINS,
    CandidateClosure,
    CrossVerticalCandidateAccumulator,
)
from fdai.agents._framework.forseti_arbitration_contract import (
    arbitration_action_idempotency_key as _arbitration_action_idempotency_key,
)
from fdai.agents._framework.forseti_arbitration_contract import (
    autonomy_ceiling_for_risk_verdict as _autonomy_ceiling_for_risk_verdict,
)
from fdai.agents._framework.forseti_arbitration_contract import (
    remember_arbitration_winner as _remember_winner,
)
from fdai.agents._framework.forseti_arbitration_contract import (
    winning_domain_disposition_allows_resolution as _winning_domain_disposition_allows_resolution,
)
from fdai.agents._framework.forseti_arbitration_planning import (
    finalize_planning_projection as _finalize_planning_projection,
)
from fdai.agents._framework.forseti_constants import _MAX_RESOURCES
from fdai.agents._framework.forseti_cost_annotation import (
    cost_annotation_for_arbitration as _cost_annotation_for_arbitration,
)
from fdai.agents._framework.forseti_cross_vertical_intake import (
    ingest_cross_vertical_candidate_locked,
)
from fdai.agents._framework.forseti_decision_helpers import (
    change_assessment_mapping as _change_assessment_mapping,
)
from fdai.agents._framework.forseti_decision_helpers import (
    decision_case_mapping as _decision_case_mapping,
)
from fdai.agents._framework.forseti_decision_helpers import (
    domain_option_evidence as _domain_option_evidence,
)
from fdai.agents._framework.forseti_decision_helpers import is_conflict as _is_conflict
from fdai.agents._framework.forseti_decision_helpers import source_freshness as _source_freshness
from fdai.agents._framework.forseti_domain_advice import ingest_domain_signal
from fdai.agents._framework.forseti_learned_outputs import ForsetiLearnedOutputMixin
from fdai.agents._framework.forseti_rule_bindings import RISK_VERDICT as _RISK_VERDICT
from fdai.agents._framework.forseti_safeguards import attach_arbitration_safeguards
from fdai.agents._framework.forseti_timeout_tasks import (
    cancel_cross_vertical_timeout,
    start_cross_vertical_timeout,
)
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.core.decision_case import (
    DomainDecisionCoordinator,
    DomainDecisionProjection,
    DomainOptionEvidence,
    conflicting_objective_effects,
)
from fdai.core.operational_context import OperationalContextMaterializer, SourceFreshness
from fdai.core.operational_planning import (
    KineticActionProposal,
    KineticActionProposalSource,
    SpecialistPlanningCoordinator,
    SpecialistPlanningProjection,
    validate_operational_plan_identity,
)
from fdai.core.operational_planning.prospective_lineage import (
    FinalizedProspectiveLineage,
    ProspectiveLineage,
    ProspectiveLineageFinalizer,
)

_LOGGER = logging.getLogger(__name__)

_DecisionProjection = DomainDecisionProjection | SpecialistPlanningProjection


class ForsetiArbitrationMixin(ForsetiLearnedOutputMixin):
    bus: PantheonBus | None
    _action_semantics: ActionSemanticsCatalog | None
    _operational_context: OperationalContextMaterializer | None
    _decision_coordinator: DomainDecisionCoordinator
    _operational_planner: SpecialistPlanningCoordinator | None
    _kinetic_proposal_source: KineticActionProposalSource | None
    _prospective_lineage_finalizer: ProspectiveLineageFinalizer | None
    _agent_availability: Callable[[], Iterable[str]] | None
    _cross_vertical_timeout_seconds: float
    _cross_vertical_candidates: CrossVerticalCandidateAccumulator
    _cross_vertical_timeout_tasks: dict[str, asyncio.Task[None]]
    _cross_vertical_timeout_deadlines: dict[str, float]
    _cross_vertical_timeout_heap: list[tuple[float, str]]
    _cross_vertical_timeout_max: int
    _cross_vertical_locks: WeakValueDictionary[str, asyncio.Lock]
    _pending_arbitration_principals: BoundedLruDict[str, dict[str, str]]
    arbitrations: dict[str, str]
    _unresolved_arbitrations: BoundedLruDict[str, dict[str, Any]]
    _arbitration_resources: BoundedLruDict[str, str]
    _domain_advice: BoundedLruDict[str, dict[str, str]]
    _domain_impact: BoundedLruDict[str, dict[str, float]]
    _domain_observed_at: BoundedLruDict[str, dict[str, str]]
    _domain_correlation_ids: BoundedLruDict[str, dict[str, str]]
    _domain_source_freshness: BoundedLruDict[str, dict[str, tuple[SourceFreshness, ...]]]
    _domain_arguments: BoundedLruDict[str, dict[str, dict[str, object]]]
    _domain_cost_annotations: BoundedLruDict[str, dict[str, Any]]
    _pending_decision_cases: BoundedLruDict[str, _DecisionProjection]
    _pending_change_assessments: BoundedLruDict[str, dict[str, Any]]
    _forseti_state_store: Any | None
    _test_context_clock: Callable[[], datetime]

    def record_behavior(self, name: str, amount: int = 1) -> None:
        raise NotImplementedError

    async def _ingest_cross_vertical_candidate(
        self,
        topic: str,
        payload: dict[str, Any],
    ) -> None:
        """Join the three owner-authenticated candidates and publish one request."""

        correlation_id = str(payload.get("correlation_id") or "")
        lock = self._cross_vertical_locks.setdefault(correlation_id, asyncio.Lock())
        async with lock:
            await self._ingest_cross_vertical_candidate_locked(topic, payload, correlation_id)

    async def _ingest_cross_vertical_candidate_locked(
        self,
        topic: str,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        await ingest_cross_vertical_candidate_locked(self, topic, payload, correlation_id)

    def _start_cross_vertical_timeout(
        self,
        correlation_id: str,
        *,
        delay_seconds: float | None = None,
    ) -> None:
        start_cross_vertical_timeout(self, correlation_id, delay_seconds=delay_seconds)

    async def _cancel_cross_vertical_timeout(
        self,
        timeout: str | asyncio.Task[None],
    ) -> None:
        if isinstance(timeout, str):
            self._cross_vertical_timeout_deadlines.pop(timeout, None)
            return
        await cancel_cross_vertical_timeout(timeout)

    async def _expire_cross_vertical_candidates(self, correlation_id: str) -> None:
        try:
            lock = self._cross_vertical_locks.setdefault(correlation_id, asyncio.Lock())
            async with lock:
                if await _durability.durable_cross_vertical_completed(self, correlation_id):
                    return
                closure = self._cross_vertical_candidates.expire(correlation_id)
                if closure is not None:
                    await self._close_cross_vertical_candidates((closure,))
        finally:
            self._cross_vertical_timeout_deadlines.pop(correlation_id, None)

    async def _close_cross_vertical_candidates(
        self,
        closures: tuple[CandidateClosure, ...],
    ) -> None:
        for closure in closures:
            await self._cancel_cross_vertical_timeout(closure.correlation_id)
            self._arbitration_resources.set(closure.correlation_id, closure.resource_id)
            await _durability.persist_arbitration_resource(
                self,
                closure.correlation_id,
                closure.resource_id,
            )
            await _durability.mark_cross_vertical_completed(
                self, closure.correlation_id, closure.reason
            )
            await self._escalate_arbitration(
                closure.correlation_id,
                {
                    "winning_domain": "",
                    "losing_domains": list(INITIAL_VERTICAL_DOMAINS),
                    "margin": None,
                },
                reason=closure.reason,
                grounding_extra={"candidate_set_complete": False},
            )
            self.record_behavior(f"cross_vertical_candidate:{closure.reason}")

    async def _close_unowned_arbitration(
        self,
        correlation_id: str,
        *,
        domains: list[str],
        arbitration_request: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return await _durability.close_unowned_arbitration(
            self,
            correlation_id,
            domains=domains,
            arbitration_request=arbitration_request,
        )

    async def maybe_request_arbitration(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Raise an ArbitrationRequest when domains contend on the same objective.

        Domain specialists (Njord / Freyr / Loki) may attach advice to an
        event under ``domain_advice`` (``{domain: recommendation}``), and a
        specialist whose own deterministic runtime already produced an
        action may attach ``domain_evidence``: the ActionType it built, the
        signed objective effects it expects, and the canonical lineage both
        were read from.

        When that grounded evidence is present it is the sole basis for the
        conflict: two domains contend only when one and the same objective
        moves in opposite directions, checked over signed utilities by
        :func:`conflicting_objective_effects`. Two different recommendation
        labels are then not enough, so a shared direction vocabulary can
        never manufacture an arbitration. Without grounded evidence the
        older label comparison still applies. Forseti - the sole writer of
        ``object.arbitration-request`` - asks Odin to settle it.
        """
        advice = event.get("domain_advice")
        normalized = (
            {str(key): str(value) for key, value in advice.items()}
            if isinstance(advice, dict)
            else {}
        )
        evidence = _domain_option_evidence(event.get("domain_evidence"))
        objective_conflicts: tuple[tuple[str, str, str], ...] = ()
        if evidence:
            objective_conflicts = conflicting_objective_effects(evidence)
            if not objective_conflicts:
                self.record_behavior("arbitration_declined:objectives_agree")
                return None
            # The ActionType a domain's runtime built is its canonical
            # recommendation; an advice label never overrides it.
            for item in evidence:
                normalized[item.domain] = item.action_type
        elif len(normalized) < 2 or not _is_conflict(normalized):
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
            evidence_by_domain={item.domain: item for item in evidence},
            objective_conflicts=objective_conflicts,
            cost_annotation=(
                _cost_annotation_for_arbitration(event.get("cost_annotation"))
                if isinstance(event.get("cost_annotation"), Mapping)
                else None
            ),
        )

    async def _ingest_domain_signal(
        self, domain: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        return await ingest_domain_signal(self, domain, payload)

    async def _emit_arbitration_request(
        self,
        *,
        resource_id: Any,
        advice: dict[str, str],
        correlation_id: str,
        impacts: dict[str, float] | None = None,
        arguments_by_domain: dict[str, dict[str, object]] | None = None,
        observed_at: str = "",
        change_assessment: dict[str, Any] | None = None,
        source_freshness: tuple[SourceFreshness, ...] = (),
        evidence_by_domain: dict[str, DomainOptionEvidence] | None = None,
        objective_conflicts: tuple[tuple[str, str, str], ...] = (),
        domain_observed_at: dict[str, str] | None = None,
        domain_correlation_ids: dict[str, str] | None = None,
        domain_source_freshness: dict[str, tuple[SourceFreshness, ...]] | None = None,
        cost_annotation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not correlation_id or not str(resource_id or ""):
            raise ValueError("arbitration request identities MUST be non-empty")
        request: dict[str, Any] = {
            "producer_principal": "Forseti",
            "correlation_id": correlation_id,
            "idempotency_key": stable_idempotency_key(
                "forseti-arbitration-request",
                correlation_id,
                resource_id,
                advice,
                domain_observed_at or {},
                domain_correlation_ids or {},
            ),
            "resource_id": resource_id,
            "domains_in_conflict": sorted(advice),
            "advice": advice,
            "impacts": impacts or {},
            "source_correlations": domain_correlation_ids
            or {domain: correlation_id for domain in advice},
            "domain_observed_at": domain_observed_at or {},
            "cost_annotation": _cost_annotation_for_arbitration(cost_annotation),
        }
        if domain_source_freshness:
            request["domain_source_freshness"] = {
                domain: [
                    {
                        "source": item.source,
                        "observed_at": item.observed_at.isoformat(),
                        "max_age_seconds": item.max_age_seconds,
                    }
                    for item in values
                ]
                for domain, values in domain_source_freshness.items()
            }
        if objective_conflicts:
            # The independently computed relation that justified raising
            # this at all, carried so the arbiter and the audit can see
            # which objectives are actually contended.
            request["objective_conflicts"] = [
                {"domains": [left, right], "objective_id": objective_id}
                for left, right, objective_id in objective_conflicts
            ]
        projection = await self._build_domain_decision_projection(
            resource_id=str(resource_id or ""),
            correlation_id=correlation_id,
            advice=advice,
            impacts=impacts or {},
            arguments_by_domain=arguments_by_domain,
            observed_at=observed_at,
            source_freshness=source_freshness,
            evidence_by_domain=evidence_by_domain,
        )
        if projection is not None:
            request["decision_case"] = _decision_case_mapping(projection, change_assessment)
            self._pending_decision_cases.set(correlation_id, projection)
            if change_assessment is not None:
                self._pending_change_assessments.set(correlation_id, change_assessment)
        self._arbitration_resources.set(correlation_id, str(resource_id))
        await _durability.persist_arbitration_resource(self, correlation_id, str(resource_id))
        # Decision semantics: the judge decided to raise arbitration. Recorded
        # independent of a bus (delivery is measured by the bus metrics, not
        # here), so a bus-less unit still measures the decision.
        self.record_behavior("arbitration_requested")
        if self.bus is not None:
            try:
                await self.bus.publish("Forseti", "object.arbitration-request", request)
            except Exception:
                self.record_behavior("arbitration_request:publish_failed")
                closed = await _durability.close_unowned_arbitration(
                    self,
                    correlation_id,
                    domains=sorted(advice),
                    arbitration_request=request,
                )
                if closed is None:
                    raise
                return request
        await _durability.close_unowned_arbitration(
            self,
            correlation_id,
            domains=sorted(advice),
            arbitration_request=request,
        )
        return request

    async def _record_arbitration(self, decision: dict[str, Any]) -> None:
        if decision.get("producer_principal") != "Odin":
            self.record_behavior("arbitration_decision:rejected_owner")
            return
        correlation_id = str(decision.get("correlation_id", ""))
        if not correlation_id:
            self.record_behavior("arbitration_decision:missing_correlation")
            return
        if correlation_id in self.arbitrations:
            self.record_behavior("arbitration_decision:duplicate")
            return
        if await _durability.durable_arbitration_completed(self, correlation_id):
            self.record_behavior("arbitration_decision:duplicate")
            return
        if self._unresolved_arbitrations.get(correlation_id) is not None:
            self.record_behavior("arbitration_decision:duplicate")
            return
        escalated = decision.get("escalate_hil") is True
        winning_domain = str(decision.get("winning_domain") or "")
        if not escalated and not _winning_domain_disposition_allows_resolution(
            decision, winning_domain
        ):
            escalated = True
            self.record_behavior("arbitration_decision:disposition_escalated")
        outcome = "escalated" if escalated else "resolved"
        if await self._settle_advisory_arbitration(correlation_id, decision, outcome=outcome):
            await _durability.mark_arbitration_completed(self, correlation_id, outcome)
            return
        if escalated:
            await self._escalate_arbitration(correlation_id, decision)
            await _durability.mark_arbitration_completed(self, correlation_id, outcome)
            return
        projection = self._pending_decision_cases.get(correlation_id)
        if projection is None:
            resource = self._arbitration_resources.get(
                correlation_id
            ) or await _durability.durable_arbitration_resource(self, correlation_id)
            if resource is not None:
                self._arbitration_resources.set(correlation_id, resource)
                await self._escalate_arbitration(correlation_id, decision)
                await _durability.mark_arbitration_completed(
                    self, correlation_id, "missing_context"
                )
            return
        if projection.selection.requires_human_approval:
            await self._escalate_arbitration(correlation_id, decision)
            return
        change_assessment = self._pending_change_assessments.get(correlation_id)
        if change_assessment is not None and change_assessment.get("review_required") is True:
            await self._escalate_arbitration(correlation_id, decision)
            return
        option = projection.option_for_domain(winning_domain)
        eligible_options = {
            option_id for option_id, _score in projection.selection.objective_scores
        }
        if option is None or option.option_id not in eligible_options or option.action_type is None:
            await self._escalate_arbitration(correlation_id, decision)
            return
        projection, planning_invalid = await _finalize_planning_projection(
            self,
            projection,
            selected_option_id=option.option_id,
        )
        await self._publish_resolved_arbitration_verdict(
            correlation_id=correlation_id,
            decision=decision,
            projection=projection,
            action_type=option.action_type,
            planning_invalid=planning_invalid,
        )
        _remember_winner(self.arbitrations, correlation_id, winning_domain, _MAX_RESOURCES)
        await _durability.mark_arbitration_completed(self, correlation_id, "resolved")

    async def _build_domain_decision_projection(
        self,
        *,
        resource_id: str,
        correlation_id: str,
        advice: dict[str, str],
        impacts: dict[str, float],
        arguments_by_domain: dict[str, dict[str, object]] | None,
        observed_at: str,
        source_freshness: tuple[SourceFreshness, ...],
        evidence_by_domain: dict[str, DomainOptionEvidence] | None = None,
    ) -> DomainDecisionProjection | SpecialistPlanningProjection | None:
        if self._mark_advisory_arbitration(correlation_id, advice):
            return None
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
                    arguments_by_domain=arguments_by_domain,
                    created_at=cutoff,
                    evidence_by_domain=evidence_by_domain,
                )
            return self._decision_coordinator.build(
                correlation_id=correlation_id,
                context=context,
                advice=advice,
                impacts=impacts,
                created_at=cutoff,
                arguments_by_domain=arguments_by_domain,
                evidence_by_domain=evidence_by_domain,
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
        planning_invalid: bool = False,
    ) -> None:
        self._pending_decision_cases.pop(correlation_id, None)
        risk_verdict = _RISK_VERDICT.get(action_type, "hil")
        (
            kinetic_proposal,
            prospective_lineage,
            invalid_kinetic_proposal,
        ) = await self._resolve_kinetic_proposal(
            correlation_id=correlation_id,
            projection=projection,
            action_type=action_type,
        )
        if invalid_kinetic_proposal or planning_invalid:
            risk_verdict = "deny"
        resource_id = self._arbitration_resources.get(correlation_id) or ""
        action_idempotency_key = _arbitration_action_idempotency_key(
            correlation_id,
            action_type,
            projection.selection.selected_option_id or "",
            resource_id,
            kinetic_proposal.proposal_id if kinetic_proposal is not None else "",
        )
        rollback_contract = rollback_contract_for(action_type, self._action_semantics)
        verdict = {
            "producer_principal": "Forseti",
            "correlation_id": correlation_id,
            "idempotency_key": stable_idempotency_key(
                "forseti-arbitration-verdict",
                correlation_id,
                action_type,
                self._arbitration_resources.get(correlation_id) or "",
            ),
            "action_idempotency_key": action_idempotency_key,
            "resource_id": resource_id,
            "action_type": action_type,
            "risk_verdict": risk_verdict,
            "resolved_autonomy_ceiling": _autonomy_ceiling_for_risk_verdict(risk_verdict),
            "reason": "arbitration_resolved",
            "arbitration": {
                "winning_domain": decision.get("winning_domain"),
                "losing_domains": decision.get("losing_domains") or [],
                "margin": decision.get("margin"),
            },
            "cost_annotation": _cost_annotation_for_arbitration(decision.get("cost_annotation")),
            "decision_case": _decision_case_mapping(
                projection,
                self._pending_change_assessments.pop(correlation_id, None),
            ),
            "quorum_required": quorum_for(action_type, self._action_semantics),
            "rollback_contract": rollback_contract,
            "initiator_principal": (
                self._pending_arbitration_principals.pop(correlation_id, {}) or {}
            ).get(str(decision.get("winning_domain") or "")),
        }
        attach_arbitration_safeguards(
            verdict,
            risk_verdict,
            action_type,
            action_idempotency_key,
            resource_id,
            rollback_contract,
        )
        if kinetic_proposal is not None:
            verdict["params"] = kinetic_proposal.arguments()
            verdict["kinetic_proposal"] = kinetic_proposal.model_dump(mode="json")
        if prospective_lineage is not None:
            verdict["prospective_lineage"] = prospective_lineage.model_dump(mode="json")
        self.record_behavior(f"verdict:{risk_verdict}")
        self.record_behavior("arbitration_resolved")
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.verdict", verdict)

    async def _escalate_arbitration(
        self,
        correlation_id: str,
        decision: dict[str, Any],
        *,
        reason: str = "arbitration_unresolved",
        grounding_extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Turn an unresolved arbitration into a human-visible verdict.

        Near-ties, unknown domains, invalid impacts, and unavailable arbitration
        ownership fail toward safety as HIL. Idempotency is by correlation:
        once unresolved or settled, redelivery cannot publish another verdict
        or reopen the closure.
        """
        if reason != "arbitration_owner_unavailable":
            if await self._settle_advisory_arbitration(
                correlation_id,
                decision,
                outcome=reason,
                grounding_extra=grounding_extra,
            ):
                return None
        if self._unresolved_arbitrations.get(correlation_id) is not None:
            return None
        losing = [str(domain) for domain in decision.get("losing_domains") or []]
        winning_domain = str(decision.get("winning_domain", ""))
        grounding = {
            "winning_domain": winning_domain,
            "losing_domains": losing,
            "margin": decision.get("margin"),
        }
        if grounding_extra is not None:
            grounding.update(dict(grounding_extra))
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
        planning_invalid = False
        if projection is not None and winning_option is not None:
            projection, planning_invalid = await _finalize_planning_projection(
                self,
                projection,
                selected_option_id=winning_option.option_id,
            )
        (
            kinetic_proposal,
            prospective_lineage,
            invalid_kinetic_proposal,
        ) = await self._resolve_kinetic_proposal(
            correlation_id=correlation_id,
            projection=projection,
            action_type=action_type,
        )
        risk_verdict = "deny" if invalid_kinetic_proposal or planning_invalid else "hil"
        self._unresolved_arbitrations.set(correlation_id, grounding)
        self.record_behavior(f"verdict:{risk_verdict}")
        self.record_behavior("arbitration_escalated")
        principals = self._pending_arbitration_principals.pop(correlation_id, {}) or {}
        resource_id = self._arbitration_resources.get(correlation_id) or ""
        action_idempotency_key = _arbitration_action_idempotency_key(
            correlation_id,
            action_type,
            winning_option.option_id if winning_option is not None else "",
            resource_id,
            kinetic_proposal.proposal_id if kinetic_proposal is not None else "",
        )
        rollback_contract = rollback_contract_for(action_type, self._action_semantics)
        verdict = {
            "producer_principal": "Forseti",
            "correlation_id": correlation_id,
            "idempotency_key": stable_idempotency_key(
                "forseti-arbitration-verdict",
                correlation_id,
                action_type,
                self._arbitration_resources.get(correlation_id) or "",
                reason,
            ),
            "action_idempotency_key": action_idempotency_key,
            "resource_id": resource_id,
            # Odin's winner is the concrete recommendation under review; the
            # complete DecisionCase keeps every alternative visible.
            "action_type": action_type,
            "risk_verdict": risk_verdict,
            "reason": reason,
            "arbitration": grounding,
            "cost_annotation": _cost_annotation_for_arbitration(decision.get("cost_annotation")),
            "decision_case": (
                _decision_case_mapping(projection, change_assessment)
                if projection is not None
                else None
            ),
            "quorum_required": quorum_for(action_type, self._action_semantics),
            "rollback_contract": rollback_contract,
            "initiator_principal": principals.get(winning_domain),
        }
        attach_arbitration_safeguards(
            verdict,
            risk_verdict,
            action_type,
            action_idempotency_key,
            resource_id,
            rollback_contract,
        )
        if kinetic_proposal is not None:
            verdict["params"] = kinetic_proposal.arguments()
            verdict["kinetic_proposal"] = kinetic_proposal.model_dump(mode="json")
        if prospective_lineage is not None:
            verdict["prospective_lineage"] = prospective_lineage.model_dump(mode="json")
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.verdict", verdict)
        if winning_domain:
            _remember_winner(self.arbitrations, correlation_id, winning_domain, _MAX_RESOURCES)
        return verdict

    async def _resolve_kinetic_proposal(
        self,
        *,
        correlation_id: str,
        projection: _DecisionProjection | None,
        action_type: str,
    ) -> tuple[KineticActionProposal | None, ProspectiveLineage | None, bool]:
        """Resolve exact A0 evidence without creating or upgrading a mutation plan."""

        if not isinstance(projection, SpecialistPlanningProjection):
            return None, None, False
        operational_plan = projection.plan
        finalized: FinalizedProspectiveLineage | None = None
        proposal: KineticActionProposal | None
        try:
            validate_operational_plan_identity(operational_plan)
            if self._prospective_lineage_finalizer is not None:
                finalized = await self._prospective_lineage_finalizer.finalize(projection)
                proposal = finalized.proposal
            elif self._kinetic_proposal_source is not None:
                proposal = await self._kinetic_proposal_source.resolve(operational_plan)
            else:
                return None, None, False
            if proposal is None:
                return None, None, False
            if not isinstance(proposal, KineticActionProposal):
                raise ValueError("kinetic proposal source returned an invalid contract")
            proposal = KineticActionProposal.model_validate_json(proposal.model_dump_json())
        except Exception:  # noqa: BLE001 - optional proposal evidence fails closed
            self.record_behavior("kinetic_proposal:invalid")
            return None, None, True

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
            or selected_option.arguments is None
            or proposal.arguments_digest != selected_option.arguments.arguments_digest
        ):
            self.record_behavior("kinetic_proposal:invalid")
            return None, None, True
        self.record_behavior("kinetic_proposal:resolved")
        envelope = finalized.envelope if finalized is not None else None
        if envelope is not None:
            if self.bus is None:
                self.record_behavior("prospective_lineage:bus_unavailable")
                return None, None, True
            await self.bus.publish(
                "Forseti",
                "object.prospective-lineage",
                {
                    **envelope.model_dump(mode="json"),
                    "idempotency_key": envelope.id,
                    "resource_id": proposal.target_resource_ref,
                },
            )
            self.record_behavior("prospective_lineage:published")
        return proposal, envelope, False

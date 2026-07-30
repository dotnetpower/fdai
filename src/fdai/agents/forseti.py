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
from typing import Any

from fdai.agents._framework.action_semantics import (
    ActionSemanticsCatalog,
    quorum_for,
    rollback_contract_for,
)
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    mentioned,
)
from fdai.agents._framework.pantheon import _FORSETI
from fdai.agents._framework.specialist_ingress import SPECIALIST_EVENT_PREFIX
from fdai.core.decision_case import DomainDecisionCoordinator, DomainDecisionProjection
from fdai.core.operational_context import OperationalContextMaterializer, SourceFreshness
from fdai.core.readiness import AuthorityCeiling, DetectionReadinessDecision

# ---------------------------------------------------------------------------
# Deterministic tables (wave 3 defaults)
# ---------------------------------------------------------------------------

# ``event_type -> proposed ActionType id`` (rule match). Wave 3 uses a
# tiny in-memory table; real T0 loader consumes rule catalog YAML.
_RULE_MATCH: dict[str, str] = {
    "public_network_enabled": "remediate.disable-public-access",
    "unencrypted_disk": "remediate.enable-encryption",
    "restart_needed": "ops.restart-service",
    "chaos_experiment_request": "ops.restart-service",
    "control_plane.t2_proposer_failure": "ops.switch-t2-proposer-route",
}

# ``ActionType id -> default risk verdict`` (deterministic per
# rule-catalog/risk-classification.yaml). Wave 3 hard-codes a small
# lookup; real loader parses the full first-match table.
_RISK_VERDICT: dict[str, str] = {
    "remediate.disable-public-access": "auto",
    "remediate.enable-encryption": "hil",
    "ops.restart-service": "auto",
    "governance.notify-admin-privilege-violation": "auto",
    "ops.failover-primary": "hil",
    "ops.switch-t2-proposer-route": "hil",
    "remediate.delete-storage": "deny",  # irreversible
}

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


class Forseti(Agent):
    """Wave-3 Forseti: rule match + risk verdict + RBAC + SecurityEvent."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        rbac: dict[str, frozenset[str]] | None = None,
        action_semantics: ActionSemanticsCatalog | None = None,
        operational_context: OperationalContextMaterializer | None = None,
        decision_coordinator: DomainDecisionCoordinator | None = None,
    ) -> None:
        super().__init__(spec=_FORSETI)
        self.bus = bus
        self._rbac = rbac if rbac is not None else _DEFAULT_RBAC
        self._action_semantics = action_semantics
        self._operational_context = operational_context
        self._decision_coordinator = decision_coordinator or DomainDecisionCoordinator()
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
        self._pending_decision_cases: BoundedLruDict[str, DomainDecisionProjection] = (
            BoundedLruDict(_MAX_RESOURCES)
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
            await self.maybe_request_arbitration(payload)
            await self.judge(payload)
        elif topic == "object.cost-anomaly":
            await self._ingest_domain_signal("cost", payload)
        elif topic == "object.capacity-forecast":
            await self._ingest_domain_signal("capacity", payload)
        elif topic == "object.arbitration-decision":
            await self._record_arbitration(payload)

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
        )
        if projection is not None:
            request["decision_case"] = projection.to_mapping()
            self._pending_decision_cases.set(correlation_id, projection)
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
        projection = self._pending_decision_cases.pop(correlation_id, None)
        if projection is None:
            if self._arbitration_resources.get(correlation_id) is not None:
                await self._escalate_arbitration(correlation_id, decision)
            return
        if projection.selection.requires_human_approval:
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
    ) -> DomainDecisionProjection | None:
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
            )
            if context.review_required:
                return None
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
        projection: DomainDecisionProjection,
        action_type: str,
    ) -> None:
        risk_verdict = _RISK_VERDICT.get(action_type, "hil")
        verdict = {
            "producer_principal": "Forseti",
            "correlation_id": correlation_id,
            "resource_id": self._arbitration_resources.get(correlation_id) or "",
            "action_type": action_type,
            "risk_verdict": risk_verdict,
            "reason": "arbitration_resolved",
            "arbitration": {
                "winning_domain": decision.get("winning_domain"),
                "losing_domains": decision.get("losing_domains") or [],
                "margin": decision.get("margin"),
            },
            "decision_case": projection.to_mapping(),
            "quorum_required": quorum_for(action_type, self._action_semantics),
            "rollback_contract": rollback_contract_for(action_type, self._action_semantics),
            "initiator_principal": None,
        }
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
        winning_option = (
            projection.option_for_domain(winning_domain) if projection is not None else None
        )
        action_type = (
            winning_option.action_type
            if winning_option is not None and winning_option.action_type is not None
            else ""
        )
        self._unresolved_arbitrations.set(correlation_id, grounding)
        self.record_behavior("verdict:hil")
        self.record_behavior("arbitration_escalated")
        verdict = {
            "producer_principal": "Forseti",
            "correlation_id": correlation_id,
            "resource_id": self._arbitration_resources.get(correlation_id) or "",
            # Odin's winner is the concrete recommendation under review; the
            # complete DecisionCase keeps every alternative visible.
            "action_type": action_type,
            "risk_verdict": "hil",
            "reason": "arbitration_unresolved",
            "arbitration": grounding,
            "decision_case": projection.to_mapping() if projection is not None else None,
            "quorum_required": quorum_for(action_type, self._action_semantics),
            "rollback_contract": rollback_contract_for(action_type, self._action_semantics),
            "initiator_principal": None,
        }
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.verdict", verdict)
        return verdict

    # ---- judgment ------------------------------------------------------

    async def judge_document_ingestion(self, event: dict[str, Any]) -> dict[str, Any]:
        """Admit a validated upload into the mandatory safety pipeline.

        This is not an action verdict: it carries a kind discriminator and no
        action type. Thor ignores it, while the ingestion gateway consumes it
        to unlock the scan phase. Later gates issue their own document verdicts.
        """
        correlation_id = str(event.get("correlation_id") or "")
        document_id = str(event.get("document_id") or event.get("resource_id") or "")
        record = event.get("record")
        upload_id = str(record.get("upload_id") or "") if isinstance(record, dict) else ""
        complete = bool(correlation_id and document_id and upload_id)
        decision = "admit" if complete else "hold"
        reason = "ingress_validated" if complete else "invalid_ingress_envelope"
        self.record_behavior(f"document_ingestion:{decision}")
        verdict = {
            "producer_principal": "Forseti",
            "kind": "document_ingestion",
            "stage": "received",
            "decision": decision,
            "reason": reason,
            "correlation_id": correlation_id or document_id,
            "resource_id": document_id,
            "document_id": document_id,
            "upload_id": upload_id,
            "idempotency_key": str(event.get("idempotency_key") or ""),
        }
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.verdict", verdict)
        return verdict

    async def judge_document_safety(self, signal: dict[str, Any]) -> dict[str, Any]:
        """Issue the protection verdict from Heimdall's normalized signal."""
        complete = bool(
            signal.get("correlation_id") and signal.get("document_id") and signal.get("upload_id")
        )
        clear = complete and signal.get("safety_status") == "clear"
        purposes = {str(value) for value in signal.get("purposes") or []}
        requires_approval = bool(signal.get("sensitivity_label")) or bool(
            purposes & {"handover_bootstrap", "manual_distillation"}
        )
        decision = "hil" if clear and requires_approval else ("admit" if clear else "hold")
        reason = (
            "sensitive_or_authoritative_document"
            if decision == "hil"
            else "safety_checks_passed"
            if decision == "admit"
            else str(
                signal.get("failure_code")
                or signal.get("protection_state")
                or "invalid_safety_signal"
            )
        )
        self.record_behavior(f"document_safety:{decision}")
        verdict = {
            "producer_principal": "Forseti",
            "kind": "document_ingestion",
            "stage": "protection_check",
            "decision": decision,
            "reason": reason,
            "correlation_id": str(signal.get("correlation_id") or ""),
            "resource_id": str(signal.get("resource_id") or ""),
            "document_id": str(signal.get("document_id") or ""),
            "upload_id": str(signal.get("upload_id") or ""),
            "initiator_principal": str(signal.get("initiator_principal") or ""),
            "idempotency_key": str(signal.get("idempotency_key") or ""),
        }
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.verdict", verdict)
        return verdict

    async def judge(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Emit a Verdict on the bus. Returns the verdict payload."""
        # An operator proposal (conversational-port re-entry, 7.7) names the
        # ActionType directly; a rule-fired signal carries an ``event_type``
        # Forseti maps to one. Prefer the direct action_type, fall back to the
        # rule-match table.
        action_type = event.get("action_type")
        if action_type is None:
            event_type = str(event.get("event_type", ""))
            action_type = _RULE_MATCH.get(event_type)
        if action_type is None:
            # No rule match. Fail toward safety (agent-pantheon rule 4.7): an
            # identifiable incident we cannot resolve MUST NOT vanish - route
            # it to HIL so a human triages it. Wave 3 has no T1/T2 escalation,
            # so HIL is the safe terminal for an unresolved event.
            self.record_behavior("no_rule_match")
            resource_id = event.get("resource_id")
            correlation_id = str(event.get("correlation_id", ""))
            if not resource_id or not correlation_id:
                # Not a trackable, actionable incident (no concrete resource
                # target or no correlation id) - there is nothing for a human
                # to triage. Recorded via the ``no_rule_match`` counter and
                # abstained, so a flood of malformed / junk payloads cannot
                # manufacture HIL items (DoS resistance). Dropping malformed
                # ingress is the event-ingest boundary's job, not the judge's.
                return None
            # A concrete resource target with no matching rule -> HIL triage.
            self.record_behavior("verdict:hil")
            verdict = {
                "producer_principal": "Forseti",
                "correlation_id": correlation_id,
                "resource_id": resource_id,
                # No concrete ActionType maps; a human decides what (if
                # anything) to do. Empty string (not None) so Thor's ``str()``
                # coercion yields "" rather than the literal "None".
                "action_type": "",
                "risk_verdict": "hil",
                "reason": "no_rule_match",
                # No known irreversible action; the single-approver default.
                "quorum_required": 1,
                "initiator_principal": event.get("initiator_principal"),
            }
            if self.bus is not None:
                await self.bus.publish("Forseti", "object.verdict", verdict)
            return verdict
        action_type = str(action_type)

        initiator = str(event.get("initiator_principal", event.get("producer_principal", "")))
        risk_verdict = _RISK_VERDICT.get(action_type, "hil")

        # RBAC check: if initiator is set (e.g. operator-requested action),
        # verify permission. Rule-fired actions have no operator initiator;
        # they are always subject to risk_verdict only. An operator-initiated
        # proposal whose initiator is unknown to the RBAC seam fails closed to
        # ``deny`` (never silently allowed) - the conversational port must not
        # widen privilege.
        rbac_denied = False
        if initiator and initiator in self._rbac:
            allowed = self._rbac[initiator]
            if action_type not in allowed:
                await self._emit_security_event(
                    event=event,
                    initiator=initiator,
                    action_type=action_type,
                )
                risk_verdict = "deny"
                rbac_denied = True
        elif event.get("operator_initiated") is True and initiator not in self._rbac:
            await self._emit_security_event(
                event=event,
                initiator=initiator,
                action_type=action_type,
            )
            risk_verdict = "deny"
            rbac_denied = True

        readiness = self._detection_readiness.get(str(event.get("resource_id") or ""))
        readiness_limited = bool(
            readiness
            and readiness["authority_ceiling"] in {"disabled", "deterministic_fallback", "shadow"}
            and risk_verdict == "auto"
        )
        if readiness_limited:
            risk_verdict = "hil"

        # An arbitration Odin could not settle leaves the resource contested.
        # Judging a later event on that correlation as auto would execute a
        # change while the domain conflict behind it is still with a human.
        arbitration_limited = bool(
            risk_verdict == "auto"
            and self._unresolved_arbitrations.get(str(event.get("correlation_id") or ""))
            is not None
        )
        if arbitration_limited:
            risk_verdict = "hil"

        if risk_verdict == "deny":
            reason = "rbac_insufficient" if rbac_denied else "risk_deny"
        elif readiness_limited:
            reason = "detection_readiness_ceiling"
        elif arbitration_limited:
            reason = "arbitration_unresolved"
        else:
            reason = "rule_match"
        verdict = {
            "producer_principal": "Forseti",
            "correlation_id": event.get("correlation_id", ""),
            "resource_id": event.get("resource_id"),
            "action_type": action_type,
            "risk_verdict": risk_verdict,
            "reason": reason,
            "detection_readiness": readiness,
            # Distinct-approver quorum: an irreversible action MUST clear two
            # approvers (agent-pantheon.md 4.6). The judge sets it on the
            # verdict; Thor propagates it onto the ActionRun and Var enforces
            # it. Reversible actions carry the single-approver default. This
            # rides along even on a deny verdict (harmless, and correct if a
            # fork's risk table routes the same action to hil instead).
            "quorum_required": quorum_for(action_type, self._action_semantics),
            "rollback_contract": rollback_contract_for(
                action_type,
                self._action_semantics,
            ),
            # Propagate the operator initiator (None for rule-fired) so the
            # approver principal downstream can enforce no-self-approval.
            "initiator_principal": event.get("initiator_principal"),
        }
        await self._attach_operational_context(event, verdict)
        # Measurable behaviour records the final verdict after every
        # never-raising context ceiling has been applied.
        self.record_behavior(f"verdict:{verdict['risk_verdict']}")
        if rbac_denied:
            self.record_behavior("rbac_denied")
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.verdict", verdict)
        return verdict

    async def _attach_operational_context(
        self,
        event: dict[str, Any],
        verdict: dict[str, Any],
    ) -> None:
        materializer = self._operational_context
        if materializer is None:
            return
        resource_id = str(event.get("resource_id") or "")
        detected_at = event.get("detected_at")
        if not resource_id or not isinstance(detected_at, str):
            self._hold_for_context(verdict, "operational_context_input_missing")
            return
        try:
            cutoff = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
            if cutoff.tzinfo is None:
                raise ValueError("detected_at MUST be timezone-aware")
            raw_versions = event.get("catalog_versions")
            versions = (
                {str(key): str(value) for key, value in raw_versions.items()}
                if isinstance(raw_versions, Mapping)
                else {}
            )
            freshness = _source_freshness(event.get("source_freshness"))
            snapshot = await materializer.materialize(
                target_resource_id=resource_id,
                cutoff=cutoff,
                catalog_versions=versions,
                source_freshness=freshness,
            )
        except (TypeError, ValueError):
            self._hold_for_context(verdict, "operational_context_invalid")
            return
        except Exception:  # noqa: BLE001 - optional context failure lowers authority
            self.record_behavior("operational_context_failed")
            self._hold_for_context(verdict, "operational_context_unavailable")
            return
        verdict["operational_context"] = {
            "snapshot_id": snapshot.snapshot_id,
            "service_ids": list(snapshot.service_ids),
            "workload_ids": list(snapshot.workload_ids),
            "objective_ids": list(snapshot.objective_ids),
            "constraint_ids": list(snapshot.constraint_ids),
            "stale_sources": list(snapshot.stale_sources),
            "conflicts": list(snapshot.conflicts),
            "autonomy_ceiling": snapshot.autonomy_ceiling.value,
        }
        if snapshot.review_required:
            self._hold_for_context(verdict, "operational_context_ceiling")

    @staticmethod
    def _hold_for_context(verdict: dict[str, Any], reason: str) -> None:
        if verdict.get("risk_verdict") == "auto":
            verdict["risk_verdict"] = "hil"
            verdict["reason"] = reason

    async def _emit_security_event(
        self,
        *,
        event: dict[str, Any],
        initiator: str,
        action_type: str,
    ) -> None:
        # Decision semantics: the judge decided this is a privilege-escalation
        # attempt. Recorded regardless of a bus so a bus-less unit measures
        # the decision; delivery is the bus's concern (published / errors).
        self.record_behavior("security_event")
        if self.bus is None:
            return
        await self.bus.publish(
            "Forseti",
            "object.security-event",
            {
                "producer_principal": "Forseti",
                "correlation_id": event.get("correlation_id", ""),
                "event_type": "privilege_escalation_attempt",
                "initiator_principal": initiator,
                "attempted_action": action_type,
                "target_resource": event.get("resource_id"),
                "severity_hint": "high" if action_type == "remediate.delete-storage" else "medium",
            },
        )

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
        normalized_question = question.casefold()
        if "rca" in normalized_question or "root cause" in normalized_question:
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


def _is_conflict(advice: dict[str, str]) -> bool:
    """True when >=2 domains give >=2 distinct actionable recommendations.

    ``hold`` is not actionable, so it never creates a conflict on its own.
    """
    active = {domain: rec for domain, rec in advice.items() if rec != "hold"}
    return len(active) >= 2 and len(set(active.values())) >= 2


def _signal_impact(domain: str, payload: dict[str, Any]) -> float:
    """Read the impact magnitude in [0, 1] from a domain signal.

    The domain specialist (Njord, Freyr, ...) is the authority: it owns
    per-domain normalization and MUST attach an explicit ``impact`` field
    to the payload it publishes. Forseti simply forwards it.

    Raw-metric fallbacks (``ratio`` for cost, ``forecast_util`` for
    capacity) exist only for backward compatibility with a fork publisher
    that has not yet migrated. Absent any magnitude the impact defaults
    to 1.0 so the call collapses to the priority order.
    """
    explicit = payload.get("impact")
    if explicit is not None:
        try:
            return max(0.0, min(1.0, float(explicit)))
        except (TypeError, ValueError):
            pass
    # Legacy fallbacks (kept for pre-migration fork publishers).
    if domain == "cost" and "ratio" in payload:
        try:
            return max(0.0, min(1.0, float(payload["ratio"]) - 1.0))
        except (TypeError, ValueError):
            return 1.0
    if domain == "capacity" and "forecast_util" in payload:
        try:
            return max(0.0, min(1.0, float(payload["forecast_util"])))
        except (TypeError, ValueError):
            return 1.0
    return 1.0


def _source_freshness(raw: object) -> tuple[SourceFreshness, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("source_freshness MUST be an array")
    items: list[SourceFreshness] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("source_freshness entries MUST be objects")
        observed_at = item.get("observed_at")
        if not isinstance(observed_at, str):
            raise ValueError("source_freshness observed_at MUST be a timestamp")
        items.append(
            SourceFreshness(
                source=str(item.get("source") or ""),
                observed_at=datetime.fromisoformat(observed_at.replace("Z", "+00:00")),
                max_age_seconds=int(item.get("max_age_seconds") or 0),
            )
        )
    return tuple(items)

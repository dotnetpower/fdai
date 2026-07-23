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
    ) -> None:
        super().__init__(spec=_FORSETI)
        self.bus = bus
        self._rbac = rbac if rbac is not None else _DEFAULT_RBAC
        self._action_semantics = action_semantics
        # Latest arbitration winner per correlation id (populated when Odin
        # resolves a cross-vertical conflict Forseti raised).
        self.arbitrations: dict[str, str] = {}
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

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    # ---- typed port ----------------------------------------------------

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if payload.get("kind") == "document_ingestion":
            if topic == "object.event" and payload.get("event_type") == "document.received":
                await self.judge_document_ingestion(payload)
            elif topic == "object.anomaly" and payload.get("stage") == "protection_check":
                await self.judge_document_safety(payload)
            return
        if topic in ("object.event", "object.anomaly", "object.drift"):
            await self.maybe_request_arbitration(payload)
            await self.judge(payload)
        elif topic == "object.cost-anomaly":
            await self._ingest_domain_signal("cost", payload)
        elif topic == "object.capacity-forecast":
            await self._ingest_domain_signal("capacity", payload)
        elif topic == "object.arbitration-decision":
            self._record_arbitration(payload)

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
        return await self._emit_arbitration_request(
            resource_id=event.get("resource_id"),
            advice=normalized,
            correlation_id=str(event.get("correlation_id", "")),
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
        if not _is_conflict(advice):
            return None
        request = await self._emit_arbitration_request(
            resource_id=resource_id,
            advice=dict(advice),
            correlation_id=str(payload.get("correlation_id", "")),
            impacts=dict(impacts),
        )
        # Consume the accumulated advice once the conflict is surfaced.
        # Leaving it in place would (a) grow both maps without bound over
        # every resource ever seen (memory leak) and (b) make the stale
        # opposing recommendation re-trigger a duplicate arbitration on the
        # very next signal for this resource. Fresh signals re-accumulate.
        self._domain_advice.pop(resource_id, None)
        self._domain_impact.pop(resource_id, None)
        return request

    async def _emit_arbitration_request(
        self,
        *,
        resource_id: Any,
        advice: dict[str, str],
        correlation_id: str,
        impacts: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        request = {
            "producer_principal": "Forseti",
            "correlation_id": correlation_id,
            "resource_id": resource_id,
            "domains_in_conflict": sorted(advice),
            "advice": advice,
            "impacts": impacts or {},
        }
        # Decision semantics: the judge decided to raise arbitration. Recorded
        # independent of a bus (delivery is measured by the bus metrics, not
        # here), so a bus-less unit still measures the decision.
        self.record_behavior("arbitration_requested")
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.arbitration-request", request)
        return request

    def _record_arbitration(self, decision: dict[str, Any]) -> None:
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

        if risk_verdict == "deny":
            reason = "rbac_insufficient" if rbac_denied else "risk_deny"
        else:
            reason = "rule_match"
        # Measurable behaviour: the verdict distribution + why. A scenario
        # test reads verdict:auto / verdict:hil / verdict:deny counts and the
        # rbac_denied tally to assert invariants (deny never auto, an RBAC
        # violation always denies) without touching private state.
        self.record_behavior(f"verdict:{risk_verdict}")
        if rbac_denied:
            self.record_behavior("rbac_denied")
        verdict = {
            "producer_principal": "Forseti",
            "correlation_id": event.get("correlation_id", ""),
            "resource_id": event.get("resource_id"),
            "action_type": action_type,
            "risk_verdict": risk_verdict,
            "reason": reason,
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
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.verdict", verdict)
        return verdict

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

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "known_action_verdicts": dict(_RISK_VERDICT),
            "rule_matches": dict(_RULE_MATCH),
            "arbitrations_recorded": len(self.arbitrations),
        }
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

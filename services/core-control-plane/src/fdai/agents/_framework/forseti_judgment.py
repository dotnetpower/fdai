"""Deterministic judgment and context ceilings executed by Forseti."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai.agents._framework.action_semantics import (
    ActionSemanticsCatalog,
    quorum_for,
    rollback_contract_for,
)
from fdai.agents._framework.bounded import BoundedLruDict
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.forseti_decision_helpers import copy_change_assessment, source_freshness
from fdai.core.operational_context import OperationalContextMaterializer
from fdai.shared.contracts.models import Autonomy

RULE_MATCH: dict[str, str] = {
    "public_network_enabled": "remediate.disable-public-access",
    "unencrypted_disk": "remediate.enable-encryption",
    "restart_needed": "ops.restart-service",
    "chaos_experiment_request": "ops.restart-service",
    "control_plane.t2_proposer_failure": "ops.switch-t2-proposer-route",
}

RISK_VERDICT: dict[str, str] = {
    "remediate.disable-public-access": "auto",
    "remediate.enable-encryption": "hil",
    "ops.restart-service": "auto",
    "governance.notify-admin-privilege-violation": "auto",
    "ops.failover-primary": "hil",
    "ops.switch-t2-proposer-route": "hil",
    "remediate.delete-storage": "deny",
}


class ForsetiJudgmentMixin:
    """Issue deterministic Verdicts and lower authority on missing evidence."""

    bus: PantheonBus | None
    arbitrations: dict[str, str]
    _action_semantics: ActionSemanticsCatalog | None
    _detection_readiness: BoundedLruDict[str, dict[str, str]]
    _operational_context: OperationalContextMaterializer | None
    _rbac: dict[str, frozenset[str]]
    _unresolved_arbitrations: BoundedLruDict[str, dict[str, Any]]

    def record_behavior(self, name: str, amount: int = 1) -> None:
        raise NotImplementedError

    async def judge_document_ingestion(self, event: dict[str, Any]) -> dict[str, Any]:
        """Admit a validated upload into the mandatory safety pipeline."""
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
        action_type = event.get("action_type")
        if action_type is None:
            action_type = RULE_MATCH.get(str(event.get("event_type", "")))
        if action_type is None:
            self.record_behavior("no_rule_match")
            resource_id = event.get("resource_id")
            correlation_id = str(event.get("correlation_id", ""))
            if not resource_id or not correlation_id:
                return None
            self.record_behavior("verdict:hil")
            verdict = {
                "producer_principal": "Forseti",
                "correlation_id": correlation_id,
                "idempotency_key": str(event.get("idempotency_key") or correlation_id),
                "resource_id": resource_id,
                "action_type": "",
                "risk_verdict": "hil",
                "resolved_autonomy_ceiling": Autonomy.SHADOW_ONLY.value,
                "reason": "no_rule_match",
                "quorum_required": 1,
                "initiator_principal": event.get("initiator_principal"),
            }
            copy_change_assessment(event, verdict)
            if self.bus is not None:
                await self.bus.publish("Forseti", "object.verdict", verdict)
            return verdict
        action_type = str(action_type)

        initiator = str(event.get("initiator_principal", event.get("producer_principal", "")))
        risk_verdict = RISK_VERDICT.get(action_type, "hil")
        explicit_hil = event.get("human_approval_required") is True
        if explicit_hil:
            risk_verdict = "hil"
        chaos_evidence_incomplete = (
            event.get("event_type") == "chaos_experiment_request"
            and event.get("evidence_complete") is not True
        )
        if chaos_evidence_incomplete:
            risk_verdict = "deny"

        rbac_denied = False
        if initiator and initiator in self._rbac:
            if action_type not in self._rbac[initiator]:
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
        arbitration_limited = bool(
            risk_verdict == "auto"
            and self._unresolved_arbitrations.get(str(event.get("correlation_id") or ""))
            is not None
        )
        if arbitration_limited:
            risk_verdict = "hil"

        if risk_verdict == "deny":
            reason = (
                "rbac_insufficient"
                if rbac_denied
                else "chaos_evidence_incomplete"
                if chaos_evidence_incomplete
                else "risk_deny"
            )
        elif readiness_limited:
            reason = "detection_readiness_ceiling"
        elif arbitration_limited:
            reason = "arbitration_unresolved"
        elif explicit_hil:
            reason = "human_approval_required"
        else:
            reason = "rule_match"
        raw_params = event.get("params")
        params = dict(raw_params) if isinstance(raw_params, Mapping) else {}
        if action_type == "ops.switch-t2-proposer-route":
            prior_route = str(event.get("prior_route_ref") or "")
            target_route = str(event.get("alternate_route_ref") or "")
            if prior_route in {"primary", "secondary"} and target_route in {
                "primary",
                "secondary",
            }:
                params = {
                    "target_resource_ref": str(event.get("resource_id") or ""),
                    "target_route_ref": target_route,
                    "prior_route_ref": prior_route,
                    "reason_code": str(
                        event.get("reason_code") or "t2_proposer_candidates_exhausted"
                    ),
                }
        verdict = {
            "producer_principal": "Forseti",
            "correlation_id": event.get("correlation_id", ""),
            "idempotency_key": str(
                event.get("idempotency_key") or event.get("correlation_id") or ""
            ),
            "resource_id": event.get("resource_id"),
            "action_type": action_type,
            "risk_verdict": risk_verdict,
            "resolved_autonomy_ceiling": (
                Autonomy.ENFORCE_AUTO.value
                if risk_verdict == "auto"
                else Autonomy.ENFORCE_HIL.value
                if risk_verdict == "hil"
                else Autonomy.SHADOW_ONLY.value
            ),
            "reason": reason,
            "params": params,
            "detection_readiness": readiness,
            "quorum_required": quorum_for(action_type, self._action_semantics),
            "rollback_contract": rollback_contract_for(action_type, self._action_semantics),
            "initiator_principal": event.get("initiator_principal"),
        }
        workflow_action = event.get("workflow_action")
        if isinstance(workflow_action, Mapping):
            verdict["workflow_action"] = dict(workflow_action)
        copy_change_assessment(event, verdict)
        await self._attach_operational_context(event, verdict)
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
            snapshot = await materializer.materialize(
                target_resource_id=resource_id,
                cutoff=cutoff,
                catalog_versions=versions,
                source_freshness=source_freshness(event.get("source_freshness")),
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
        verdict["resolved_autonomy_ceiling"] = snapshot.autonomy_ceiling.value
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


__all__ = ["ForsetiJudgmentMixin", "RISK_VERDICT", "RULE_MATCH"]

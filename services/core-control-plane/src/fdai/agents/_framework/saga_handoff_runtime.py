"""Saga - append-only audit and typed issue-handoff materialization."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from fdai.agents._framework.action_semantics import RESULT_VALUES, outcome_result
from fdai.agents._framework.adapters import (
    AuditEntry,
)
from fdai.agents._framework.saga_constants import (
    _AUDIT_OUTBOX_CLAIM_LEASE as _AUDIT_OUTBOX_CLAIM_LEASE,
)
from fdai.agents._framework.saga_constants import (
    _AUDIT_OUTBOX_MAINTENANCE_PAGE as _AUDIT_OUTBOX_MAINTENANCE_PAGE,
)
from fdai.agents._framework.saga_constants import (
    _AUDIT_OUTBOX_PENDING_SCAN_LIMIT as _AUDIT_OUTBOX_PENDING_SCAN_LIMIT,
)
from fdai.agents._framework.saga_constants import (
    _AUDIT_OUTBOX_PREFIX as _AUDIT_OUTBOX_PREFIX,
)
from fdai.agents._framework.saga_constants import (
    _AUDIT_OUTBOX_TOMBSTONE_RETENTION as _AUDIT_OUTBOX_TOMBSTONE_RETENTION,
)
from fdai.agents._framework.saga_constants import (
    _FINGERPRINT_BUCKET as _FINGERPRINT_BUCKET,
)
from fdai.agents._framework.saga_constants import (
    _FINGERPRINT_PREFIX as _FINGERPRINT_PREFIX,
)
from fdai.agents._framework.saga_constants import (
    _FINGERPRINT_RETENTION as _FINGERPRINT_RETENTION,
)
from fdai.agents._framework.saga_constants import (
    _FORECAST_AUDIT_FENCE_SIZE as _FORECAST_AUDIT_FENCE_SIZE,
)
from fdai.agents._framework.saga_constants import (
    _HANDOFF_CONTEXT_KEYS as _HANDOFF_CONTEXT_KEYS,
)
from fdai.agents._framework.saga_constants import (
    _ISSUE_CLOSE_CLEAN_WINDOW as _ISSUE_CLOSE_CLEAN_WINDOW,
)
from fdai.agents._framework.saga_constants import (
    _ISSUE_CLOSE_ELIGIBILITY_BUCKET as _ISSUE_CLOSE_ELIGIBILITY_BUCKET,
)
from fdai.agents._framework.saga_constants import (
    _ISSUE_CLOSE_ELIGIBILITY_PREFIX as _ISSUE_CLOSE_ELIGIBILITY_PREFIX,
)
from fdai.agents._framework.saga_constants import (
    _MAX_FINGERPRINT_INDEX as _MAX_FINGERPRINT_INDEX,
)
from fdai.agents._framework.saga_constants import (
    _MAX_HANDOFF_CONTEXT_ITEMS as _MAX_HANDOFF_CONTEXT_ITEMS,
)
from fdai.agents._framework.saga_constants import (
    _MAX_HANDOFF_CONTEXT_VALUE_CHARS as _MAX_HANDOFF_CONTEXT_VALUE_CHARS,
)
from fdai.agents._framework.saga_constants import (
    _NON_LEARNABLE_TERMINAL_STATES as _NON_LEARNABLE_TERMINAL_STATES,
)
from fdai.agents._framework.saga_handoff import (
    HandoffIssueCheckpoint,
)
from fdai.agents._framework.topics import stable_idempotency_key

if TYPE_CHECKING:
    from fdai.agents._framework.base import Agent as _AgentMixinBase
else:
    _AgentMixinBase = object


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SagaAuditChain(Protocol):
    durable: bool
    entries: list[AuditEntry]

    def append(
        self,
        *,
        principal: str,
        topic: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> AuditEntry | Awaitable[AuditEntry]: ...

    def entries_for_correlation(self, correlation_id: str) -> list[AuditEntry]: ...


@dataclass
class _RefCountedLock:
    lock: asyncio.Lock
    ref_count: int = 0


class SagaHandoffRuntimeMixin(_AgentMixinBase):
    """Behavior-preserving extracted runtime methods."""

    if TYPE_CHECKING:
        _append_audit: Any
        _append_issue_audit: Any
        _audit_outbox_pending: Any
        _clock: Any
        _durable_state_store: Any
        _fingerprint_index: Any
        _forecast_audit_keys: Any
        _handoff_journal: Any
        _handoff_locks: Any
        _handover_message: Any
        _issue_close_eligibility: Any
        _issue_close_eligibility_rehydrated: Any
        _issue_close_promotion_evidence_producer_bound: Any
        _issue_timeout_seconds: Any
        _last_audit_outbox_recovered: Any
        _last_issue_close_eligibility_recovered: Any
        _load_durable_fingerprint: Any
        _mutate_github_issue: Any
        _publish_audit_entry_with_outbox: Any
        _publish_issue: Any
        _put_fingerprint_index: Any
        audit_chain: Any
        durable_audit: Any
        github: Any
        recover_audit_outbox: Any
        rehydrate_issue_close_eligibility: Any
        rehydrate_issue_tracker: Any
        state_store: Any

    async def _materialize_handoff(
        self,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        lock_key = str(payload.get("escalation_id") or payload.get("id") or correlation_id)
        lock_entry = self._handoff_locks.get(lock_key)
        if lock_entry is None:
            lock_entry = _RefCountedLock(asyncio.Lock())
            self._handoff_locks[lock_key] = lock_entry
        lock_entry.ref_count += 1
        try:
            async with lock_entry.lock:
                await self._materialize_handoff_locked(payload, correlation_id)
        finally:
            lock_entry.ref_count -= 1
            if lock_entry.ref_count == 0 and self._handoff_locks.get(lock_key) is lock_entry:
                del self._handoff_locks[lock_key]

    async def _materialize_handoff_locked(
        self,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        escalation_id = str(payload.get("escalation_id") or payload.get("id") or "")
        emitting_agent = str(payload.get("emitting_agent") or "")
        intent_category = str(payload.get("intent_category") or "")
        resource_type = str(payload.get("resource_type") or "")
        failure_reason = str(payload.get("failure_reason_code") or "")
        normalized_selector = str(payload.get("normalized_selector") or "")
        supplied_fingerprint = str(payload.get("problem_fingerprint") or "")
        if not all(
            (escalation_id, correlation_id, emitting_agent, intent_category, failure_reason)
        ):
            self.record_behavior("handoff:invalid")
            return
        if not resource_type:
            if supplied_fingerprint:
                self.record_behavior("handoff:invalid")
                return
            resource_type = "unknown"
        if not normalized_selector:
            if supplied_fingerprint:
                self.record_behavior("handoff:invalid")
                return
            normalized_selector = stable_idempotency_key(
                "handoff-legacy-selector",
                intent_category,
                resource_type,
                emitting_agent,
                failure_reason,
            )
        if not supplied_fingerprint:
            self.record_behavior("handoff:legacy_fingerprint_computed")
        fingerprint = compute_fingerprint(
            intent_category=intent_category,
            resource_type=resource_type,
            normalized_selector=normalized_selector,
            primary_agent=emitting_agent,
            failure_reason_code=failure_reason,
        )
        if supplied_fingerprint and supplied_fingerprint != fingerprint:
            self.record_behavior("handoff:fingerprint_mismatch")
            return
        operation_id = f"handoff:{escalation_id}"
        await self._handoff_journal.claim(
            escalation_id=escalation_id,
            fingerprint=fingerprint,
            correlation_id=correlation_id,
            operation_id=operation_id,
        )
        if await self._handoff_journal.is_complete(
            escalation_id=escalation_id,
            fingerprint=fingerprint,
            correlation_id=correlation_id,
        ):
            self.record_behavior("handoff:duplicate")
            return
        checkpoint = await self._handoff_journal.read_checkpoint(escalation_id)
        if checkpoint is None:
            issue_number, created, occurrence_count = await self._mutate_github_issue(
                operation_id=operation_id,
                fingerprint=fingerprint,
                emitting_agent=emitting_agent,
                intent_category=intent_category,
                failure_reason_code=failure_reason,
                correlation_id=correlation_id,
                emitted_at=str(payload.get("emitted_at") or ""),
                context=_bounded_handoff_context(payload.get("context")),
                require_idempotent=True,
            )
            checkpoint = HandoffIssueCheckpoint(
                fingerprint=fingerprint,
                correlation_id=correlation_id,
                issue_number=issue_number,
                created=created,
                occurrence_count=occurrence_count,
            )
            await self._handoff_journal.write_checkpoint(escalation_id, checkpoint)
        elif checkpoint.fingerprint != fingerprint or checkpoint.correlation_id != correlation_id:
            raise ValueError("handoff escalation id conflicts with its mutation checkpoint")

        if not checkpoint.audit_recorded:
            await self._append_issue_audit(
                fingerprint=fingerprint,
                issue_number=checkpoint.issue_number,
                created=checkpoint.created,
                correlation_id=correlation_id,
                operation_id=operation_id,
            )
            checkpoint = checkpoint.with_audit_recorded()
            await self._handoff_journal.write_checkpoint(escalation_id, checkpoint)
        if not checkpoint.published:
            if self.bus is None:
                self.record_behavior("handoff:publication_pending")
                await self._handoff_journal.write_checkpoint(escalation_id, checkpoint)
                raise RuntimeError("Saga issue publication bus is unavailable")
            await self._publish_issue(
                fingerprint=fingerprint,
                issue_number=checkpoint.issue_number,
                created=checkpoint.created,
                correlation_id=correlation_id,
                operation_id=operation_id,
            )
            checkpoint = checkpoint.with_published()
            await self._handoff_journal.write_checkpoint(escalation_id, checkpoint)
        await self._handoff_journal.complete(escalation_id, checkpoint)
        self.record_behavior("handoff:materialized")

    async def recover_handoff_issue_publications(self) -> int:
        """Republish Saga-owned issue records whose checkpoint survived a crash."""

        if self.bus is None:
            return 0
        recovered = 0
        for escalation_id, checkpoint in await self._handoff_journal.pending_publications():
            if checkpoint.published:
                continue
            operation_id = f"handoff:{escalation_id}"
            await self._publish_issue(
                fingerprint=checkpoint.fingerprint,
                issue_number=checkpoint.issue_number,
                created=checkpoint.created,
                correlation_id=checkpoint.correlation_id,
                operation_id=operation_id,
            )
            checkpoint = checkpoint.with_published()
            await self._handoff_journal.write_checkpoint(escalation_id, checkpoint)
            await self._handoff_journal.complete(escalation_id, checkpoint)
            recovered += 1
        if recovered:
            self.record_behavior("handoff:publication_recovered", recovered)
        return recovered

    async def _append_ingress_retention_audit(
        self,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        if not correlation_id:
            correlation_id = stable_idempotency_key(
                "ingress-retention-correlation",
                str(payload.get("idempotency_key") or ""),
                str(payload.get("event_type") or ""),
                str(payload.get("resource_id") or ""),
            )
        receipt = {
            "producer_principal": "Saga",
            "kind": "normalized_ingress_retention",
            "audited_topic": "object.event",
            "correlation_id": correlation_id,
            "idempotency_key": stable_idempotency_key(
                "audit-entry:normalized-ingress-retention",
                correlation_id,
                str(payload.get("idempotency_key") or ""),
                str(payload.get("event_type") or ""),
            ),
            "event_type": str(payload.get("event_type") or "unknown"),
            "resource_id": str(payload.get("resource_id") or ""),
            "source_id": str(payload.get("source_id") or payload.get("id") or ""),
            "judgment_state": "retained_for_replay",
            "execution_authority": False,
        }
        await self._append_audit(
            principal="Saga",
            topic="object.audit-entry",
            correlation_id=correlation_id,
            payload=receipt,
        )
        self.record_behavior("ingress_retention:audit_recorded")

    async def _republish_forecast_outcome(
        self,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> None:
        """Seal a bounded forecast result onto Saga's public audit stream."""
        if self.bus is None and self._durable_state_store is None:
            self.record_behavior("forecast_outcome_audit:transport_unavailable")
            return
        if not correlation_id:
            self.record_behavior("forecast_outcome_audit:missing_correlation")
            return
        idempotency_key = str(payload.get("idempotency_key") or "")
        if not idempotency_key:
            self.record_behavior("forecast_outcome_audit:missing_idempotency_key")
            return
        outcome_id = str(payload.get("outcome_id") or "")
        if not outcome_id:
            self.record_behavior("forecast_outcome_audit:missing_outcome_id")
            return
        audit_idempotency_key = stable_idempotency_key(
            "audit-entry:forecast-outcome",
            outcome_id,
            idempotency_key,
        )
        if audit_idempotency_key in self._forecast_audit_keys:
            self.record_behavior("forecast_outcome_audit:duplicate")
            return
        await self._publish_audit_entry_with_outbox(
            {
                "producer_principal": "Saga",
                "correlation_id": correlation_id,
                "idempotency_key": audit_idempotency_key,
                "audited_topic": "object.forecast-outcome",
                "action_kind": "forecast.outcome.closed",
                "outcome_id": outcome_id,
                "prediction_id": payload.get("prediction_id"),
                "detector_id": str(payload.get("detector_id") or ""),
                "detector_version": str(payload.get("detector_version") or ""),
                "access_scope_digest": str(payload.get("access_scope_digest") or ""),
                "target_digest": str(payload.get("target_digest") or ""),
                "metric": str(payload.get("metric") or ""),
                "label": str(payload.get("label") or ""),
                "evidence_refs": list(payload.get("evidence_refs") or []),
                "telemetry_completeness": str(payload.get("telemetry_completeness") or ""),
                "closed_at": str(payload.get("closed_at") or ""),
                "mode": str(payload.get("mode") or "shadow"),
            },
        )
        self._forecast_audit_keys.add(audit_idempotency_key)

    async def _republish_document_decision(
        self, payload: dict[str, Any], correlation_id: str
    ) -> None:
        """Seal a document decision before the ingestion worker may act."""
        if self.bus is None:
            self.record_behavior("document_decision_audit:transport_unavailable")
            return
        if not correlation_id:
            self.record_behavior("document_decision_audit:missing_correlation")
            return
        idempotency_key = str(payload.get("idempotency_key") or "")
        if not idempotency_key:
            self.record_behavior("document_decision_audit:missing_idempotency_key")
            return
        await self.bus.publish(
            "Saga",
            "object.audit-entry",
            {
                "schema_version": "1.0.0",
                "producer_principal": "Saga",
                "kind": "document_ingestion",
                "audited_topic": "object.verdict",
                "correlation_id": correlation_id,
                "idempotency_key": idempotency_key,
                "stage": str(payload.get("stage") or ""),
                "decision": str(payload.get("decision") or "hold"),
                "reason": str(payload.get("reason") or ""),
                "document_id": str(payload.get("document_id") or ""),
                "upload_id": str(payload.get("upload_id") or ""),
                "initiator_principal": str(payload.get("initiator_principal") or ""),
            },
        )

    async def _republish_document_approval(
        self, payload: dict[str, Any], correlation_id: str
    ) -> None:
        """Seal a document approval before promotion or hold."""
        if self.bus is None:
            self.record_behavior("document_approval_audit:transport_unavailable")
            return
        if not correlation_id:
            self.record_behavior("document_approval_audit:missing_correlation")
            return
        idempotency_key = str(payload.get("idempotency_key") or "")
        if not idempotency_key:
            self.record_behavior("document_approval_audit:missing_idempotency_key")
            return
        await self.bus.publish(
            "Saga",
            "object.audit-entry",
            {
                "schema_version": "1.0.0",
                "producer_principal": "Saga",
                "kind": "document_ingestion",
                "audited_topic": "object.approval",
                "correlation_id": correlation_id,
                "idempotency_key": idempotency_key,
                "stage": str(payload.get("stage") or "protection_check"),
                "decision": str(payload.get("state") or "rejected"),
                "reason": "human_approval",
                "document_id": str(payload.get("document_id") or ""),
                "upload_id": str(payload.get("upload_id") or ""),
                "approvers": list(payload.get("approvers") or []),
            },
        )

    async def _republish_outcome(self, payload: dict[str, Any], correlation_id: str) -> None:
        """Republish a terminal action outcome as an ``object.audit-entry``.

        Saga owns AuditEntry, so it is the writer that closes the discovery
        loop: Norns (the learner) subscribes ``object.audit-entry`` and scores
        rollback rates from these records. Only outcome-defining terminal
        states (succeeded / failed / rolled_back) are republished - one
        record per definitive outcome; intermediate lifecycle states carry no
        learnable result and are written to the append-only chain only. Saga
        does not subscribe ``object.audit-entry``, so this never loops. A
        bus-less Saga (unit scenarios) simply records to the chain.
        """
        if self.bus is None and self._durable_state_store is None:
            self.record_behavior("action_run_audit:transport_unavailable")
            return
        # Self-loop guard (defensive): never republish a record that is
        # already a republished audit-entry. Saga does not subscribe
        # object.audit-entry today, so this cannot fire - but if a future
        # change wires that subscription, the audited_topic marker stops an
        # infinite audit-of-an-audit loop.
        if payload.get("audited_topic"):
            self.record_behavior("action_run_audit:ignored_audit_entry")
            return
        # Empty correlation -> the audit-entry (a correlation-partitioned
        # topic) would carry an empty partition key, losing ordering, and
        # Norns cannot dedup it per action. The append-only chain already has
        # the record; skip the bus republish rather than emit an unkeyed one.
        if not correlation_id:
            self.record_behavior("action_run_audit:missing_correlation")
            return
        result = outcome_result(str(payload.get("state", "")))
        # Prefer a directly-stamped canonical ``result`` when present (mirrors
        # Norns' precedence, which reads ``result`` before falling back to
        # ``state``). Without this, a producer that emitted only a canonical
        # ``result`` - with a ``state`` Saga cannot map - would be dropped here
        # yet learned by Norns, an asymmetry between writer and reader.
        direct = str(payload.get("result", "")).strip().lower()
        if direct in RESULT_VALUES:
            result = direct
        action_type = str(payload.get("action_type", ""))
        state = str(payload.get("state") or "").strip().lower()
        non_learnable = result is None and state in _NON_LEARNABLE_TERMINAL_STATES
        if not action_type:
            self.record_behavior("action_run_audit:missing_action_type")
            return
        if result is None and not non_learnable:
            self.record_behavior("action_run_audit:unmappable_state")
            return
        shadow_mode = bool(payload.get("shadow_mode", False))
        if shadow_mode and result is not None:
            result = f"shadow_{result}"
        idempotency_key = stable_idempotency_key(
            "audit-entry:action-run",
            correlation_id,
            action_type,
            state,
            result,
            shadow_mode,
            payload.get("idempotency_key"),
        )
        observed_at = str(payload.get("terminal_at") or "")
        if shadow_mode and result is not None and not observed_at:
            observed_at = self._clock().isoformat()
        await self._publish_audit_entry_with_outbox(
            {
                "producer_principal": "Saga",
                "correlation_id": correlation_id,
                "idempotency_key": idempotency_key,
                "audited_topic": "object.action-run",
                "action_type": action_type,
                **({"result": result} if result is not None else {}),
                "non_learnable": non_learnable,
                "resource_id": payload.get("resource_id"),
                "shadow_mode": shadow_mode,
                "shadow_observation_id": correlation_id,
                "observed_at": observed_at,
                "operator_reviewed": False,
                "operator_agreed": False,
                "policy_escape": payload.get("policy_escape") is True,
                "initiator_principal": payload.get("initiator_principal"),
                **(
                    {"batch_role": payload.get("batch_role")}
                    if payload.get("batch_role") in {"rollup", "attempt"}
                    else {}
                ),
                **(
                    {"attempt_id": payload.get("attempt_id")}
                    if isinstance(payload.get("attempt_id"), str)
                    else {}
                ),
                **(
                    {"rollup_correlation_id": payload.get("rollup_correlation_id")}
                    if isinstance(payload.get("rollup_correlation_id"), str)
                    else {}
                ),
                **(
                    {"rollup_action_run_identity": payload.get("rollup_action_run_identity")}
                    if isinstance(payload.get("rollup_action_run_identity"), str)
                    else {}
                ),
                **(
                    {"target_set_digest": payload.get("target_set_digest")}
                    if isinstance(payload.get("target_set_digest"), str)
                    else {}
                ),
                **(
                    {"target_set": list(payload["target_set"])}
                    if isinstance(payload.get("target_set"), list)
                    else {}
                ),
                **(
                    {"target_count": payload.get("target_count")}
                    if isinstance(payload.get("target_count"), int)
                    and not isinstance(payload.get("target_count"), bool)
                    else {}
                ),
                **(
                    {"batch_rollup": dict(payload["batch_rollup"])}
                    if isinstance(payload.get("batch_rollup"), Mapping)
                    else {}
                ),
            }
        )
        self.record_behavior(
            "action_run_audit:non_learnable" if non_learnable else "action_run_audit:published"
        )


def compute_fingerprint(
    *,
    intent_category: str,
    resource_type: str,
    normalized_selector: str,
    primary_agent: str,
    failure_reason_code: str,
) -> str:
    """Deterministic SHA-256 fingerprint over the §6.4 handoff components."""
    material = "|".join(
        (
            intent_category,
            resource_type,
            normalized_selector,
            primary_agent,
            failure_reason_code,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _bounded_handoff_context(raw: Mapping[str, Any] | object | None) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    sanitized: dict[str, str] = {}
    for key, value in sorted(raw.items()):
        name = str(key)
        if name not in _HANDOFF_CONTEXT_KEYS:
            continue
        if len(sanitized) >= _MAX_HANDOFF_CONTEXT_ITEMS:
            break
        rendered = str(value).strip()
        if not rendered or len(rendered) > _MAX_HANDOFF_CONTEXT_VALUE_CHARS:
            continue
        sanitized[name] = rendered
    return sanitized


__all__ = ["SagaHandoffRuntimeMixin"]

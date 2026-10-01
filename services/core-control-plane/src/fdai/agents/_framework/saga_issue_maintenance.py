"""Saga - append-only audit and typed issue-handoff materialization."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from fdai.agents._framework.adapters import (
    AuditEntry,
    canonical_json_digest,
)
from fdai.agents._framework.base import Agent
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
from fdai.agents._framework.topics import stable_idempotency_key

if TYPE_CHECKING:
    from fdai.agents._framework.base import Agent as _AgentMixinBase
else:
    _AgentMixinBase = object

_ISSUE_CLOSE_CHECKPOINT_PREFIX = "pantheon/saga/issue-close-checkpoint/"
_ISSUE_CLOSE_CHECKPOINT_PAGE = 128
_ISSUE_CLOSE_CHECKPOINT_RETENTION = 1_024
_ISSUE_CLOSE_CHECKPOINT_CAS_RETRIES = 16


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


class SagaIssueMaintenanceMixin(_AgentMixinBase):
    """Behavior-preserving extracted runtime methods."""

    if TYPE_CHECKING:
        _append_audit: Any
        _append_ingress_retention_audit: Any
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
        _materialize_handoff: Any
        _mutate_github_issue: Any
        _publish_audit_entry_with_outbox: Any
        _publish_issue: Any
        _put_fingerprint_index: Any
        _republish_document_approval: Any
        _republish_document_decision: Any
        _republish_forecast_outcome: Any
        _republish_outcome: Any
        audit_chain: Any
        durable_audit: Any
        github: Any
        recover_audit_outbox: Any
        rehydrate_issue_close_eligibility: Any
        rehydrate_issue_tracker: Any
        state_store: Any

    async def close_issue(self, *, fingerprint: str, closed_by_pr: str) -> None:
        result = self.github.close(fingerprint, closed_by_pr=closed_by_pr)
        if inspect.isawaitable(result):
            await result
        state = self.state_store.get(_FINGERPRINT_BUCKET, fingerprint) or {}
        state["closed_by_pr"] = closed_by_pr
        state["open"] = False
        self._put_fingerprint_index(fingerprint, state)

    async def scan_issue_closures(self) -> int:
        if not self._issue_close_eligibility_rehydrated:
            await self.rehydrate_issue_close_eligibility()
        await self.rehydrate_issue_tracker()
        closed = int(await self._recover_issue_close_checkpoints())
        now = self._clock()
        for fingerprint, evidence in tuple(self._issue_close_eligibility.items()):
            if not _issue_close_evidence_is_eligible(evidence, now=now):
                continue
            fingerprint_state = await self._current_fingerprint_state(fingerprint)
            if fingerprint_state is None:
                self.record_behavior("issue_close:missing_fingerprint_state")
                continue
            if _fingerprint_recurred_since_clean(fingerprint_state, evidence):
                self.record_behavior("issue_close:recurrence_after_clean")
                continue
            issue = self.github.issues.get(fingerprint)
            if issue is None:
                continue
            if not issue.open:
                continue
            closed_by_pr = str(evidence["promotion_pr"])
            correlation_id = str(evidence["correlation_id"])
            idempotency_key = stable_idempotency_key(
                "issue-auto-close",
                fingerprint,
                closed_by_pr,
                correlation_id,
            )
            checkpoint = await self._issue_close_checkpoint(
                fingerprint=fingerprint,
                issue_number=issue.number,
                closed_by_pr=closed_by_pr,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                evidence=evidence,
            )
            if await self._advance_issue_close_checkpoint(checkpoint):
                closed += 1
        if closed:
            self.record_behavior("maintenance_tick:issue_close_scan_closed", closed)
        return closed

    async def _issue_close_checkpoint(
        self,
        *,
        fingerprint: str,
        issue_number: int,
        closed_by_pr: str,
        correlation_id: str,
        idempotency_key: str,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        record = {
            "schema_version": "1.0.0",
            "revision": 1,
            "status": "pending",
            "checkpoint_key": _issue_close_checkpoint_key(fingerprint, idempotency_key),
            "fingerprint": fingerprint,
            "issue_number": issue_number,
            "closed_by_pr": closed_by_pr,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "eligibility_evidence": dict(evidence),
            "intent_audited": False,
            "external_closed": False,
            "terminal_audited": False,
            "published": False,
            "completed": False,
        }
        if self._durable_state_store is None:
            self.record_behavior("issue_close:no_durable_checkpoint")
            return record
        key = _issue_close_checkpoint_key(fingerprint, idempotency_key)
        await self._durable_state_store.write_state_if_absent(key, record)
        stored = await self._durable_state_store.read_state(key)
        if not isinstance(stored, Mapping):
            raise RuntimeError("Saga issue-close checkpoint disappeared after creation")
        return dict(stored)

    async def _recover_issue_close_checkpoints(self) -> int:
        if self._durable_state_store is None:
            return 0
        recovered = 0
        while recovered < _MAX_FINGERPRINT_INDEX:
            rows, _total = await self._durable_state_store.read_state_page(
                _ISSUE_CLOSE_CHECKPOINT_PREFIX,
                limit=min(_ISSUE_CLOSE_CHECKPOINT_PAGE, _MAX_FINGERPRINT_INDEX - recovered),
                field="status",
                value="pending",
            )
            if not rows:
                break
            for row in reversed(rows):
                if await self._advance_issue_close_checkpoint(dict(row)):
                    recovered += 1
        await self._compact_issue_close_checkpoints()
        if recovered:
            self.record_behavior("issue_close:checkpoint_recovered", recovered)
        return recovered

    async def _advance_issue_close_checkpoint(self, checkpoint: dict[str, Any]) -> bool:
        for _attempt in range(_ISSUE_CLOSE_CHECKPOINT_CAS_RETRIES):
            completed, checkpoint, retry = await self._advance_issue_close_checkpoint_once(
                checkpoint
            )
            if not retry:
                return bool(completed)
        raise RuntimeError("Saga issue-close checkpoint CAS retry limit exceeded")

    async def _advance_issue_close_checkpoint_once(
        self,
        checkpoint: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], bool]:
        fingerprint = str(checkpoint.get("fingerprint") or "")
        issue_number = _positive_int(checkpoint.get("issue_number"))
        closed_by_pr = str(checkpoint.get("closed_by_pr") or "")
        correlation_id = str(checkpoint.get("correlation_id") or "")
        idempotency_key = str(checkpoint.get("idempotency_key") or "")
        evidence = checkpoint.get("eligibility_evidence")
        if (
            not fingerprint
            or issue_number is None
            or not closed_by_pr
            or not correlation_id
            or not idempotency_key
            or not isinstance(evidence, Mapping)
        ):
            self.record_behavior("issue_close:checkpoint_invalid")
            return False, checkpoint, False
        if not checkpoint.get("intent_audited"):
            await self._append_issue_close_audit(
                fingerprint=fingerprint,
                issue_number=issue_number,
                closed_by_pr=closed_by_pr,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                evidence=evidence,
                kind="issue_auto_close_intent",
            )
            checkpoint, stored = await self._store_issue_close_checkpoint(
                checkpoint,
                {"intent_audited": True},
            )
            if not stored:
                return False, checkpoint, True
        if not checkpoint.get("external_closed"):
            current_state = await self._current_fingerprint_state(fingerprint)
            if current_state is None or _fingerprint_recurred_since_clean(current_state, evidence):
                await self._append_issue_close_cancelled_audit(
                    fingerprint=fingerprint,
                    issue_number=issue_number,
                    closed_by_pr=closed_by_pr,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                    evidence=evidence,
                    reason=(
                        "missing_fingerprint_state"
                        if current_state is None
                        else "recurrence_after_clean"
                    ),
                )
                checkpoint, stored = await self._store_issue_close_checkpoint(
                    checkpoint,
                    {
                        "status": "cancelled",
                        "completed": True,
                        "cancelled": True,
                        "cancel_reason": (
                            "missing_fingerprint_state"
                            if current_state is None
                            else "recurrence_after_clean"
                        ),
                    },
                )
                if not stored:
                    return False, checkpoint, True
                self.record_behavior("issue_close:cancelled_recurrence")
                return False, checkpoint, False
            issue = self.github.issues.get(fingerprint)
            if issue is not None and issue.open:
                await self.close_issue(fingerprint=fingerprint, closed_by_pr=closed_by_pr)
            checkpoint, stored = await self._store_issue_close_checkpoint(
                checkpoint,
                {"external_closed": True},
            )
            if not stored:
                return False, checkpoint, True
        if not checkpoint.get("terminal_audited"):
            await self._append_issue_close_audit(
                fingerprint=fingerprint,
                issue_number=issue_number,
                closed_by_pr=closed_by_pr,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                evidence=evidence,
                kind="issue_auto_close",
            )
            checkpoint, stored = await self._store_issue_close_checkpoint(
                checkpoint,
                {"terminal_audited": True},
            )
            if not stored:
                return False, checkpoint, True
        if not checkpoint.get("published"):
            if self.bus is None:
                self.record_behavior("issue_close:publication_pending")
                return False, checkpoint, False
            await self._publish_issue(
                fingerprint=fingerprint,
                issue_number=issue_number,
                created=False,
                correlation_id=correlation_id,
                operation_id=idempotency_key,
                extra={
                    "kind": "issue_auto_close",
                    "closed_by_pr": closed_by_pr,
                    "execution_authority": False,
                },
            )
            checkpoint, stored = await self._store_issue_close_checkpoint(
                checkpoint,
                {"published": True},
            )
            if not stored:
                return False, checkpoint, True
        checkpoint, stored = await self._store_issue_close_checkpoint(
            checkpoint,
            {"completed": True, "status": "complete"},
        )
        if not stored:
            return False, checkpoint, True
        await self._compact_issue_close_checkpoints()
        return True, checkpoint, False

    async def _append_issue_close_audit(
        self,
        *,
        fingerprint: str,
        issue_number: int,
        closed_by_pr: str,
        correlation_id: str,
        idempotency_key: str,
        evidence: Mapping[str, Any],
        kind: str,
    ) -> None:
        payload = {
            "producer_principal": "Saga",
            "kind": kind,
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "fingerprint": fingerprint,
            "issue_number": issue_number,
            "closed_by_pr": closed_by_pr,
            "mimir_promotion_recorded_at": evidence.get("promotion_recorded_at"),
            "clean_regression_started_at": evidence.get("clean_regression_started_at"),
            "execution_authority": False,
        }
        if _audit_payload_exists(self.audit_chain.entries_for_correlation(correlation_id), payload):
            return
        await self._append_audit(
            principal="Saga",
            topic="object.issue",
            correlation_id=correlation_id,
            payload=payload,
        )

    async def _append_issue_close_cancelled_audit(
        self,
        *,
        fingerprint: str,
        issue_number: int,
        closed_by_pr: str,
        correlation_id: str,
        idempotency_key: str,
        evidence: Mapping[str, Any],
        reason: str,
    ) -> None:
        payload = {
            "producer_principal": "Saga",
            "kind": "issue_auto_close_cancelled",
            "correlation_id": correlation_id,
            "idempotency_key": stable_idempotency_key(
                "issue-auto-close-cancelled",
                idempotency_key,
            ),
            "source_idempotency_key": idempotency_key,
            "fingerprint": fingerprint,
            "issue_number": issue_number,
            "closed_by_pr": closed_by_pr,
            "cancel_reason": reason,
            "mimir_promotion_recorded_at": evidence.get("promotion_recorded_at"),
            "clean_regression_started_at": evidence.get("clean_regression_started_at"),
            "execution_authority": False,
        }
        if _audit_payload_exists(self.audit_chain.entries_for_correlation(correlation_id), payload):
            return
        await self._append_audit(
            principal="Saga",
            topic="object.issue",
            correlation_id=correlation_id,
            payload=payload,
        )

    async def _store_issue_close_checkpoint(
        self,
        checkpoint: dict[str, Any],
        updates: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        current_revision = int(checkpoint.get("revision", 1))
        updated = {
            **checkpoint,
            **dict(updates),
            "revision": current_revision + 1,
        }
        if self._durable_state_store is None:
            return updated, True
        key = _issue_close_checkpoint_key(
            str(checkpoint["fingerprint"]),
            str(checkpoint["idempotency_key"]),
        )
        stored = await self._durable_state_store.compare_and_set_state(
            key,
            updated,
            expected_revision=current_revision,
        )
        if stored:
            return updated, True
        latest = await self._durable_state_store.read_state(key)
        if not isinstance(latest, Mapping):
            raise RuntimeError("Saga issue-close checkpoint disappeared during transition")
        return dict(latest), False

    async def _compact_issue_close_checkpoints(self) -> int:
        if self._durable_state_store is None:
            return 0
        rows, total = await self._durable_state_store.read_state_page(
            _ISSUE_CLOSE_CHECKPOINT_PREFIX,
            limit=_ISSUE_CLOSE_CHECKPOINT_PAGE,
            offset=_ISSUE_CLOSE_CHECKPOINT_RETENTION,
            field="status",
            value="complete",
        )
        deleted = 0
        for row in rows:
            key = str(row.get("checkpoint_key") or "")
            if key.startswith(
                _ISSUE_CLOSE_CHECKPOINT_PREFIX
            ) and await self._durable_state_store.delete_state(key):
                deleted += 1
        if total > _ISSUE_CLOSE_CHECKPOINT_RETENTION + _ISSUE_CLOSE_CHECKPOINT_PAGE:
            self.record_behavior("issue_close:checkpoint_compaction_deferred")
        if deleted:
            self.record_behavior("issue_close:checkpoint_compacted", deleted)
        return deleted

    async def _current_fingerprint_state(self, fingerprint: str) -> dict[str, Any] | None:
        durable = await self._load_durable_fingerprint(fingerprint)
        if durable is not None:
            return dict(durable)
        local = self._fingerprint_index.get(fingerprint)
        return dict(local) if isinstance(local, Mapping) else None

    def replay_for_correlation(self, correlation_id: str) -> list[AuditEntry]:
        return list(self.audit_chain.entries_for_correlation(correlation_id))

    async def maintenance_tick(self) -> None:
        await Agent.maintenance_tick(self)
        await self.recover_audit_outbox(limit=_AUDIT_OUTBOX_MAINTENANCE_PAGE)
        verify = getattr(self.audit_chain, "verify", None)
        if callable(verify):
            verify()
        self._last_chain_verified_entries = len(self.audit_chain.entries)
        if self._last_chain_verified_entries:
            self.record_behavior("maintenance_tick:audit_chain_verified")
        await self.scan_issue_closures()
        compacted = await self.compact_fingerprint_index()
        if compacted:
            self.record_behavior("maintenance_tick:fingerprint_index_compacted", compacted)

    async def compact_fingerprint_index(self) -> int:
        compacted = 0
        while len(self._fingerprint_index) > _FINGERPRINT_RETENTION:
            oldest = next(iter(self._fingerprint_index))
            self._fingerprint_index.pop(oldest, None)
            compacted += 1
        self.state_store.data[_FINGERPRINT_BUCKET] = dict(self._fingerprint_index.items())
        if self._durable_state_store is not None:
            compacted += await self._durable_state_store.delete_states_beyond(
                _FINGERPRINT_PREFIX,
                retain_newest=_FINGERPRINT_RETENTION,
            )
        return compacted

    def health(self) -> dict[str, Any]:
        entries = len(self.audit_chain.entries)
        durable = self.durable_audit
        verified_entries = self._last_chain_verified_entries
        integrity_kpi = (
            {
                "value": 1.0,
                "evidence_state": "measured",
                "numerator": verified_entries,
                "denominator": entries,
                "unit": "ratio",
            }
            if durable and entries > 0 and verified_entries >= entries
            else {
                "value": None,
                "evidence_state": "insufficient_sample",
                "numerator": verified_entries,
                "denominator": entries,
                "unit": "ratio",
            }
        )
        return {
            "agent": self.spec.name,
            "status": "ok" if durable else "degraded",
            "status_reason": "ready" if durable else "audit_not_durable",
            "audit_durability": "durable" if durable else "process_local",
            "audit_backend_available": True,
            "audit_entries": entries,
            "chain_verification": {
                "verified_entries": verified_entries,
                "entries": entries,
                "evidence_state": integrity_kpi["evidence_state"],
            },
            "pending_audit_outbox": self._audit_outbox_pending,
            "last_audit_outbox_recovered": self._last_audit_outbox_recovered,
            "audit_outbox_scan_limit": _AUDIT_OUTBOX_PENDING_SCAN_LIMIT,
            "fingerprint_index_size": len(self._fingerprint_index),
            "fingerprint_retention": _FINGERPRINT_RETENTION,
            "issue_auto_close": (
                "evidence_available"
                if self._issue_close_eligibility
                else "durable_evidence_rehydrated_empty"
                if self._issue_close_eligibility_rehydrated
                and self._last_issue_close_eligibility_recovered == 0
                else "awaiting_promotion_evidence"
                if self._issue_close_promotion_evidence_producer_bound
                else "awaiting_promotion_evidence_producer"
            ),
            "issue_auto_close_producer_bound": (
                self._issue_close_promotion_evidence_producer_bound
            ),
            "issue_auto_close_evidence_count": len(self._issue_close_eligibility),
            "issue_auto_close_last_recovered": self._last_issue_close_eligibility_recovered,
            "kpis": {"audit_chain_integrity_rate": integrity_kpi},
            "behavior": self.behavior_snapshot(),
        }


def _issue_close_evidence_is_eligible(evidence: Mapping[str, Any], *, now: datetime) -> bool:
    if not str(evidence.get("fingerprint") or "") or not str(evidence.get("promotion_pr") or ""):
        return False
    if not str(evidence.get("correlation_id") or ""):
        return False
    clean_started_raw = evidence.get("clean_regression_started_at")
    if not isinstance(clean_started_raw, str):
        return False
    try:
        clean_started = datetime.fromisoformat(clean_started_raw)
    except ValueError:
        return False
    if clean_started.tzinfo is None:
        clean_started = clean_started.replace(tzinfo=UTC)
    return now >= clean_started + _ISSUE_CLOSE_CLEAN_WINDOW


def _fingerprint_recurred_since_clean(
    fingerprint_state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> bool:
    clean_started_raw = evidence.get("clean_regression_started_at")
    last_seen_raw = fingerprint_state.get("last_seen")
    occurrence_count = fingerprint_state.get("occurrence_count")
    if (
        not isinstance(clean_started_raw, str)
        or not isinstance(last_seen_raw, str)
        or not isinstance(occurrence_count, int)
        or isinstance(occurrence_count, bool)
        or occurrence_count < 1
    ):
        return True
    try:
        clean_started = datetime.fromisoformat(clean_started_raw)
        last_seen = datetime.fromisoformat(last_seen_raw)
    except ValueError:
        return True
    if clean_started.tzinfo is None:
        clean_started = clean_started.replace(tzinfo=UTC)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    return occurrence_count > 1 and last_seen > clean_started


def _issue_close_checkpoint_key(fingerprint: str, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{fingerprint}\0{idempotency_key}".encode()).hexdigest()
    return f"{_ISSUE_CLOSE_CHECKPOINT_PREFIX}{digest}"


def _positive_int(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return None
    return value


def _audit_payload_exists(entries: list[AuditEntry], payload: Mapping[str, Any]) -> bool:
    try:
        digest = canonical_json_digest(payload)
    except (TypeError, ValueError):
        return False
    return any(entry.payload_digest == digest for entry in entries)


__all__ = ["SagaIssueMaintenanceMixin"]

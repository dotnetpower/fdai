"""Saga - append-only audit and typed issue-handoff materialization."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from fdai.agents._framework.adapters import (
    AuditEntry,
)
from fdai.agents._framework.base import Agent
from fdai.agents._framework.topics import stable_idempotency_key

_FINGERPRINT_BUCKET = "issue_fingerprint_index"
_AUDIT_OUTBOX_PREFIX = "pantheon/saga/audit-outbox/"
_FINGERPRINT_PREFIX = "pantheon/saga/issue-fingerprint/"
_ISSUE_CLOSE_ELIGIBILITY_PREFIX = "pantheon/saga/issue-close-eligibility/"
_AUDIT_OUTBOX_PENDING_SCAN_LIMIT = 5_000
_AUDIT_OUTBOX_MAINTENANCE_PAGE = 16
# Published outbox tombstones retain only digests long enough to suppress
# duplicate redelivery across restarts while keeping prefix scans bounded.
_AUDIT_OUTBOX_TOMBSTONE_RETENTION = 1_024
_AUDIT_OUTBOX_CLAIM_LEASE = timedelta(minutes=5)
_FORECAST_AUDIT_FENCE_SIZE = 10_000
_MAX_FINGERPRINT_INDEX = 50_000
_FINGERPRINT_RETENTION = 10_000
_ISSUE_CLOSE_CLEAN_WINDOW = timedelta(hours=24)
_ISSUE_CLOSE_ELIGIBILITY_BUCKET = "issue_close_eligibility"
_MAX_HANDOFF_CONTEXT_ITEMS = 8
_MAX_HANDOFF_CONTEXT_VALUE_CHARS = 256
_HANDOFF_CONTEXT_KEYS = frozenset(
    {
        "context_ref",
        "evidence_ref",
        "handoff_ref",
        "payload_digest",
        "source_ref",
        "trace_ref",
    }
)
_NON_LEARNABLE_TERMINAL_STATES = frozenset(
    {"deny_dropped", "rejected", "expired", "approval_expired"}
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SagaAuditChain(Protocol):
    durable: bool
    entries: list[AuditEntry]

    def append(
        self: Any,
        *,
        principal: str,
        topic: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> AuditEntry | Awaitable[AuditEntry]: ...

    def entries_for_correlation(self: Any, correlation_id: str) -> list[AuditEntry]: ...


@dataclass
class _RefCountedLock:
    lock: asyncio.Lock
    ref_count: int = 0


class SagaIssueMaintenanceMixin:
    """Behavior-preserving extracted runtime methods."""

    async def close_issue(self: Any, *, fingerprint: str, closed_by_pr: str) -> None:
        result = self.github.close(fingerprint, closed_by_pr=closed_by_pr)
        if inspect.isawaitable(result):
            await result
        state = self.state_store.get(_FINGERPRINT_BUCKET, fingerprint) or {}
        state["closed_by_pr"] = closed_by_pr
        state["open"] = False
        self._put_fingerprint_index(fingerprint, state)

    async def scan_issue_closures(self: Any) -> int:
        if not self._issue_close_eligibility_rehydrated:
            await self.rehydrate_issue_close_eligibility()
        await self.rehydrate_issue_tracker()
        closed = 0
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
            if issue is None or not issue.open:
                continue
            fingerprint_state = await self._current_fingerprint_state(fingerprint)
            if fingerprint_state is None:
                self.record_behavior("issue_close:missing_fingerprint_state")
                continue
            if _fingerprint_recurred_since_clean(fingerprint_state, evidence):
                self.record_behavior("issue_close:recurrence_after_clean")
                continue
            closed_by_pr = str(evidence["promotion_pr"])
            await self.close_issue(fingerprint=fingerprint, closed_by_pr=closed_by_pr)
            correlation_id = str(evidence["correlation_id"])
            idempotency_key = stable_idempotency_key(
                "issue-auto-close",
                fingerprint,
                closed_by_pr,
                correlation_id,
            )
            await self._append_audit(
                principal="Saga",
                topic="object.issue",
                correlation_id=correlation_id,
                payload={
                    "producer_principal": "Saga",
                    "kind": "issue_auto_close",
                    "correlation_id": correlation_id,
                    "idempotency_key": idempotency_key,
                    "fingerprint": fingerprint,
                    "issue_number": issue.number,
                    "closed_by_pr": closed_by_pr,
                    "mimir_promotion_recorded_at": evidence["promotion_recorded_at"],
                    "clean_regression_started_at": evidence["clean_regression_started_at"],
                    "execution_authority": False,
                },
            )
            if self.bus is not None:
                await self._publish_issue(
                    fingerprint=fingerprint,
                    issue_number=issue.number,
                    created=False,
                    correlation_id=correlation_id,
                    operation_id=idempotency_key,
                )
            closed += 1
        if closed:
            self.record_behavior("maintenance_tick:issue_close_scan_closed", closed)
        return closed

    async def _current_fingerprint_state(self: Any, fingerprint: str) -> dict[str, Any] | None:
        durable = await self._load_durable_fingerprint(fingerprint)
        if durable is not None:
            return dict(durable)
        local = self._fingerprint_index.get(fingerprint)
        return dict(local) if isinstance(local, Mapping) else None

    def replay_for_correlation(self: Any, correlation_id: str) -> list[AuditEntry]:
        return list(self.audit_chain.entries_for_correlation(correlation_id))

    async def maintenance_tick(self: Any) -> None:
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

    async def compact_fingerprint_index(self: Any) -> int:
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

    def health(self: Any) -> dict[str, Any]:
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


__all__ = ["SagaIssueMaintenanceMixin"]

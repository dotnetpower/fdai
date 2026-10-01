"""Saga - append-only audit and typed issue-handoff materialization."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from fdai.agents._framework.adapters import (
    AuditEntry,
    canonical_json_digest,
)
from fdai.agents._framework.outbox_publication import (
    PublicationClaim,
    claim_expired,
    new_publication_claim_owner,
    publish_claimed_outbox,
)

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


class SagaAuditRuntimeMixin:
    """Behavior-preserving extracted runtime methods."""

    async def recover_audit_outbox(
        self: Any, *, limit: int = _AUDIT_OUTBOX_PENDING_SCAN_LIMIT
    ) -> int:
        """Republish durable audit-entry intents left unpublished by a crash."""

        if self._durable_state_store is None or self.bus is None:
            return 0
        published = 0
        attempted = 0
        attempted_keys: set[str] = set()
        while attempted < limit:
            remaining = limit - attempted
            pending_rows, pending_total = await self._durable_state_store.read_state_page(
                _AUDIT_OUTBOX_PREFIX,
                limit=remaining,
                field="status",
                value="pending",
            )
            publishing_rows, publishing_total = await self._durable_state_store.read_state_page(
                _AUDIT_OUTBOX_PREFIX,
                limit=remaining,
                field="status",
                value="publishing",
            )
            self._audit_outbox_pending = pending_total + publishing_total
            rows = (*pending_rows, *publishing_rows)
            if not rows:
                break
            progress = 0
            for row in reversed(rows[:remaining]):
                payload = row.get("payload")
                if not isinstance(payload, Mapping):
                    self.record_behavior("audit_outbox:recovery_invalid_row")
                    attempted += 1
                    continue
                outbox_key = _audit_outbox_key(payload)
                if outbox_key in attempted_keys:
                    continue
                attempted_keys.add(outbox_key)
                attempted += 1
                try:
                    if await self._publish_claimed_audit_outbox(dict(payload)):
                        published += 1
                        progress += 1
                except Exception:
                    self.record_behavior("audit_outbox:recovery_publish_failed")
                    continue
            if progress == 0:
                break
        if self._audit_outbox_pending > published:
            self.record_behavior("audit_outbox:recovery_deferred")
        self._last_audit_outbox_recovered = published
        self._audit_outbox_pending = max(0, self._audit_outbox_pending - published)
        return published

    async def _append_audit(
        self: Any,
        *,
        principal: str,
        topic: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> None:
        result = self.audit_chain.append(
            principal=principal,
            topic=topic,
            correlation_id=correlation_id,
            payload=payload,
        )
        if inspect.isawaitable(result):
            await result

    async def _publish_audit_entry_with_outbox(self: Any, payload: dict[str, Any]) -> None:
        if self._durable_state_store is None:
            if self.bus is None:
                self.record_behavior("audit_outbox:transport_unavailable")
                return
            await self.bus.publish("Saga", "object.audit-entry", payload)
            return
        await self._checkpoint_audit_outbox(payload)
        if self.bus is None:
            self.record_behavior("audit_outbox:publication_pending")
            return
        await self._publish_claimed_audit_outbox(payload)

    async def _publish_claimed_audit_outbox(self: Any, payload: dict[str, Any]) -> bool:
        bus = self.bus
        if bus is None:
            self.record_behavior("audit_outbox:publication_pending")
            return False
        claim = await self._claim_audit_outbox_publication(payload)
        return await publish_claimed_outbox(
            claim,
            publish=lambda: bus.publish("Saga", "object.audit-entry", payload),
            mark_published=lambda active_claim: self._mark_audit_outbox_published(
                payload, active_claim
            ),
            release=lambda active_claim: self._release_audit_outbox_publication_claim(
                payload, active_claim
            ),
            lease=_AUDIT_OUTBOX_CLAIM_LEASE,
        )

    async def _checkpoint_audit_outbox(self: Any, payload: Mapping[str, Any]) -> None:
        if self._durable_state_store is None:
            return
        key = _audit_outbox_key(payload)
        record = {
            "schema_version": "1.0.0",
            "revision": 1,
            "status": "pending",
            "correlation_id": str(payload.get("correlation_id") or ""),
            "idempotency_key": str(payload.get("idempotency_key") or ""),
            "payload": dict(payload),
        }
        created = await self._durable_state_store.write_state_if_absent(key, record)
        if created:
            self._audit_outbox_pending += 1
        if created:
            return
        stored = await self._durable_state_store.read_state(key)
        if not isinstance(stored, Mapping):
            raise RuntimeError("Saga audit outbox row disappeared")
        if stored.get("status") == "published":
            stored_digest = str(stored.get("payload_digest") or "")
            record_payload = record["payload"]
            if not isinstance(record_payload, Mapping):
                raise RuntimeError("Saga audit outbox row is malformed")
            payload_digest = _payload_digest(record_payload)
            if stored_digest and stored_digest != payload_digest:
                raise RuntimeError("Saga audit outbox idempotency collision")
            return
        if stored.get("payload") != record["payload"]:
            raise RuntimeError("Saga audit outbox idempotency collision")

    async def _claim_audit_outbox_publication(
        self: Any,
        payload: Mapping[str, Any],
    ) -> PublicationClaim | None:
        if self._durable_state_store is None:
            return PublicationClaim(
                owner=new_publication_claim_owner(self.spec.name),
                claimed_at=self._clock().isoformat(),
            )
        key = _audit_outbox_key(payload)
        for _attempt in range(16):
            stored = await self._durable_state_store.read_state(key)
            if stored is None:
                raise RuntimeError("Saga audit outbox row disappeared")
            if stored.get("status") == "published":
                return None
            now = self._clock()
            if stored.get("status") == "publishing" and not _audit_outbox_claim_expired(
                stored, now
            ):
                return None
            revision = int(stored.get("revision", 1))
            claimed_at = now.isoformat()
            claim_owner = new_publication_claim_owner(self.spec.name)
            advanced = await self._durable_state_store.compare_and_set_state(
                key,
                {
                    **dict(stored),
                    "status": "publishing",
                    "revision": revision + 1,
                    "claim_owner": claim_owner,
                    "claimed_at": claimed_at,
                },
                expected_revision=revision,
            )
            if advanced:
                return PublicationClaim(owner=claim_owner, claimed_at=claimed_at)
        raise RuntimeError("Saga audit outbox publication claim CAS retry limit exceeded")

    async def _mark_audit_outbox_published(
        self: Any,
        payload: Mapping[str, Any],
        claim: PublicationClaim,
    ) -> bool:
        if self._durable_state_store is None:
            return True
        key = _audit_outbox_key(payload)
        for _attempt in range(16):
            stored = await self._durable_state_store.read_state(key)
            if stored is None or stored.get("status") == "published":
                return False
            if (
                str(stored.get("claim_owner") or "") != claim.owner
                or str(stored.get("claimed_at") or "") != claim.claimed_at
            ):
                return False
            revision = int(stored.get("revision", 1))
            advanced = await self._durable_state_store.compare_and_set_state(
                key,
                _published_audit_outbox_tombstone(stored, revision=revision + 1),
                expected_revision=revision,
            )
            if advanced:
                await self._compact_audit_outbox_tombstones()
                return True
        raise RuntimeError("Saga audit outbox publication CAS retry limit exceeded")

    async def _release_audit_outbox_publication_claim(
        self: Any,
        payload: Mapping[str, Any],
        claim: PublicationClaim,
    ) -> None:
        if self._durable_state_store is None:
            return
        key = _audit_outbox_key(payload)
        for _attempt in range(16):
            stored = await self._durable_state_store.read_state(key)
            if stored is None or stored.get("status") != "publishing":
                return
            if (
                str(stored.get("claim_owner") or "") != claim.owner
                or str(stored.get("claimed_at") or "") != claim.claimed_at
            ):
                return
            revision = int(stored.get("revision", 1))
            advanced = await self._durable_state_store.compare_and_set_state(
                key,
                {
                    **dict(stored),
                    "status": "pending",
                    "revision": revision + 1,
                    "claim_owner": "",
                    "claimed_at": "",
                },
                expected_revision=revision,
            )
            if advanced:
                return
        raise RuntimeError("Saga audit outbox publication release CAS retry limit exceeded")

    async def _compact_audit_outbox_tombstones(self: Any) -> None:
        if self._durable_state_store is None:
            return
        await self._durable_state_store.delete_states_beyond(
            _AUDIT_OUTBOX_PREFIX,
            retain_newest=_AUDIT_OUTBOX_PENDING_SCAN_LIMIT + _AUDIT_OUTBOX_TOMBSTONE_RETENTION,
        )


def _audit_outbox_key(payload: Mapping[str, Any]) -> str:
    correlation_id = str(payload.get("correlation_id") or "")
    idempotency_key = str(payload.get("idempotency_key") or "")
    if not correlation_id or not idempotency_key:
        raise RuntimeError("Saga audit outbox payload requires correlation_id and idempotency_key")
    digest = hashlib.sha256(f"{correlation_id}\0{idempotency_key}".encode()).hexdigest()
    return f"{_AUDIT_OUTBOX_PREFIX}{digest}"


def _published_audit_outbox_tombstone(
    stored: Mapping[str, Any], *, revision: int
) -> dict[str, Any]:
    payload = stored.get("payload")
    payload_digest = (
        _payload_digest(payload)
        if isinstance(payload, Mapping)
        else str(stored.get("payload_digest") or "")
    )
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "status": "published",
        "correlation_id": str(stored.get("correlation_id") or ""),
        "idempotency_key": str(stored.get("idempotency_key") or ""),
        "payload_digest": payload_digest,
        "retention_window": str(_AUDIT_OUTBOX_TOMBSTONE_RETENTION),
    }


def _payload_digest(payload: Mapping[str, Any]) -> str:
    return f"sha256:{canonical_json_digest(payload)}"


def _audit_outbox_claim_expired(row: Mapping[str, Any], now: datetime) -> bool:
    return claim_expired(
        claimed_at=row.get("claimed_at"),
        now=now,
        lease=_AUDIT_OUTBOX_CLAIM_LEASE,
    )


__all__ = ["SagaAuditRuntimeMixin"]

"""Durable adapter failure windows, manual controls, and fallback alerts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol

from fdai.shared.providers.conversation_channel import ConversationChannelKind
from fdai.shared.providers.conversation_delivery import (
    AdapterBreakerMode,
    AdapterBreakerRecord,
    ConversationDeliveryStore,
)


@dataclass(frozen=True, slots=True)
class AdapterHealthConfig:
    failure_threshold: int = 3
    failure_window_seconds: int = 300

    def __post_init__(self) -> None:
        if not 1 <= self.failure_threshold <= 100:
            raise ValueError("adapter failure_threshold is invalid")
        if not 1 <= self.failure_window_seconds <= 86_400:
            raise ValueError("adapter failure_window_seconds is invalid")


@dataclass(frozen=True, slots=True)
class AdapterFallbackRoute:
    source_adapter_id: str
    target_adapter_id: str
    target_channel_kind: ConversationChannelKind
    category: str = "A2"

    def __post_init__(self) -> None:
        if not self.source_adapter_id.strip() or not self.target_adapter_id.strip():
            raise ValueError("adapter fallback route ids MUST be non-empty")
        if self.source_adapter_id == self.target_adapter_id:
            raise ValueError("adapter fallback route MUST use another adapter")
        if self.category != "A2":
            raise ValueError("adapter health fallback is limited to A2 operational alerts")


@dataclass(frozen=True, slots=True)
class AdapterHealthAuditEvent:
    event_id: str
    adapter_id: str
    action: str
    actor_id: str
    reason: str
    occurred_at: datetime
    revision: int
    fallback_adapter_id: str | None = None


class AdapterHealthAuthorizer(Protocol):
    def can_manage_adapter(self, *, actor_id: str, adapter_id: str) -> bool: ...


class AdapterFallbackAuthorizer(Protocol):
    def can_notify(self, route: AdapterFallbackRoute) -> bool: ...


class AdapterFallbackNotifier(Protocol):
    async def notify(
        self,
        *,
        route: AdapterFallbackRoute,
        breaker: AdapterBreakerRecord,
    ) -> None: ...


class AdapterHealthAuditSink(Protocol):
    async def append(self, event: AdapterHealthAuditEvent) -> None: ...


class AdapterHealthError(ValueError):
    """A breaker control was rejected without changing adapter state."""


class InMemoryAdapterHealthAuditSink:
    def __init__(self) -> None:
        self.events: list[AdapterHealthAuditEvent] = []

    async def append(self, event: AdapterHealthAuditEvent) -> None:
        self.events.append(event)


class AdapterHealthService:
    """Open on bounded failures and require authorized explicit recovery."""

    def __init__(
        self,
        *,
        store: ConversationDeliveryStore,
        audit: AdapterHealthAuditSink,
        authorizer: AdapterHealthAuthorizer,
        config: AdapterHealthConfig | None = None,
        fallback_routes: tuple[AdapterFallbackRoute, ...] = (),
        fallback_authorizer: AdapterFallbackAuthorizer | None = None,
        fallback_notifier: AdapterFallbackNotifier | None = None,
    ) -> None:
        if (fallback_routes or fallback_notifier) and fallback_authorizer is None:
            raise ValueError("adapter fallback routes require an authorizer")
        if fallback_routes and fallback_notifier is None:
            raise ValueError("adapter fallback routes require a notifier")
        self._store = store
        self._audit = audit
        self._authorizer = authorizer
        self._config = config or AdapterHealthConfig()
        self._fallback_routes = fallback_routes
        self._fallback_authorizer = fallback_authorizer
        self._fallback_notifier = fallback_notifier

    async def can_send(self, *, adapter_id: str) -> bool:
        current = await self._store.get_breaker(adapter_id)
        return current is None or current.mode is AdapterBreakerMode.CLOSED

    async def status(self, *, adapter_id: str) -> AdapterBreakerRecord | None:
        return await self._store.get_breaker(adapter_id)

    async def record_success(
        self,
        *,
        adapter_id: str,
        channel_kind: ConversationChannelKind,
        at: datetime,
    ) -> None:
        current = await self._store.get_breaker(adapter_id)
        if current is None or current.mode is not AdapterBreakerMode.CLOSED:
            return
        if not current.failure_timestamps:
            return
        await self._store.put_breaker(
            replace(
                current,
                failure_timestamps=(),
                revision=current.revision + 1,
                updated_at=at,
                updated_by="system",
                reason="delivery_succeeded",
            ),
            expected_revision=current.revision,
        )

    async def record_failure(
        self,
        *,
        adapter_id: str,
        channel_kind: ConversationChannelKind,
        at: datetime,
        error_code: str,
    ) -> None:
        current = await self._store.get_breaker(adapter_id)
        if current is not None and current.mode is not AdapterBreakerMode.CLOSED:
            return
        cutoff = at - timedelta(seconds=self._config.failure_window_seconds)
        failures = tuple(
            failure
            for failure in (current.failure_timestamps if current is not None else ())
            if failure >= cutoff
        ) + (at,)
        expected_revision = current.revision if current is not None else None
        revision = (current.revision + 1) if current is not None else 0
        opened = len(failures) >= self._config.failure_threshold
        record = AdapterBreakerRecord(
            adapter_id=adapter_id,
            channel_kind=channel_kind,
            mode=AdapterBreakerMode.OPEN if opened else AdapterBreakerMode.CLOSED,
            failure_timestamps=failures,
            revision=revision,
            updated_at=at,
            updated_by="system",
            reason=error_code,
        )
        await self._store.put_breaker(record, expected_revision=expected_revision)
        if opened:
            await self._audit_transition(record, action="opened", actor_id="system")
            await self._notify_fallback(record)

    async def pause(
        self,
        *,
        adapter_id: str,
        channel_kind: ConversationChannelKind,
        actor_id: str,
        reason: str,
        at: datetime,
    ) -> AdapterBreakerRecord:
        self._authorize(actor_id=actor_id, adapter_id=adapter_id)
        current = await self._store.get_breaker(adapter_id)
        expected_revision = current.revision if current is not None else None
        record = AdapterBreakerRecord(
            adapter_id=adapter_id,
            channel_kind=channel_kind,
            mode=AdapterBreakerMode.PAUSED,
            failure_timestamps=current.failure_timestamps if current is not None else (),
            revision=(current.revision + 1) if current is not None else 0,
            updated_at=at,
            updated_by=actor_id,
            reason=_reason(reason),
        )
        await self._store.put_breaker(record, expected_revision=expected_revision)
        await self._audit_transition(record, action="paused", actor_id=actor_id)
        return record

    async def resume(
        self,
        *,
        adapter_id: str,
        actor_id: str,
        reason: str,
        at: datetime,
    ) -> AdapterBreakerRecord:
        self._authorize(actor_id=actor_id, adapter_id=adapter_id)
        current = await self._store.get_breaker(adapter_id)
        if current is None or current.mode is AdapterBreakerMode.CLOSED:
            raise AdapterHealthError("adapter is not paused or open")
        record = replace(
            current,
            mode=AdapterBreakerMode.CLOSED,
            failure_timestamps=(),
            revision=current.revision + 1,
            updated_at=at,
            updated_by=actor_id,
            reason=_reason(reason),
        )
        await self._store.put_breaker(record, expected_revision=current.revision)
        await self._audit_transition(record, action="resumed", actor_id=actor_id)
        return record

    def _authorize(self, *, actor_id: str, adapter_id: str) -> None:
        if not self._authorizer.can_manage_adapter(actor_id=actor_id, adapter_id=adapter_id):
            raise AdapterHealthError("actor is not authorized to manage adapter")

    async def _notify_fallback(self, breaker: AdapterBreakerRecord) -> None:
        if self._fallback_authorizer is None or self._fallback_notifier is None:
            return
        for route in self._fallback_routes:
            if route.source_adapter_id != breaker.adapter_id:
                continue
            if not self._fallback_authorizer.can_notify(route):
                await self._audit_transition(
                    breaker,
                    action="fallback_denied",
                    actor_id="system",
                    fallback_adapter_id=route.target_adapter_id,
                )
                continue
            try:
                await self._fallback_notifier.notify(route=route, breaker=breaker)
            except Exception:
                await self._audit_transition(
                    breaker,
                    action="fallback_failed",
                    actor_id="system",
                    fallback_adapter_id=route.target_adapter_id,
                )
            else:
                await self._audit_transition(
                    breaker,
                    action="fallback_notified",
                    actor_id="system",
                    fallback_adapter_id=route.target_adapter_id,
                )

    async def _audit_transition(
        self,
        record: AdapterBreakerRecord,
        *,
        action: str,
        actor_id: str,
        fallback_adapter_id: str | None = None,
    ) -> None:
        raw = f"{record.adapter_id}\0{record.revision}\0{action}\0{fallback_adapter_id or ''}"
        event_id = "adapter-health:" + hashlib.sha256(raw.encode()).hexdigest()[:32]
        await self._audit.append(
            AdapterHealthAuditEvent(
                event_id=event_id,
                adapter_id=record.adapter_id,
                action=action,
                actor_id=actor_id,
                reason=record.reason,
                occurred_at=record.updated_at,
                revision=record.revision,
                fallback_adapter_id=fallback_adapter_id,
            )
        )


def _reason(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 512:
        raise AdapterHealthError("adapter transition reason MUST be bounded non-empty text")
    return normalized


__all__ = [
    "AdapterFallbackAuthorizer",
    "AdapterFallbackNotifier",
    "AdapterFallbackRoute",
    "AdapterHealthAuditEvent",
    "AdapterHealthAuditSink",
    "AdapterHealthAuthorizer",
    "AdapterHealthConfig",
    "AdapterHealthError",
    "AdapterHealthService",
    "InMemoryAdapterHealthAuditSink",
]

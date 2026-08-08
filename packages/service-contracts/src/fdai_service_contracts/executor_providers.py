"""Provider-neutral protocols and value records used by the Executor service."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from fdai_service_contracts.executor_models import ActionStopCondition, Mode


@dataclass(frozen=True, slots=True)
class PublishReceipt:
    """Broker acknowledgement of a published record."""

    topic: str
    partition: int
    offset: int | None


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """One record delivered by an event subscriber."""

    topic: str
    key: str
    payload: Mapping[str, Any]
    offset: int | None


class IncidentAppendStatus(StrEnum):
    """Atomic incident persistence result returned by StateStore."""

    APPLIED = "applied"
    DUPLICATE = "duplicate"


@runtime_checkable
class EventBus(Protocol):
    """At-least-once, per-key ordered event transport."""

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt: ...

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]: ...

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None: ...


@runtime_checkable
class StateStore(Protocol):
    """Append-only audit and tracked state contract."""

    async def append_audit_entry(self, entry: Mapping[str, Any]) -> None: ...

    async def verify_chain(self) -> bool: ...

    async def read_state(self, key: str) -> Mapping[str, Any] | None: ...

    async def write_state(self, key: str, value: Mapping[str, Any]) -> None: ...

    async def write_state_if_absent(self, key: str, value: Mapping[str, Any]) -> bool: ...

    async def write_state_with_audit_if_absent(
        self,
        key: str,
        value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool: ...

    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool: ...

    async def find_state(
        self,
        prefix: str,
        *,
        field: str,
        value: str,
    ) -> Mapping[str, Any] | None: ...

    async def read_states(
        self,
        prefix: str,
        *,
        limit: int,
    ) -> tuple[Mapping[str, Any], ...]: ...

    async def read_state_page(
        self,
        prefix: str,
        *,
        limit: int,
        offset: int = 0,
        field: str | None = None,
        value: str | None = None,
    ) -> tuple[tuple[Mapping[str, Any], ...], int]: ...

    async def append_incident_transition(
        self,
        entry: Mapping[str, Any],
    ) -> IncidentAppendStatus: ...

    async def read_incident_transitions(self) -> tuple[Mapping[str, Any], ...]: ...


@runtime_checkable
class ResourceLock(Protocol):
    """Serialize critical sections for one logical target."""

    def acquire(self, resource_id: str) -> AbstractAsyncContextManager[None]: ...


@runtime_checkable
class IdempotencyStore(Protocol):
    """Durable first-writer-wins result map for mutating actions."""

    async def seen(self, key: str) -> Mapping[str, Any] | None: ...

    async def record(self, key: str, result: Mapping[str, Any]) -> bool: ...


@dataclass(frozen=True, slots=True)
class IdentityToken:
    """Short-lived audience-scoped OIDC token."""

    token: str
    expires_at: datetime
    audience: str


@runtime_checkable
class WorkloadIdentity(Protocol):
    """Issue short-lived OIDC tokens for an exact audience."""

    async def get_token(self, audience: str) -> IdentityToken: ...


class DirectApiOutcome(StrEnum):
    """Terminal state of one direct-API provider call."""

    SUCCEEDED = "succeeded"
    ALREADY_APPLIED = "already_applied"
    PRECONDITION_FAILED = "precondition_failed"
    STOPPED = "stopped"
    FAILED = "failed"


class DirectApiError(RuntimeError):
    """Typed provider-boundary failure safe for audit classification."""

    __slots__ = ("kind",)

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class DirectApiPromotionError(DirectApiError):
    def __init__(self, message: str) -> None:
        super().__init__(kind="promotion", message=message)


class DirectApiPreconditionError(DirectApiError):
    def __init__(self, message: str) -> None:
        super().__init__(kind="precondition", message=message)


class DirectApiAuthenticationError(DirectApiError):
    def __init__(self, message: str) -> None:
        super().__init__(kind="authentication_failed", message=message)


class DirectApiPermissionDeniedError(DirectApiError):
    def __init__(self, message: str) -> None:
        super().__init__(kind="permission_denied", message=message)


class DirectApiPolicyDeniedError(DirectApiError):
    def __init__(self, message: str) -> None:
        super().__init__(kind="policy_denied", message=message)


class DirectApiNetworkDeniedError(DirectApiError):
    def __init__(self, message: str) -> None:
        super().__init__(kind="network_denied", message=message)


@dataclass(frozen=True, slots=True)
class DirectApiRequest:
    """Immutable provider-neutral direct-API dispatch intent."""

    action_id: UUID
    idempotency_key: str
    action_type_name: str
    rule_ids: tuple[str, ...]
    resource_ref: str
    arguments: Mapping[str, object] = field(default_factory=dict)
    labels: tuple[str, ...] = ("shadow",)
    mode: Mode = Mode.SHADOW
    stop_conditions: tuple[ActionStopCondition, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DirectApiReceipt:
    """Provider-issued receipt for one dispatch attempt."""

    outcome: DirectApiOutcome
    receipt_ref: str
    already_existed: bool = False
    rollback_succeeded: bool | None = None
    detail: str | None = None


@runtime_checkable
class DirectApiExecutor(Protocol):
    """Idempotently dispatch a mutation through a substrate API."""

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt: ...


__all__ = [
    "DirectApiAuthenticationError",
    "DirectApiError",
    "DirectApiExecutor",
    "DirectApiNetworkDeniedError",
    "DirectApiOutcome",
    "DirectApiPermissionDeniedError",
    "DirectApiPolicyDeniedError",
    "DirectApiPreconditionError",
    "DirectApiPromotionError",
    "DirectApiReceipt",
    "DirectApiRequest",
    "EventBus",
    "EventEnvelope",
    "IdempotencyStore",
    "IdentityToken",
    "IncidentAppendStatus",
    "PublishReceipt",
    "ResourceLock",
    "StateStore",
    "WorkloadIdentity",
]

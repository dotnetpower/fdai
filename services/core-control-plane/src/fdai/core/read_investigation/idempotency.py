"""Idempotent run records for direct and streamed read investigations."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from fdai.core.read_investigation.models import ReadInvestigationRequest, ReadInvestigationResult

_MAX_ID = 256
MAX_READ_INVESTIGATION_ATTEMPTS = 3


class ReadInvestigationRunState(StrEnum):
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"

    @property
    def terminal(self) -> bool:
        return self in {
            ReadInvestigationRunState.COMPLETED,
            ReadInvestigationRunState.FAILED,
            ReadInvestigationRunState.EXPIRED,
        }


class ReadInvestigationRunMode(StrEnum):
    DIRECT = "direct"
    STREAMED = "streamed"


@dataclass(frozen=True, slots=True)
class ReadInvestigationRunUsage:
    tool_calls: int
    execution_duration_ms: int
    reserved_cost_microusd: int = 0
    measured_cost_microusd: int | None = None

    def __post_init__(self) -> None:
        if min(self.tool_calls, self.execution_duration_ms, self.reserved_cost_microusd) < 0:
            raise ValueError("run usage MUST be non-negative")
        if self.measured_cost_microusd is not None and self.measured_cost_microusd < 0:
            raise ValueError("measured_cost_microusd MUST be non-negative")


@dataclass(frozen=True, slots=True)
class ReadInvestigationRunLease:
    owner: str
    token: str
    expires_at: datetime

    def __post_init__(self) -> None:
        _identifier("lease owner", self.owner)
        _identifier("lease token", self.token)
        _aware("lease expires_at", self.expires_at)


@dataclass(frozen=True, slots=True)
class ReadInvestigationRunRecord:
    owner_principal_id: str
    idempotency_key: str
    request_digest: str
    request: ReadInvestigationRequest
    mode: ReadInvestigationRunMode
    state: ReadInvestigationRunState
    revision: int
    created_at: datetime
    updated_at: datetime
    retention_until: datetime
    attempt_count: int = 1
    terminal_at: datetime | None = None
    lease: ReadInvestigationRunLease | None = None
    result: ReadInvestigationResult | None = None
    usage: ReadInvestigationRunUsage | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        _identifier("owner_principal_id", self.owner_principal_id)
        _identifier("idempotency_key", self.idempotency_key)
        _request_digest(self.request_digest)
        if self.request_digest != read_investigation_request_digest(self.request):
            raise ValueError("request_digest MUST match the canonical request projection")
        _aware("created_at", self.created_at)
        _aware("updated_at", self.updated_at)
        _aware("retention_until", self.retention_until)
        if self.terminal_at is not None:
            _aware("terminal_at", self.terminal_at)
        if self.revision < 1:
            raise ValueError("revision MUST be >= 1")
        if not 1 <= self.attempt_count <= MAX_READ_INVESTIGATION_ATTEMPTS:
            raise ValueError("attempt_count is outside the bounded retry range")
        if self.attempt_count > self.revision:
            raise ValueError("attempt_count cannot exceed revision")
        if not self.created_at <= self.updated_at <= self.retention_until:
            raise ValueError("run timestamps MUST be ordered")

        if self.state in {ReadInvestigationRunState.CLAIMED, ReadInvestigationRunState.RUNNING}:
            if self.lease is None:
                raise ValueError("claimed/running run MUST carry a lease")
            if self.terminal_at is not None:
                raise ValueError("claimed/running run cannot carry terminal_at")
            if self.result is not None or self.usage is not None or self.failure_reason is not None:
                raise ValueError("claimed/running run cannot carry terminal fields")
            return

        if self.lease is not None:
            raise ValueError("terminal run cannot carry a lease")
        if self.terminal_at is None:
            raise ValueError("terminal run MUST carry terminal_at")
        if self.terminal_at != self.updated_at:
            raise ValueError("terminal run terminal_at MUST match updated_at")
        if self.usage is None:
            raise ValueError("terminal run MUST carry usage")

        if self.state is ReadInvestigationRunState.COMPLETED:
            if self.result is None:
                raise ValueError("completed run MUST carry a replay result")
            if read_investigation_request_digest(self.result.request) != self.request_digest:
                raise ValueError("completed run result MUST reference the same canonical request")
            if self.failure_reason is not None:
                raise ValueError("completed run cannot carry failure_reason")
            return

        if self.result is not None:
            raise ValueError("failed/expired runs cannot carry a replay result")
        if self.failure_reason is None:
            raise ValueError("failed/expired runs MUST carry failure_reason")
        _identifier("failure_reason", self.failure_reason)


class ReadInvestigationRunConflictError(RuntimeError):
    """A lease/CAS write lost ownership or idempotency conflict was detected."""


class ReadInvestigationRunStore(Protocol):
    async def claim(
        self,
        *,
        owner_principal_id: str,
        request: ReadInvestigationRequest,
        mode: ReadInvestigationRunMode,
        lease_owner: str,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        retention_seconds: int,
    ) -> tuple[ReadInvestigationRunRecord, bool]: ...

    async def get(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
    ) -> ReadInvestigationRunRecord | None: ...

    async def reclaim(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        request_digest: str,
        mode: ReadInvestigationRunMode,
        expected_revision: int,
        lease_owner: str,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        retention_seconds: int,
    ) -> ReadInvestigationRunRecord: ...

    async def start(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        now: datetime,
    ) -> ReadInvestigationRunRecord: ...

    async def complete(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        result: ReadInvestigationResult,
        usage: ReadInvestigationRunUsage,
        now: datetime,
    ) -> ReadInvestigationRunRecord: ...

    async def renew(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        lease_ceiling_at: datetime,
    ) -> ReadInvestigationRunRecord: ...

    async def fail(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        failure_reason: str,
        usage: ReadInvestigationRunUsage,
        now: datetime,
        state: ReadInvestigationRunState = ReadInvestigationRunState.FAILED,
    ) -> ReadInvestigationRunRecord: ...

    async def reconcile_expired(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[ReadInvestigationRunRecord, ...]: ...

    async def purge_retained(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[tuple[str, str], ...]: ...


class InMemoryReadInvestigationRunStore:
    """Reference CAS store for direct/streamed read-investigation idempotency."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], ReadInvestigationRunRecord] = {}
        self._lock = asyncio.Lock()

    async def claim(
        self,
        *,
        owner_principal_id: str,
        request: ReadInvestigationRequest,
        mode: ReadInvestigationRunMode,
        lease_owner: str,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        retention_seconds: int,
    ) -> tuple[ReadInvestigationRunRecord, bool]:
        _identifier("owner_principal_id", owner_principal_id)
        _identifier("idempotency_key", request.idempotency_key)
        _identifier("lease owner", lease_owner)
        _identifier("lease token", lease_token)
        _aware("claim now", now)
        if lease_seconds < 1:
            raise ValueError("lease_seconds MUST be >= 1")
        if retention_seconds < 1:
            raise ValueError("retention_seconds MUST be >= 1")
        digest = read_investigation_request_digest(request)
        key = (owner_principal_id, request.idempotency_key)
        async with self._lock:
            current = self._records.get(key)
            if current is not None:
                if current.request_digest != digest:
                    raise ReadInvestigationRunConflictError(
                        "read investigation idempotency key was reused with another request"
                    )
                return current, False
            claimed = ReadInvestigationRunRecord(
                owner_principal_id=owner_principal_id,
                idempotency_key=request.idempotency_key,
                request_digest=digest,
                request=request,
                mode=mode,
                state=ReadInvestigationRunState.CLAIMED,
                revision=1,
                created_at=now,
                updated_at=now,
                retention_until=now + timedelta(seconds=retention_seconds),
                lease=ReadInvestigationRunLease(
                    owner=lease_owner,
                    token=lease_token,
                    expires_at=now + timedelta(seconds=lease_seconds),
                ),
            )
            self._records[key] = claimed
            return claimed, True

    async def get(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
    ) -> ReadInvestigationRunRecord | None:
        return self._records.get((owner_principal_id, idempotency_key))

    async def reclaim(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        request_digest: str,
        mode: ReadInvestigationRunMode,
        expected_revision: int,
        lease_owner: str,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        retention_seconds: int,
    ) -> ReadInvestigationRunRecord:
        _identifier("owner_principal_id", owner_principal_id)
        _identifier("idempotency_key", idempotency_key)
        _request_digest(request_digest)
        _identifier("lease owner", lease_owner)
        _identifier("lease token", lease_token)
        _aware("reclaim now", now)
        if lease_seconds < 1:
            raise ValueError("lease_seconds MUST be >= 1")
        if retention_seconds < 1:
            raise ValueError("retention_seconds MUST be >= 1")
        async with self._lock:
            key = (owner_principal_id, idempotency_key)
            current = self._records.get(key)
            if current is None:
                raise LookupError("read investigation run was not found")
            if current.request_digest != request_digest:
                raise ReadInvestigationRunConflictError(
                    "read investigation idempotency key was reused with another request"
                )
            if current.revision != expected_revision:
                raise ReadInvestigationRunConflictError("read investigation revision mismatch")
            if current.state not in {
                ReadInvestigationRunState.FAILED,
                ReadInvestigationRunState.EXPIRED,
            }:
                raise ReadInvestigationRunConflictError("read investigation run is not reclaimable")
            if current.attempt_count >= MAX_READ_INVESTIGATION_ATTEMPTS:
                raise ReadInvestigationRunConflictError("read investigation retries exhausted")
            updated = replace(
                current,
                mode=mode,
                state=ReadInvestigationRunState.CLAIMED,
                revision=current.revision + 1,
                updated_at=now,
                retention_until=max(
                    current.retention_until,
                    now + timedelta(seconds=retention_seconds),
                ),
                attempt_count=current.attempt_count + 1,
                terminal_at=None,
                lease=ReadInvestigationRunLease(
                    owner=lease_owner,
                    token=lease_token,
                    expires_at=now + timedelta(seconds=lease_seconds),
                ),
                result=None,
                usage=None,
                failure_reason=None,
            )
            self._records[key] = updated
            return updated

    async def start(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        now: datetime,
    ) -> ReadInvestigationRunRecord:
        async with self._lock:
            current = self._leased(
                owner_principal_id=owner_principal_id,
                idempotency_key=idempotency_key,
                expected_revision=expected_revision,
                lease_token=lease_token,
                now=now,
                states=frozenset({ReadInvestigationRunState.CLAIMED}),
            )
            updated = replace(
                current,
                state=ReadInvestigationRunState.RUNNING,
                revision=current.revision + 1,
                updated_at=now,
            )
            self._records[(owner_principal_id, idempotency_key)] = updated
            return updated

    async def complete(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        result: ReadInvestigationResult,
        usage: ReadInvestigationRunUsage,
        now: datetime,
    ) -> ReadInvestigationRunRecord:
        async with self._lock:
            current = self._leased(
                owner_principal_id=owner_principal_id,
                idempotency_key=idempotency_key,
                expected_revision=expected_revision,
                lease_token=lease_token,
                now=now,
                states=frozenset(
                    {
                        ReadInvestigationRunState.CLAIMED,
                        ReadInvestigationRunState.RUNNING,
                    }
                ),
            )
            if read_investigation_request_digest(result.request) != current.request_digest:
                raise ReadInvestigationRunConflictError(
                    "completed result request does not match the claimed run"
                )
            updated = replace(
                current,
                state=ReadInvestigationRunState.COMPLETED,
                revision=current.revision + 1,
                updated_at=now,
                terminal_at=now,
                lease=None,
                result=result,
                usage=usage,
                failure_reason=None,
            )
            self._records[(owner_principal_id, idempotency_key)] = updated
            return updated

    async def renew(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        lease_ceiling_at: datetime,
    ) -> ReadInvestigationRunRecord:
        _aware("renew now", now)
        _aware("renew lease_ceiling_at", lease_ceiling_at)
        if lease_seconds < 1:
            raise ValueError("lease_seconds MUST be >= 1")
        if lease_ceiling_at < now:
            raise ValueError("lease_ceiling_at MUST be >= now")
        async with self._lock:
            current = self._leased(
                owner_principal_id=owner_principal_id,
                idempotency_key=idempotency_key,
                expected_revision=expected_revision,
                lease_token=lease_token,
                now=now,
                states=frozenset({ReadInvestigationRunState.RUNNING}),
            )
            if current.lease is None:  # pragma: no cover - guarded by _leased
                raise ReadInvestigationRunConflictError("read investigation lease mismatch")
            expires_at = min(now + timedelta(seconds=lease_seconds), lease_ceiling_at)
            if expires_at <= now:
                raise ReadInvestigationRunConflictError(
                    "read investigation lease ceiling exhausted"
                )
            updated = replace(
                current,
                revision=current.revision + 1,
                updated_at=now,
                lease=replace(current.lease, expires_at=expires_at),
            )
            self._records[(owner_principal_id, idempotency_key)] = updated
            return updated

    async def fail(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        failure_reason: str,
        usage: ReadInvestigationRunUsage,
        now: datetime,
        state: ReadInvestigationRunState = ReadInvestigationRunState.FAILED,
    ) -> ReadInvestigationRunRecord:
        if state not in {ReadInvestigationRunState.FAILED, ReadInvestigationRunState.EXPIRED}:
            raise ValueError("run failure state MUST be failed or expired")
        async with self._lock:
            current = self._leased(
                owner_principal_id=owner_principal_id,
                idempotency_key=idempotency_key,
                expected_revision=expected_revision,
                lease_token=lease_token,
                now=now,
                states=frozenset(
                    {
                        ReadInvestigationRunState.CLAIMED,
                        ReadInvestigationRunState.RUNNING,
                    }
                ),
            )
            updated = replace(
                current,
                state=state,
                revision=current.revision + 1,
                updated_at=now,
                terminal_at=now,
                lease=None,
                result=None,
                usage=usage,
                failure_reason=failure_reason,
            )
            self._records[(owner_principal_id, idempotency_key)] = updated
            return updated

    async def reconcile_expired(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[ReadInvestigationRunRecord, ...]:
        _aware("reconcile now", now)
        if not 1 <= limit <= 10_000:
            raise ValueError("reconcile limit MUST be in [1, 10000]")
        reconciled: list[ReadInvestigationRunRecord] = []
        async with self._lock:
            for key, current in sorted(
                self._records.items(),
                key=lambda item: (item[1].updated_at, item[0][0], item[0][1]),
            ):
                if len(reconciled) >= limit:
                    break
                if current.state.terminal or current.lease is None:
                    continue
                if current.lease.expires_at > now:
                    continue
                updated = replace(
                    current,
                    state=ReadInvestigationRunState.EXPIRED,
                    revision=current.revision + 1,
                    updated_at=now,
                    terminal_at=now,
                    lease=None,
                    result=None,
                    usage=ReadInvestigationRunUsage(
                        tool_calls=0,
                        execution_duration_ms=0,
                        reserved_cost_microusd=current.request.budget.max_cost_microusd,
                    ),
                    failure_reason="lease_expired",
                )
                self._records[key] = updated
                reconciled.append(updated)
        return tuple(reconciled)

    async def purge_retained(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[tuple[str, str], ...]:
        _aware("purge now", now)
        if not 1 <= limit <= 10_000:
            raise ValueError("purge limit MUST be in [1, 10000]")
        purged: list[tuple[str, str]] = []
        async with self._lock:
            for key, current in sorted(
                self._records.items(),
                key=lambda item: (item[1].retention_until, item[0][0], item[0][1]),
            ):
                if len(purged) >= limit:
                    break
                if not current.state.terminal:
                    continue
                if current.retention_until > now:
                    continue
                del self._records[key]
                purged.append(key)
        return tuple(purged)

    def _leased(
        self,
        *,
        owner_principal_id: str,
        idempotency_key: str,
        expected_revision: int,
        lease_token: str,
        now: datetime,
        states: frozenset[ReadInvestigationRunState],
    ) -> ReadInvestigationRunRecord:
        _aware("lease now", now)
        current = self._records.get((owner_principal_id, idempotency_key))
        if current is None:
            raise LookupError("read investigation run was not found")
        if current.state.terminal:
            raise ReadInvestigationRunConflictError("terminal read investigation run is immutable")
        if current.revision != expected_revision:
            raise ReadInvestigationRunConflictError("read investigation revision mismatch")
        if current.state not in states:
            raise ReadInvestigationRunConflictError("read investigation state transition mismatch")
        lease = current.lease
        if lease is None or lease.token != lease_token:
            raise ReadInvestigationRunConflictError("read investigation lease mismatch")
        if lease.expires_at <= now:
            raise ReadInvestigationRunConflictError("read investigation lease expired")
        return current


def read_investigation_request_projection(request: ReadInvestigationRequest) -> dict[str, object]:
    """Return the provider-neutral canonical projection used for request digesting."""

    return {
        "intent": request.intent.value,
        "selector": {
            "name": request.selector.name,
            "scope_ref": request.selector.scope_ref,
            "resource_type": request.selector.resource_type,
            "resource_group": request.selector.resource_group,
        },
        "lookback_seconds": request.lookback_seconds,
        "requested_evidence": [tool_id.value for tool_id in request.requested_evidence],
        "budget": {
            "max_wall_seconds": request.budget.max_wall_seconds,
            "max_cost_microusd": request.budget.max_cost_microusd,
            "max_tool_calls": request.budget.max_tool_calls,
            "max_results": request.budget.max_results,
            "max_output_bytes": request.budget.max_output_bytes,
        },
        "explicit_deep": request.explicit_deep,
    }


def read_investigation_request_digest(request: ReadInvestigationRequest) -> str:
    payload = json.dumps(
        read_investigation_request_projection(request),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _identifier(name: str, value: str) -> None:
    if not value.strip() or len(value) > _MAX_ID or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be a bounded identifier")


def _request_digest(value: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("request_digest MUST be a lowercase SHA-256 digest")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} MUST be timezone-aware")


__all__ = [
    "InMemoryReadInvestigationRunStore",
    "MAX_READ_INVESTIGATION_ATTEMPTS",
    "ReadInvestigationRunConflictError",
    "ReadInvestigationRunLease",
    "ReadInvestigationRunMode",
    "ReadInvestigationRunRecord",
    "ReadInvestigationRunState",
    "ReadInvestigationRunStore",
    "ReadInvestigationRunUsage",
    "read_investigation_request_digest",
    "read_investigation_request_projection",
]

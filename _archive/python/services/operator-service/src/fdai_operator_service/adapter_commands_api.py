"""Separately authenticated /commands/adapters/* handler for status, pause, and resume.

Adapter health controls live in the channel command surface and MUST NOT be
mounted in the Console Operator API. Every command carries
``execution_authority="none"`` and mutating commands require Owner or Approver
RBAC authorization, bounded non-empty reason validation, and append-only audit
receipt emission.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from fdai_operator_service.families.conversation.channel_delivery_models import (
    ChannelAdapterBreaker,
    ChannelBreakerMode,
    ChannelKind,
)

_ADAPTER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_COMMAND_PATH_RE = re.compile(
    r"^/commands/adapters/(?P<adapter_id>[a-z0-9][a-z0-9_-]{0,63})/(?P<action>status|pause|resume)$"
)
_READ_ROLES = frozenset({"reader", "contributor", "approver", "owner"})
_MANAGE_ROLES = frozenset({"approver", "owner"})
_MAX_REASON_CHARS = 512


class AdapterCommandError(ValueError):
    """Raised when an adapter command violates authentication, RBAC, route, or state rules."""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class AdapterCommandPrincipal:
    """Authenticated caller identity on the dedicated channel-command surface."""

    principal_id: str
    roles: frozenset[str]
    authenticated_surface: str = "channel-adapter-commands"
    allowed_adapters: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class AdapterCommandAuditReceipt:
    """Immutable append-only audit receipt emitted for pause and resume transitions."""

    receipt_id: str
    adapter_id: str
    channel_kind: str
    command: Literal["pause", "resume"]
    actor_id: str
    actor_roles: tuple[str, ...]
    reason: str
    previous_mode: str
    new_mode: str
    revision: int
    occurred_at: datetime
    execution_authority: Literal["none"]
    receipt_digest: str


@dataclass(frozen=True, slots=True)
class AdapterCommandResponse:
    """Serialized response envelope returned by `/commands/adapters/*`."""

    surface: Literal["channel-adapter-commands"]
    mounted_in_console_api: Literal[False]
    execution_authority: Literal["none"]
    adapter_id: str
    channel_kind: str
    command: Literal["status", "pause", "resume"]
    mode: str
    can_send: bool
    revision: int
    updated_at: str | None
    updated_by: str
    reason: str
    failure_count: int
    audit_receipt_id: str | None = None
    audit_receipt_digest: str | None = None
    state_digest: str = ""

    def __post_init__(self) -> None:
        material = {
            "adapter_id": self.adapter_id,
            "audit_receipt_digest": self.audit_receipt_digest,
            "audit_receipt_id": self.audit_receipt_id,
            "can_send": self.can_send,
            "channel_kind": self.channel_kind,
            "command": self.command,
            "execution_authority": self.execution_authority,
            "failure_count": self.failure_count,
            "mode": self.mode,
            "mounted_in_console_api": self.mounted_in_console_api,
            "reason": self.reason,
            "revision": self.revision,
            "surface": self.surface,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
        }
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        expected = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
        if not self.state_digest:
            object.__setattr__(self, "state_digest", expected)
        elif self.state_digest != expected:
            raise ValueError("AdapterCommandResponse.state_digest mismatch")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> dict[str, object]:
        return asdict(self)


class AdapterBreakerStore(Protocol):
    """Minimal breaker persistence seam required by the adapter command controller."""

    async def get_breaker(self, adapter_id: str) -> ChannelAdapterBreaker | None: ...
    async def put_breaker(
        self, record: ChannelAdapterBreaker, *, expected_revision: int | None
    ) -> ChannelAdapterBreaker: ...


class InMemoryAdapterCommandBreakerStore:
    """Deterministic in-memory breaker store with CAS semantics for tests and local wiring."""

    def __init__(self, initial: tuple[ChannelAdapterBreaker, ...] = ()) -> None:
        self._breakers: dict[str, ChannelAdapterBreaker] = {r.adapter_id: r for r in initial}

    async def get_breaker(self, adapter_id: str) -> ChannelAdapterBreaker | None:
        return self._breakers.get(adapter_id)

    async def put_breaker(
        self, record: ChannelAdapterBreaker, *, expected_revision: int | None
    ) -> ChannelAdapterBreaker:
        current = self._breakers.get(record.adapter_id)
        actual_revision = current.revision if current is not None else None
        if actual_revision != expected_revision:
            raise AdapterCommandError(
                "revision_conflict", "adapter breaker revision CAS failed", status_code=409
            )
        self._breakers[record.adapter_id] = record
        return record


class AdapterCommandController:
    """Separately authenticated `/commands/adapters/*` controller for status, pause, and resume."""

    def __init__(
        self,
        *,
        store: AdapterBreakerStore,
        adapter_channels: Mapping[str, ChannelKind] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._adapter_channels: dict[str, ChannelKind] = dict(
            adapter_channels or {"slack": ChannelKind.SLACK, "teams": ChannelKind.TEAMS}
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        self._audit_receipts: list[AdapterCommandAuditReceipt] = []

    @property
    def audit_receipts(self) -> tuple[AdapterCommandAuditReceipt, ...]:
        """Return append-only audit receipts emitted by pause and resume commands."""
        return tuple(self._audit_receipts)

    async def handle(
        self,
        *,
        path: str,
        method: str,
        principal: AdapterCommandPrincipal | None,
        payload: Mapping[str, Any] | None = None,
    ) -> AdapterCommandResponse:
        """Dispatch a `/commands/adapters/{adapter_id}/{status|pause|resume}` request."""
        match = _COMMAND_PATH_RE.fullmatch(path.strip())
        if match is None:
            raise AdapterCommandError(
                "invalid_command_path",
                "path MUST match /commands/adapters/{adapter_id}/{status|pause|resume}",
                status_code=404,
            )
        adapter_id, action = match.group("adapter_id"), match.group("action")
        normalized_method = method.strip().upper()
        if action == "status":
            if normalized_method != "GET":
                raise AdapterCommandError("method_not_allowed", "requires GET", status_code=405)
            return await self.status(principal=principal, adapter_id=adapter_id)
        if normalized_method != "POST":
            raise AdapterCommandError("method_not_allowed", "requires POST", status_code=405)
        if not isinstance(payload, Mapping) or not isinstance(payload.get("reason"), str):
            raise AdapterCommandError(
                "invalid_reason", "payload.reason MUST be a non-empty string", status_code=400
            )
        raw_reason = str(payload["reason"])
        expected_rev = payload.get("expected_revision")
        if action == "pause":
            return await self.pause(
                principal=principal,
                adapter_id=adapter_id,
                reason=raw_reason,
                expected_revision=expected_rev,
            )
        return await self.resume(
            principal=principal,
            adapter_id=adapter_id,
            reason=raw_reason,
            expected_revision=expected_rev,
        )

    async def status(
        self, *, principal: AdapterCommandPrincipal | None, adapter_id: str
    ) -> AdapterCommandResponse:
        """Return current breaker status for ``adapter_id`` without mutating state."""
        self._authorize(principal=principal, adapter_id=adapter_id, mutate=False)
        channel_kind = self._resolve_channel_kind(adapter_id)
        current = await self._store.get_breaker(adapter_id)
        if current is None:
            return AdapterCommandResponse(
                surface="channel-adapter-commands",
                mounted_in_console_api=False,
                execution_authority="none",
                adapter_id=adapter_id,
                channel_kind=channel_kind.value,
                command="status",
                mode=ChannelBreakerMode.CLOSED.value,
                can_send=True,
                revision=0,
                updated_at=None,
                updated_by="system",
                reason="initialized",
                failure_count=0,
            )
        return _response_from_breaker(current, command="status", receipt=None)

    async def pause(
        self,
        *,
        principal: AdapterCommandPrincipal | None,
        adapter_id: str,
        reason: str,
        expected_revision: int | None = None,
    ) -> AdapterCommandResponse:
        """Pause ``adapter_id`` with Owner/Approver RBAC and append-only audit receipt."""
        actor_id, roles = self._authorize(principal=principal, adapter_id=adapter_id, mutate=True)
        normalized_reason = _validate_reason(reason)
        channel_kind = self._resolve_channel_kind(adapter_id)
        now = _ensure_aware(self._clock())
        current = await self._store.get_breaker(adapter_id)
        if expected_revision is not None:
            if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
                raise AdapterCommandError(
                    "invalid_expected_revision",
                    "expected_revision must be an integer",
                    status_code=400,
                )
            actual_rev = current.revision if current is not None else 0
            if actual_rev != expected_revision:
                raise AdapterCommandError(
                    "revision_conflict",
                    "adapter breaker revision conflict",
                    status_code=409,
                )
        prev_mode = current.mode.value if current is not None else ChannelBreakerMode.CLOSED.value
        updated = ChannelAdapterBreaker(
            adapter_id=adapter_id,
            channel_kind=current.channel_kind if current is not None else channel_kind,
            mode=ChannelBreakerMode.PAUSED,
            failure_timestamps=current.failure_timestamps if current is not None else (),
            revision=(current.revision + 1) if current is not None else 0,
            updated_at=now,
            updated_by=actor_id,
            reason=normalized_reason,
        )
        stored = await self._store.put_breaker(
            updated, expected_revision=current.revision if current is not None else None
        )
        receipt = self._append_audit(stored, "pause", actor_id, roles, prev_mode)
        return _response_from_breaker(stored, command="pause", receipt=receipt)

    async def resume(
        self,
        *,
        principal: AdapterCommandPrincipal | None,
        adapter_id: str,
        reason: str,
        expected_revision: int | None = None,
    ) -> AdapterCommandResponse:
        """Resume an open or paused adapter with Owner/Approver RBAC and audit receipt."""
        actor_id, roles = self._authorize(principal=principal, adapter_id=adapter_id, mutate=True)
        normalized_reason = _validate_reason(reason)
        self._resolve_channel_kind(adapter_id)
        now = _ensure_aware(self._clock())
        current = await self._store.get_breaker(adapter_id)
        if current is None or current.mode is ChannelBreakerMode.CLOSED:
            raise AdapterCommandError(
                "adapter_not_paused_or_open", "adapter is neither paused nor open", status_code=409
            )
        if expected_revision is not None:
            if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
                raise AdapterCommandError(
                    "invalid_expected_revision",
                    "expected_revision must be an integer",
                    status_code=400,
                )
            if current.revision != expected_revision:
                raise AdapterCommandError(
                    "revision_conflict",
                    "adapter breaker revision conflict",
                    status_code=409,
                )
        updated = replace(
            current,
            mode=ChannelBreakerMode.CLOSED,
            failure_timestamps=(),
            revision=current.revision + 1,
            updated_at=now,
            updated_by=actor_id,
            reason=normalized_reason,
        )
        stored = await self._store.put_breaker(updated, expected_revision=current.revision)
        receipt = self._append_audit(stored, "resume", actor_id, roles, current.mode.value)
        return _response_from_breaker(stored, command="resume", receipt=receipt)

    def _resolve_channel_kind(self, adapter_id: str) -> ChannelKind:
        if _ADAPTER_ID_RE.fullmatch(adapter_id) is None:
            raise AdapterCommandError("invalid_adapter_id", "invalid adapter_id", status_code=400)
        channel_kind = self._adapter_channels.get(adapter_id)
        if channel_kind is None:
            raise AdapterCommandError("unknown_adapter", f"unknown {adapter_id}", status_code=404)
        return channel_kind

    def _authorize(
        self, *, principal: AdapterCommandPrincipal | None, adapter_id: str, mutate: bool
    ) -> tuple[str, tuple[str, ...]]:
        if principal is None or not principal.principal_id.strip():
            raise AdapterCommandError("unauthenticated", "principal is required", status_code=401)
        if principal.authenticated_surface != "channel-adapter-commands":
            raise AdapterCommandError(
                "invalid_auth_surface",
                "console tokens MUST NOT invoke /commands/adapters/*",
                status_code=403,
            )
        roles = tuple(sorted({r.strip().lower() for r in principal.roles if r.strip()}))
        if not (set(roles) & (_MANAGE_ROLES if mutate else _READ_ROLES)):
            raise AdapterCommandError("forbidden_role", "insufficient RBAC role", status_code=403)
        if principal.allowed_adapters is not None and adapter_id not in principal.allowed_adapters:
            raise AdapterCommandError("adapter_scope_denied", "adapter denied", status_code=403)
        return principal.principal_id.strip(), roles

    def _append_audit(
        self,
        breaker: ChannelAdapterBreaker,
        command: Literal["pause", "resume"],
        actor_id: str,
        actor_roles: tuple[str, ...],
        previous_mode: str,
    ) -> AdapterCommandAuditReceipt:
        if breaker.updated_at is None:
            raise ValueError("breaker.updated_at MUST be set before audit emission")
        occurred_at = _ensure_aware(breaker.updated_at)
        material = {
            "actor_id": actor_id,
            "actor_roles": list(actor_roles),
            "adapter_id": breaker.adapter_id,
            "channel_kind": breaker.channel_kind.value,
            "command": command,
            "execution_authority": "none",
            "new_mode": breaker.mode.value,
            "occurred_at": occurred_at.isoformat(),
            "previous_mode": previous_mode,
            "reason": breaker.reason,
            "revision": breaker.revision,
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        receipt = AdapterCommandAuditReceipt(
            receipt_id=f"adapter-cmd:{breaker.adapter_id}:{breaker.revision}:{digest[7:23]}",
            adapter_id=breaker.adapter_id,
            channel_kind=breaker.channel_kind.value,
            command=command,
            actor_id=actor_id,
            actor_roles=actor_roles,
            reason=breaker.reason,
            previous_mode=previous_mode,
            new_mode=breaker.mode.value,
            revision=breaker.revision,
            occurred_at=occurred_at,
            execution_authority="none",
            receipt_digest=digest,
        )
        self._audit_receipts.append(receipt)
        return receipt


def _response_from_breaker(
    breaker: ChannelAdapterBreaker,
    *,
    command: Literal["status", "pause", "resume"],
    receipt: AdapterCommandAuditReceipt | None,
) -> AdapterCommandResponse:
    return AdapterCommandResponse(
        surface="channel-adapter-commands",
        mounted_in_console_api=False,
        execution_authority="none",
        adapter_id=breaker.adapter_id,
        channel_kind=breaker.channel_kind.value,
        command=command,
        mode=breaker.mode.value,
        can_send=breaker.mode is ChannelBreakerMode.CLOSED,
        revision=breaker.revision,
        updated_at=breaker.updated_at.astimezone(UTC).isoformat() if breaker.updated_at else None,
        updated_by=breaker.updated_by,
        reason=breaker.reason,
        failure_count=len(breaker.failure_timestamps),
        audit_receipt_id=receipt.receipt_id if receipt is not None else None,
        audit_receipt_digest=receipt.receipt_digest if receipt is not None else None,
    )


def _validate_reason(reason: str) -> str:
    normalized = reason.strip()
    if (
        not normalized
        or len(normalized) > _MAX_REASON_CHARS
        or any(ord(ch) < 32 for ch in normalized)
    ):
        raise AdapterCommandError("invalid_reason", "reason must be 1..512 chars", status_code=400)
    return normalized


def _ensure_aware(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("adapter command timestamp MUST be timezone-aware")
    return timestamp.astimezone(UTC)

"""Audited, revision-safe command service for the global kill-switch."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.shared.providers.state_store import StateStore
from fdai.shared.resilience.kill_switch import KILL_SWITCH_STATE_KEY

_MIN_REASON_CHARS = 20
_MAX_REASON_CHARS = 500
_MAX_REQUEST_ID_CHARS = 200


class KillSwitchCommandError(ValueError):
    """The requested state transition is malformed."""


class KillSwitchCommandConflictError(RuntimeError):
    """Another command changed the switch before this transition committed."""


@dataclass(frozen=True, slots=True)
class KillSwitchState:
    """Persisted emergency-stop state returned to an authorized caller."""

    engaged: bool
    revision: int
    updated_at: datetime
    updated_by: str
    reason: str
    request_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "engaged": self.engaged,
            "revision": self.revision,
            "updated_at": self.updated_at.isoformat(),
            "updated_by": self.updated_by,
            "reason": self.reason,
            "request_id": self.request_id,
        }

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> KillSwitchState:
        engaged = raw.get("engaged")
        revision = raw.get("revision")
        updated_at = raw.get("updated_at")
        updated_by = _required_state_text(raw, "updated_by")
        reason = _required_state_text(raw, "reason")
        request_id = _required_state_text(raw, "request_id")
        if not isinstance(engaged, bool):
            raise KillSwitchCommandError("kill-switch engaged MUST be a boolean")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise KillSwitchCommandError("kill-switch revision MUST be a positive integer")
        if not isinstance(updated_at, str) or not updated_at:
            raise KillSwitchCommandError("kill-switch state updated_at is incomplete")
        try:
            parsed_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise KillSwitchCommandError("kill-switch updated_at MUST be RFC 3339") from exc
        if parsed_at.tzinfo is None:
            raise KillSwitchCommandError("kill-switch updated_at MUST be timezone-aware")
        return cls(
            engaged=engaged,
            revision=revision,
            updated_at=parsed_at.astimezone(UTC),
            updated_by=updated_by,
            reason=reason,
            request_id=request_id,
        )


@dataclass(frozen=True, slots=True)
class KillSwitchCommandService:
    """Apply one immediate emergency-stop transition with atomic audit."""

    store: StateStore

    async def set_state(
        self,
        *,
        engaged: bool,
        actor_oid: str,
        reason: str,
        request_id: str,
        now: datetime | None = None,
    ) -> KillSwitchState:
        normalized_actor = _bounded_text(actor_oid, "actor_oid", minimum=1)
        normalized_reason = _bounded_text(
            reason,
            "reason",
            minimum=_MIN_REASON_CHARS,
            maximum=_MAX_REASON_CHARS,
        )
        normalized_request = _bounded_text(
            request_id,
            "request_id",
            minimum=1,
            maximum=_MAX_REQUEST_ID_CHARS,
        )
        changed_at = now or datetime.now(tz=UTC)
        if changed_at.tzinfo is None:
            raise KillSwitchCommandError("now MUST be timezone-aware")
        changed_at = changed_at.astimezone(UTC)

        current_raw = await self.store.read_state(KILL_SWITCH_STATE_KEY)
        if current_raw is not None:
            current = KillSwitchState.from_mapping(dict(current_raw))
            if current.request_id == normalized_request:
                if current.engaged != engaged or current.updated_by != normalized_actor:
                    raise KillSwitchCommandConflictError(
                        "kill-switch request_id was already used for a different transition"
                    )
                return current
            expected_revision = current.revision
        else:
            expected_revision = 0

        updated = KillSwitchState(
            engaged=engaged,
            revision=expected_revision + 1,
            updated_at=changed_at,
            updated_by=normalized_actor,
            reason=normalized_reason,
            request_id=normalized_request,
        )
        audit_entry = {
            "event_id": str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"fdai.kill-switch://{normalized_request}")
            ),
            "correlation_id": normalized_request,
            "actor": normalized_actor,
            "action_kind": (
                "system.kill-switch.engaged" if engaged else "system.kill-switch.disengaged"
            ),
            "mode": "enforce",
            "decision": "engaged" if engaged else "disengaged",
            "idempotency_key": normalized_request,
            "revision": updated.revision,
            "reason": normalized_reason,
            "timestamp": changed_at.isoformat(),
        }
        payload = updated.to_dict()
        if expected_revision == 0:
            applied = await self.store.write_state_with_audit_if_absent(
                KILL_SWITCH_STATE_KEY,
                payload,
                audit_entry,
            )
        else:
            applied = await self.store.compare_and_set_state_with_audit(
                KILL_SWITCH_STATE_KEY,
                payload,
                expected_revision=expected_revision,
                audit_entry=audit_entry,
            )
        if applied:
            return updated

        raced_raw = await self.store.read_state(KILL_SWITCH_STATE_KEY)
        if raced_raw is not None:
            raced = KillSwitchState.from_mapping(dict(raced_raw))
            if raced.request_id == normalized_request and raced.engaged == engaged:
                return raced
        raise KillSwitchCommandConflictError(
            "kill-switch state changed concurrently; retry with a new request_id"
        )


def _bounded_text(
    value: str,
    name: str,
    *,
    minimum: int,
    maximum: int = _MAX_REQUEST_ID_CHARS,
) -> str:
    normalized = value.strip()
    if len(normalized) < minimum:
        raise KillSwitchCommandError(f"{name} MUST be at least {minimum} characters")
    if len(normalized) > maximum:
        raise KillSwitchCommandError(f"{name} MUST be at most {maximum} characters")
    return normalized


def _required_state_text(raw: dict[str, Any], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise KillSwitchCommandError(f"kill-switch state {name} is incomplete")
    return value


__all__ = [
    "KillSwitchCommandConflictError",
    "KillSwitchCommandError",
    "KillSwitchCommandService",
    "KillSwitchState",
]

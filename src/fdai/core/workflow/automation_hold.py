"""Durable target automation holds for incomplete workflow recovery."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.shared.providers.state_store import StateStore

_KEY_PREFIX = "workflow:automation-hold:"


@dataclass(frozen=True, slots=True)
class StateStoreAutomationHoldLedger:
    """Issue immutable recovery holds and read their fail-closed state."""

    store: StateStore

    async def issue(
        self,
        *,
        target_ref: str,
        process_id: str,
        reason: str,
    ) -> None:
        target_digest = _target_digest(target_ref)
        record = {
            "target_digest": target_digest,
            "process_id": process_id,
            "reason": reason,
            "state": "active",
            "created_at": datetime.now(tz=UTC).isoformat(),
        }
        await self.store.write_state_with_audit_if_absent(
            _state_key(target_ref),
            record,
            {
                "actor": "fdai.core.workflow.automation_hold",
                "action_kind": "workflow.automation_hold.issued",
                **record,
            },
        )

    async def is_held(self, *, target_ref: str) -> bool:
        record = await self.store.read_state(_state_key(target_ref))
        if record is None:
            return False
        return not (
            record.get("target_digest") == _target_digest(target_ref)
            and record.get("state") == "released"
        )


def _target_digest(target_ref: str) -> str:
    return hashlib.sha256(target_ref.encode()).hexdigest()


def _state_key(target_ref: str) -> str:
    return f"{_KEY_PREFIX}{_target_digest(target_ref)}"


__all__ = ["StateStoreAutomationHoldLedger"]

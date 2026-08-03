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
        key = _state_key(target_ref)
        for _ in range(3):
            existing = await self.store.read_state(key)
            if existing is not None and existing.get("state") != "released":
                return
            revision = int(existing.get("revision", 0)) + 1 if existing is not None else 1
            record = {
                "target_digest": target_digest,
                "process_id": process_id,
                "reason": reason,
                "state": "active",
                "created_at": datetime.now(tz=UTC).isoformat(),
                "revision": revision,
            }
            audit_entry = {
                "actor": "fdai.core.workflow.automation_hold",
                "action_kind": "workflow.automation_hold.issued",
                **record,
            }
            if existing is None:
                if await self.store.write_state_with_audit_if_absent(
                    key,
                    record,
                    audit_entry,
                ):
                    return
            elif await self.store.compare_and_set_state_with_audit(
                key,
                record,
                expected_revision=revision - 1,
                audit_entry=audit_entry,
            ):
                return
        raise RuntimeError("automation hold issue conflicted repeatedly")

    async def recovery_eligible(
        self,
        *,
        target_ref: str,
        process_id: str,
        step_id: str,
    ) -> bool:
        record = await self.store.read_state(_state_key(target_ref))
        return bool(
            record is not None
            and record.get("target_digest") == _target_digest(target_ref)
            and record.get("state") == "active"
            and record.get("process_id") == process_id
            and step_id.startswith("compensate_")
        )

    async def release_verified(
        self,
        *,
        target_ref: str,
        process_id: str,
        recovery_receipt_ref: str,
    ) -> bool:
        key = _state_key(target_ref)
        record = await self.store.read_state(key)
        if not (
            record is not None
            and record.get("target_digest") == _target_digest(target_ref)
            and record.get("state") == "active"
            and record.get("process_id") == process_id
            and isinstance(record.get("revision"), int)
            and recovery_receipt_ref
        ):
            return False
        revision = int(record["revision"])
        released_at = datetime.now(tz=UTC).isoformat()
        released = {
            **dict(record),
            "state": "released",
            "recovery_receipt_ref": recovery_receipt_ref,
            "released_at": released_at,
            "revision": revision + 1,
        }
        return await self.store.compare_and_set_state_with_audit(
            key,
            released,
            expected_revision=revision,
            audit_entry={
                "actor": "fdai.core.workflow.automation_hold",
                "action_kind": "workflow.automation_hold.released",
                "target_digest": record["target_digest"],
                "process_id": process_id,
                "recovery_receipt_ref": recovery_receipt_ref,
                "released_at": released_at,
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

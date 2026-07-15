"""Local incident StateStore that also feeds the console read projection."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.shared.providers.state_store import IncidentAppendStatus
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class ProjectingIncidentStateStore(InMemoryStateStore):
    """Persist incident audit rows and mirror each unique row to the local UI."""

    def __init__(self, *, read_model: InMemoryConsoleReadModel) -> None:
        super().__init__()
        self._read_model = read_model
        self._projected_keys: set[str] = set()
        self._projection_lock = asyncio.Lock()

    async def append_incident_transition(
        self, entry: Mapping[str, Any]
    ) -> IncidentAppendStatus:
        key = str(entry.get("idempotency_key") or "")
        if not key:
            raise ValueError("incident transition MUST carry a non-empty idempotency_key")
        async with self._projection_lock:
            if key in self._projected_keys:
                return IncidentAppendStatus.DUPLICATE
            status = await super().append_incident_transition(entry)
            if status is IncidentAppendStatus.DUPLICATE:
                return status
            payload = dict(entry)
            members = payload.get("member_event_ids")
            event_id = (
                str(members[0])
                if isinstance(members, list) and members
                else str(payload.get("incident_id"))
            )
            payload.setdefault("event_id", event_id)
            payload.setdefault("recorded_at", payload.get("opened_at") or payload.get("at"))
            self._read_model.record_audit_entry(
                payload,
                actor=str(payload.get("actor_oid", "fdai")),
                action_kind=str(payload.get("kind", "incident.transition")),
                mode="enforce",
            )
            self._projected_keys.add(key)
            return status


__all__ = ["ProjectingIncidentStateStore"]
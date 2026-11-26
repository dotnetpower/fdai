"""Tests for the audited global kill-switch command service."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.rbac.kill_switch_command import (
    KillSwitchCommandConflictError,
    KillSwitchCommandService,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.resilience import KILL_SWITCH_STATE_KEY


async def test_transition_persists_state_and_audit_atomically() -> None:
    store = InMemoryStateStore()
    service = KillSwitchCommandService(store=store)

    state = await service.set_state(
        engaged=True,
        actor_oid="owner-1",
        reason="Emergency containment during an active incident.",
        request_id="kill-request-1",
        now=datetime(2026, 7, 18, 1, 2, 3, tzinfo=UTC),
    )

    assert state.engaged is True
    assert state.revision == 1
    persisted = await store.read_state(KILL_SWITCH_STATE_KEY)
    assert persisted == state.to_dict()
    assert len(store.audit_entries) == 1
    audit = store.audit_entries[0]["entry"]
    assert audit["action_kind"] == "system.kill-switch.engaged"
    assert audit["actor"] == "owner-1"
    assert audit["mode"] == "enforce"


async def test_same_request_replays_without_duplicate_audit() -> None:
    store = InMemoryStateStore()
    service = KillSwitchCommandService(store=store)
    kwargs = {
        "engaged": True,
        "actor_oid": "owner-1",
        "reason": "Emergency containment during an active incident.",
        "request_id": "kill-request-1",
    }

    first = await service.set_state(**kwargs)
    replay = await service.set_state(**kwargs)

    assert replay == first
    assert len(store.audit_entries) == 1


async def test_reused_request_id_with_different_intent_conflicts() -> None:
    service = KillSwitchCommandService(store=InMemoryStateStore())
    await service.set_state(
        engaged=True,
        actor_oid="owner-1",
        reason="Emergency containment during an active incident.",
        request_id="kill-request-1",
    )

    with pytest.raises(KillSwitchCommandConflictError, match="different transition"):
        await service.set_state(
            engaged=False,
            actor_oid="owner-1",
            reason="Incident is contained and normal authority may resume.",
            request_id="kill-request-1",
        )

"""Tests for the operator-triggered global KillSwitch seam."""

from __future__ import annotations

import asyncio

import pytest
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.resilience.kill_switch import (
    KILL_SWITCH_STATE_KEY,
    InMemoryKillSwitch,
    KillSwitch,
    StateStoreKillSwitch,
)


def test_default_is_disengaged() -> None:
    ks = InMemoryKillSwitch()
    assert ks.is_engaged() is False


def test_engage_and_disengage_toggle() -> None:
    ks = InMemoryKillSwitch()
    ks.engage()
    assert ks.is_engaged() is True
    ks.disengage()
    assert ks.is_engaged() is False


def test_constructed_engaged() -> None:
    ks = InMemoryKillSwitch(engaged=True)
    assert ks.is_engaged() is True


def test_satisfies_protocol() -> None:
    ks: KillSwitch = InMemoryKillSwitch()
    assert isinstance(ks, KillSwitch)


def test_state_store_switch_starts_engaged_until_refreshed() -> None:
    switch = StateStoreKillSwitch(store=InMemoryStateStore())
    assert switch.is_engaged() is True


def test_state_store_switch_refreshes_missing_and_persisted_state() -> None:
    async def _run() -> tuple[bool, bool]:
        store = InMemoryStateStore()
        switch = StateStoreKillSwitch(store=store)
        await switch.refresh()
        missing_state = switch.is_engaged()
        await store.write_state(KILL_SWITCH_STATE_KEY, {"engaged": True})
        await switch.refresh()
        return missing_state, switch.is_engaged()

    assert asyncio.run(_run()) == (False, True)


def test_state_store_switch_rejects_malformed_state() -> None:
    async def _run() -> None:
        store = InMemoryStateStore()
        await store.write_state(KILL_SWITCH_STATE_KEY, {"engaged": "yes"})
        switch = StateStoreKillSwitch(store=store)
        with pytest.raises(ValueError, match="MUST be a boolean"):
            await switch.refresh()

    asyncio.run(_run())

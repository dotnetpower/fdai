"""Tests for the operator-triggered global KillSwitch seam."""

from __future__ import annotations

from fdai.shared.resilience.kill_switch import InMemoryKillSwitch, KillSwitch


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

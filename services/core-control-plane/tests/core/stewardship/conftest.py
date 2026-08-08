"""Shared fixtures for stewardship tests."""

from __future__ import annotations

import copy
from collections.abc import Callable

import pytest
from fdai.core.stewardship.names import AGENT_NAMES


def _oid(n: int) -> str:
    """A placeholder-shaped, distinct object id (passes non-fork validation)."""
    return f"00000000-0000-0000-0000-{n:012d}"


def _build_valid_raw() -> dict:
    agents: dict = {}
    for i, name in enumerate(AGENT_NAMES):
        if name == "Loki":
            agents[name] = {
                "accept_autonomous": {"reason": "Chaos proposals are always HIL."},
                "stewards": [],
            }
        else:
            agents[name] = {
                "stewards": [{"kind": "user", "id": _oid(100 + i), "responsibility": "accountable"}]
            }
    return {
        "stewardship": {
            "version": 1,
            "maintainers": [{"oid": _oid(1)}, {"oid": _oid(2)}],
            "channels": {},
            "escalation": {"hop_timeout_seconds": 900},
            "thresholds": {"over_assigned_max": 5},
            "agents": agents,
        }
    }


@pytest.fixture
def oid() -> Callable[[int], str]:
    return _oid


@pytest.fixture
def valid_raw() -> dict:
    """A fully valid stewardship config mapping (deep-copied per test)."""
    return copy.deepcopy(_build_valid_raw())

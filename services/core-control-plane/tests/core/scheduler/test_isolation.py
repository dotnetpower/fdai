"""Scheduled-run session, context, and tool isolation tests."""

from __future__ import annotations

import pytest
from fdai.core.scheduler import (
    ScheduledRunIsolationError,
    ScheduledRunIsolationGuard,
    ScheduledRunIsolationProfile,
    isolation_payload,
)


def test_default_profile_denies_ambient_tools() -> None:
    profile = ScheduledRunIsolationProfile()
    guard = ScheduledRunIsolationGuard(profile)

    guard.authorize(context_chars=100, elapsed_seconds=1)
    with pytest.raises(ScheduledRunIsolationError, match="outside"):
        guard.authorize(
            context_chars=100,
            elapsed_seconds=1,
            tool_id="query_inventory",
        )
    assert isolation_payload(profile)["allowed_tool_ids"] == []


def test_profile_enforces_context_duration_and_tool_call_caps() -> None:
    profile = ScheduledRunIsolationProfile(
        profile_id="scheduled.inventory",
        max_session_seconds=30,
        max_context_chars=1000,
        max_tool_calls=2,
        allowed_tool_ids=frozenset({"query_inventory"}),
        command_sandbox_profile_id="local.read",
    )
    guard = ScheduledRunIsolationGuard(profile)
    guard.authorize(
        context_chars=1000,
        elapsed_seconds=30,
        tool_id="query_inventory",
        prior_tool_calls=1,
    )
    with pytest.raises(ScheduledRunIsolationError, match="context"):
        guard.authorize(context_chars=1001, elapsed_seconds=1)
    with pytest.raises(ScheduledRunIsolationError, match="session"):
        guard.authorize(context_chars=1, elapsed_seconds=31)
    with pytest.raises(ScheduledRunIsolationError, match="cap"):
        guard.authorize(
            context_chars=1,
            elapsed_seconds=1,
            tool_id="query_inventory",
            prior_tool_calls=2,
        )

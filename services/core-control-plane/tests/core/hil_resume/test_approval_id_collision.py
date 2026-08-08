from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fdai.core.hil_resume import RequestOutcome

from tests.core.hil_resume.test_coordinator import (
    _SUBMITTER,
    _action,
    _coordinator,
    _rule,
)


async def _request(coordinator, **overrides: Any):  # type: ignore[no-untyped-def]
    values: dict[str, Any] = {
        "action": _action(),
        "rule": _rule(),
        "submitter_oid": _SUBMITTER,
        "correlation_id": "corr-1",
        "approval_id": "approval-1",
        "reasons": ("review",),
        "blast_radius_summary": "1 resource",
        "ttl_seconds": 300,
    }
    values.update(overrides)
    return await coordinator.request_approval(**values)


async def test_exact_request_replay_does_not_resend_or_overwrite() -> None:
    coordinator, _, store, channel = _coordinator()
    first = await _request(coordinator)
    original = await store.read_state("hil_park:approval-1")

    replay = await _request(coordinator)

    assert first.outcome is RequestOutcome.PARKED
    assert replay.outcome is RequestOutcome.ALREADY_PARKED
    assert len(channel.sent) == 1
    assert await store.read_state("hil_park:approval-1") == original


@pytest.mark.parametrize(
    "overrides",
    [
        {"action": _action(idempotency_key="other-action")},
        {"submitter_oid": "other-submitter"},
        {"correlation_id": "other-correlation"},
        {"reasons": ("different",)},
        {"blast_radius_summary": "2 resources"},
        {"ttl_seconds": 600},
        {"assignee_oid": "other-assignee"},
    ],
)
async def test_same_approval_id_with_different_request_conflicts(
    overrides: dict[str, Any],
) -> None:
    coordinator, _, store, channel = _coordinator()
    await _request(coordinator)
    original = await store.read_state("hil_park:approval-1")

    conflict = await _request(coordinator, **overrides)

    assert conflict.outcome is RequestOutcome.APPROVAL_ID_CONFLICT
    assert len(channel.sent) == 1
    assert await store.read_state("hil_park:approval-1") == original


async def test_concurrent_different_requests_claim_approval_once() -> None:
    coordinator, _, store, channel = _coordinator()

    first, second = await asyncio.gather(
        _request(coordinator),
        _request(coordinator, action=_action(idempotency_key="other-action")),
    )

    assert {first.outcome, second.outcome} == {
        RequestOutcome.PARKED,
        RequestOutcome.APPROVAL_ID_CONFLICT,
    }
    assert len(channel.sent) == 1
    assert await store.read_state("hil_park:approval-1") is not None


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("approval_id", "   ", "approval_id MUST be non-empty"),
        ("ttl_seconds", 0, "ttl_seconds MUST be > 0"),
        ("ttl_seconds", -1, "ttl_seconds MUST be > 0"),
    ],
)
async def test_invalid_request_bounds_are_rejected(
    field: str,
    value: object,
    message: str,
) -> None:
    coordinator, _, store, channel = _coordinator()

    with pytest.raises(ValueError, match=message):
        await _request(coordinator, **{field: value})

    assert channel.sent == []
    assert tuple(store.audit_entries) == ()

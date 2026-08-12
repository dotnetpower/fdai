"""Tests for the scheduled synthetic canary publisher payload."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.control_loop._canary import CANARY_EVENT_TYPE, CANARY_SOURCE
from fdai.delivery.canary_cli import build_canary_event


def test_same_slot_builds_same_event_and_idempotency_key() -> None:
    first = build_canary_event(
        slot="20260718T0100Z",
        now=datetime(2026, 7, 18, 1, 0, tzinfo=UTC),
    )
    retry = build_canary_event(
        slot="20260718T0100Z",
        now=datetime(2026, 7, 18, 1, 0, 30, tzinfo=UTC),
    )

    assert retry.event_id == first.event_id
    assert retry.idempotency_key == first.idempotency_key
    assert retry.source == CANARY_SOURCE
    assert retry.event_type == CANARY_EVENT_TYPE
    assert retry.mode.value == "shadow"


def test_canary_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        build_canary_event(
            slot="20260718T0100Z",
            now=datetime(2026, 7, 18, 1, 0),
        )

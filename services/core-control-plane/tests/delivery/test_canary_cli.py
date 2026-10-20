"""Tests for the scheduled synthetic canary publisher payload."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fdai.core.control_loop._canary import CANARY_EVENT_TYPE, CANARY_SOURCE
from fdai.delivery import canary_cli
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


async def test_default_cli_identity_cannot_witness_retry_stable_scheduled_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A same-schedule retry across a minute boundary is not the same published event."""
    published: list[dict[str, Any]] = []

    class Bus:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def publish(self, topic: str, key: str, payload: dict[str, Any]) -> None:
            published.append(payload)

        async def close(self) -> None:
            return None

    monkeypatch.delenv("FDAI_CANARY_SLOT", raising=False)
    monkeypatch.setenv("FDAI_CANARY_TOPIC", "example-canary")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "example.com:9093")
    monkeypatch.setattr(canary_cli, "EventHubsKafkaBus", Bus)
    monkeypatch.setattr(
        canary_cli,
        "ManagedIdentityWorkloadIdentity",
        SimpleNamespace(from_env=lambda **kwargs: object()),
    )
    for minute in (0, 1):
        at = datetime(2026, 10, 20, 1, minute, tzinfo=UTC)
        monkeypatch.setattr(canary_cli, "datetime", SimpleNamespace(now=lambda *, tz, at=at: at))
        assert await canary_cli._run() == 0
    assert published[0]["event_id"] != published[1]["event_id"]
    assert published[0]["idempotency_key"] != published[1]["idempotency_key"]
    assert published[0]["payload"] == {"slot": "20261020T0100Z"}
    assert published[1]["payload"] == {"slot": "20261020T0101Z"}

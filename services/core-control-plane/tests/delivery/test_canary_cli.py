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


async def test_job_uid_preserves_cli_identity_across_minute_and_schedule_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delayed retry belongs to its controller Job, not the current clock slot."""
    published: list[dict[str, Any]] = []

    class Bus:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def publish(self, topic: str, key: str, payload: dict[str, Any]) -> None:
            published.append(payload)

        async def close(self) -> None:
            return None

    monkeypatch.delenv("FDAI_CANARY_SLOT", raising=False)
    monkeypatch.setenv("FDAI_CANARY_JOB_UID", "00000000-0000-0000-0000-000000000001")
    monkeypatch.setenv("FDAI_CANARY_TOPIC", "example-canary")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "example.com:9093")
    monkeypatch.setattr(canary_cli, "EventHubsKafkaBus", Bus)
    monkeypatch.setattr(
        canary_cli,
        "ManagedIdentityWorkloadIdentity",
        SimpleNamespace(from_env=lambda **kwargs: object()),
    )
    for minute in (4, 5, 6):
        at = datetime(2026, 10, 20, 1, minute, tzinfo=UTC)
        monkeypatch.setattr(canary_cli, "datetime", SimpleNamespace(now=lambda *, tz, at=at: at))
        assert await canary_cli._run() == 0
    assert len({item["event_id"] for item in published}) == 1
    assert len({item["idempotency_key"] for item in published}) == 1
    assert published[0]["payload"] == {"slot": "aks-job:00000000-0000-0000-0000-000000000001"}


@pytest.mark.parametrize(
    "uid",
    [
        None,
        "",
        "not-a-uuid",
        "00000000-0000-0000-0000-000000000000",
        "{00000000-0000-0000-0000-000000000001}",
    ],
)
async def test_cli_rejects_missing_or_malformed_execution_identity_before_provider_access(
    monkeypatch: pytest.MonkeyPatch, uid: str | None
) -> None:
    monkeypatch.delenv("FDAI_CANARY_SLOT", raising=False)
    monkeypatch.delenv("FDAI_CANARY_JOB_UID", raising=False)
    if uid is not None:
        monkeypatch.setenv("FDAI_CANARY_JOB_UID", uid)
    monkeypatch.setenv("FDAI_CANARY_TOPIC", "example-canary")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "example.com:9093")

    def forbidden(**kwargs: Any) -> None:
        pytest.fail("provider identity accessed without a stable canary identity")

    monkeypatch.setattr(
        canary_cli, "ManagedIdentityWorkloadIdentity", SimpleNamespace(from_env=forbidden)
    )
    with pytest.raises(RuntimeError, match="identity|UID"):
        await canary_cli._run()


def test_explicit_slot_precedes_platform_identity_without_rewriting_it() -> None:
    assert (
        canary_cli._execution_slot(
            {"FDAI_CANARY_SLOT": "explicit-slot:example", "FDAI_CANARY_JOB_UID": "malformed"}
        )
        == "explicit-slot:example"
    )


def test_distinct_controller_jobs_have_distinct_slots() -> None:
    first = canary_cli._execution_slot(
        {"FDAI_CANARY_JOB_UID": "00000000-0000-0000-0000-000000000001"}
    )
    second = canary_cli._execution_slot(
        {"FDAI_CANARY_JOB_UID": "00000000-0000-0000-0000-000000000002"}
    )
    assert first != second
    assert build_canary_event(slot=first, now=datetime(2026, 10, 20, tzinfo=UTC)).event_id != (
        build_canary_event(slot=second, now=datetime(2026, 10, 20, tzinfo=UTC)).event_id
    )

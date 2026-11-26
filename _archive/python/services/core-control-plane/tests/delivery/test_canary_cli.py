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


@pytest.mark.parametrize(
    ("identity", "slot"),
    [
        (
            {"FDAI_CANARY_JOB_UID": "00000000-0000-0000-0000-000000000001"},
            "aks-job:00000000-0000-0000-0000-000000000001",
        ),
        (
            {"CONTAINER_APP_JOB_EXECUTION_NAME": "example-canary-abcdef1"},
            "aca-execution:example-canary-abcdef1",
        ),
    ],
)
async def test_platform_execution_preserves_cli_identity_across_clock_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    identity: dict[str, str],
    slot: str,
) -> None:
    """Delayed starts and retries retain execution identity, not a current-clock slot."""
    published: list[dict[str, Any]] = []

    class Bus:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def publish(self, topic: str, key: str, payload: dict[str, Any]) -> None:
            published.append(payload)

        async def close(self) -> None:
            return None

    monkeypatch.delenv("FDAI_CANARY_SLOT", raising=False)
    monkeypatch.delenv("FDAI_CANARY_JOB_UID", raising=False)
    monkeypatch.delenv("CONTAINER_APP_JOB_EXECUTION_NAME", raising=False)
    for key, value in identity.items():
        monkeypatch.setenv(key, value)
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
    assert published[0]["payload"] == {"slot": slot}


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
    monkeypatch.delenv("CONTAINER_APP_JOB_EXECUTION_NAME", raising=False)
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
            {
                "FDAI_CANARY_SLOT": "explicit-slot:example",
                "FDAI_CANARY_JOB_UID": "malformed",
                "CONTAINER_APP_JOB_EXECUTION_NAME": "malformed/name",
            }
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


def test_distinct_aca_executions_of_same_job_are_distinct_and_namespaced() -> None:
    first = canary_cli._execution_slot(
        {
            "CONTAINER_APP_JOB_NAME": "example-canary",
            "CONTAINER_APP_JOB_EXECUTION_NAME": "example-canary-abcdef1",
        }
    )
    second = canary_cli._execution_slot(
        {
            "CONTAINER_APP_JOB_NAME": "example-canary",
            "CONTAINER_APP_JOB_EXECUTION_NAME": "example-canary-abcdef2",
        }
    )
    now = datetime(2026, 10, 20, tzinfo=UTC)
    assert first != second
    assert build_canary_event(slot=first, now=now).event_id != (
        build_canary_event(slot=second, now=now).event_id
    )
    uid = "00000000-0000-0000-0000-000000000001"
    assert canary_cli._execution_slot({"FDAI_CANARY_JOB_UID": uid}) != (
        canary_cli._execution_slot({"CONTAINER_APP_JOB_EXECUTION_NAME": uid})
    )


@pytest.mark.parametrize(
    "name",
    [
        "",
        " ",
        " leading",
        "trailing ",
        "UPPER",
        "bad/name",
        "bad\n",
        "-leading",
        "trailing-",
        "a" * 87,
    ],
)
def test_malformed_aca_execution_identity_is_rejected(name: str) -> None:
    with pytest.raises(RuntimeError, match="execution"):
        canary_cli._execution_slot({"CONTAINER_APP_JOB_EXECUTION_NAME": name})


@pytest.mark.parametrize("uid", ["00000000-0000-0000-0000-000000000001", "", "malformed"])
@pytest.mark.parametrize("execution", ["example-canary-abcdef1", ""])
def test_two_platform_identity_bindings_fail_closed(uid: str, execution: str) -> None:
    with pytest.raises(RuntimeError, match="ambiguous"):
        canary_cli._execution_slot(
            {"FDAI_CANARY_JOB_UID": uid, "CONTAINER_APP_JOB_EXECUTION_NAME": execution}
        )


def test_aca_definition_or_replica_name_is_not_an_execution_identity() -> None:
    with pytest.raises(RuntimeError, match="identity"):
        canary_cli._execution_slot(
            {
                "CONTAINER_APP_JOB_NAME": "example-canary",
                "CONTAINER_APP_REPLICA_NAME": "example-replica",
            }
        )


@pytest.mark.parametrize("size", [1, 86])
def test_aca_execution_slot_keeps_exact_100_character_slot_boundary(size: int) -> None:
    execution = "a" * size
    slot = canary_cli._execution_slot({"CONTAINER_APP_JOB_EXECUTION_NAME": execution})
    assert slot == f"aca-execution:{execution}"
    assert len(slot) <= 100
    assert build_canary_event(slot=slot, now=datetime(2026, 10, 20, tzinfo=UTC)).payload == {
        "slot": slot
    }


@pytest.mark.parametrize(
    "identity",
    [
        {
            "FDAI_CANARY_JOB_UID": "00000000-0000-0000-0000-000000000001",
            "CONTAINER_APP_JOB_EXECUTION_NAME": "example-canary-abcdef1",
        },
        {"CONTAINER_APP_JOB_EXECUTION_NAME": "malformed/name"},
        {"CONTAINER_APP_JOB_NAME": "example-canary"},
    ],
)
async def test_invalid_platform_binding_never_accesses_provider(
    monkeypatch: pytest.MonkeyPatch, identity: dict[str, str]
) -> None:
    for key in ("FDAI_CANARY_SLOT", "FDAI_CANARY_JOB_UID", "CONTAINER_APP_JOB_EXECUTION_NAME"):
        monkeypatch.delenv(key, raising=False)
    for key, value in identity.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("FDAI_CANARY_TOPIC", "example-canary")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "example.com:9093")

    def forbidden(**kwargs: Any) -> None:
        pytest.fail("provider identity accessed for an invalid platform binding")

    monkeypatch.setattr(
        canary_cli, "ManagedIdentityWorkloadIdentity", SimpleNamespace(from_env=forbidden)
    )
    with pytest.raises(RuntimeError):
        await canary_cli._run()

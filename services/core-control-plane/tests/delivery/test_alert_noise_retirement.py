"""Unreleased alert-noise 1.0.0 and invalid outbox rows retire explicitly, never crash the drain."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.delivery.alert_noise_handler import AlertNoiseAgentHandler, drain_alert_noise_results
from fdai.delivery.alert_noise_retirement import ALERT_RESULT_PREFIX
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.alert_noise import NoisePolicy, digest_record
from fdai_service_contracts.alert_noise_wire import (
    AlertNoiseCommand,
    AlertNoiseResult,
    SignedAlertCommand,
    sign_alert_record,
)

_NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
_KEY = b"test-only-alert-retirement-key-000000"
_TOPIC = "alert-noise.result"


class _Bus:
    def __init__(self) -> None:
        self.published: list[str] = []

    async def publish(self, topic: str, key: str, payload: dict[str, Any]) -> None:
        assert topic == _TOPIC and payload
        self.published.append(key)


def _command(request_ref: str, *, requested_at: datetime = _NOW) -> AlertNoiseCommand:
    return AlertNoiseCommand(
        operation="alert_noise.assess",
        request_ref=request_ref,
        requester_ref="principal:example",
        scope_ref="scope:example",
        requested_at=requested_at,
        expires_at=requested_at + timedelta(minutes=5),
    )


def _held(command: AlertNoiseCommand) -> dict[str, Any]:
    return AlertNoiseResult(
        command=command,
        command_digest=digest_record(command),
        recorded_at=command.requested_at + timedelta(seconds=1),
        status="held",
        reason="source_unavailable",
    ).model_dump(mode="json")


def _legacy(command: AlertNoiseCommand) -> dict[str, Any]:
    return {**_held(command), "schema_version": "1.0.0"}


def _handler(store: InMemoryStateStore) -> AlertNoiseAgentHandler:
    return AlertNoiseAgentHandler(
        store=store,
        sources={},
        principals={"principal:example": frozenset({"scope:example"})},
        policy=NoisePolicy(),
        transport_key=_KEY,
        clock=lambda: _NOW,
    )


async def _pending(store: InMemoryStateStore, key: str, result: object, revision: object = 1):
    row = {"result": result, "publication_state": "pending", "revision": revision}
    await store.write_state(key, row)
    return row


def _audits(store: InMemoryStateStore, kind: str) -> list[dict[str, Any]]:
    entries = (row["entry"] for row in store.audit_entries)
    return [dict(row) for row in entries if row.get("action_kind") == kind]


async def test_legacy_and_invalid_rows_retire_while_current_results_publish() -> None:
    store, bus = InMemoryStateStore(), _Bus()
    legacy_key = ALERT_RESULT_PREFIX + "request:legacy"
    invalid_key = ALERT_RESULT_PREFIX + "request:invalid"
    await _pending(store, legacy_key, _legacy(_command("request:legacy")))
    await _pending(
        store, ALERT_RESULT_PREFIX + "request:current", _held(_command("request:current"))
    )
    corrupt = {**_held(_command("request:invalid")), "command_digest": "sha256:" + "0" * 64}
    await _pending(store, invalid_key, corrupt)

    published = await drain_alert_noise_results(handler=_handler(store), bus=bus, topic=_TOPIC)

    assert published == 1
    assert bus.published == ["request:current"]
    legacy_row = await store.read_state(legacy_key)
    invalid_row = await store.read_state(invalid_key)
    assert legacy_row is not None and invalid_row is not None
    assert (legacy_row["publication_state"], legacy_row["revision"]) == ("retired", 2)
    assert legacy_row["result"] == _legacy(_command("request:legacy"))
    assert (invalid_row["publication_state"], invalid_row["revision"]) == ("retired", 2)
    retired = {row["correlation_id"]: row for row in _audits(store, "alert_noise.result.retired")}
    assert retired["request:legacy"]["reason"] == "legacy_contract_retired"
    assert retired["request:legacy"]["retired_schema_version"] == "1.0.0"
    assert retired["request:invalid"]["reason"] == "invalid_result_record"
    assert retired["request:invalid"]["retired_schema_version"] is None
    assert all(row["execution_authority"] is False for row in retired.values())

    assert await drain_alert_noise_results(handler=_handler(store), bus=bus, topic=_TOPIC) == 0
    assert bus.published == ["request:current"]


@pytest.mark.parametrize(
    ("key", "result", "revision"),
    [
        (ALERT_RESULT_PREFIX + "request:broken", {"status": "held"}, 1),
        (ALERT_RESULT_PREFIX + "request:revision", "LEGACY", "1"),
        (ALERT_RESULT_PREFIX + "request:elsewhere", "LEGACY", 1),
    ],
)
async def test_unaddressable_rows_get_one_audited_denial_and_stay_retained(
    key: str, result: object, revision: object
) -> None:
    store, bus = InMemoryStateStore(), _Bus()
    if result == "LEGACY":
        claimed = "request:legacy" if key.endswith("elsewhere") else "request:revision"
        result = _legacy(_command(claimed))
    row = await _pending(store, key, result, revision)

    for _ in range(2):
        assert await drain_alert_noise_results(handler=_handler(store), bus=bus, topic=_TOPIC) == 0

    assert bus.published == []
    assert await store.read_state(key) == row
    assert _audits(store, "alert_noise.result.retired") == []
    denials = _audits(store, "alert_noise.result.retirement_denied")
    assert len(denials) == 1 and denials[0]["execution_authority"] is False


async def test_replay_of_a_legacy_result_is_terminal_and_never_replanned() -> None:
    store = InMemoryStateStore()
    handler = _handler(store)
    command = _command("request:replay")
    signal = await handler.observe(
        {
            "producer_principal": "Huginn",
            "alert_noise": SignedAlertCommand(
                command=command, signature=sign_alert_record(command, _KEY)
            ).model_dump(mode="json"),
        }
    )
    row = {"result": _legacy(command), "publication_state": "published", "revision": 2}
    await store.write_state(ALERT_RESULT_PREFIX + command.request_ref, row)
    before = await store.read_state_page("alert-noise:", limit=100)

    replayed = await handler.plan({**signal, "producer_principal": "Heimdall"})

    assert replayed == _legacy(command)
    assert await store.read_state_page("alert-noise:", limit=100) == before

    conflicting = _legacy(_command("request:replay", requested_at=_NOW - timedelta(seconds=1)))
    await store.write_state(
        ALERT_RESULT_PREFIX + command.request_ref, {**row, "result": conflicting}
    )
    with pytest.raises(ValueError, match="identity conflict"):
        await handler.plan({**signal, "producer_principal": "Heimdall"})

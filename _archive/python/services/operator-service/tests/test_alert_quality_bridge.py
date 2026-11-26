"""Round 7: a signed terminal identity precedes projection and survives interrupted replay."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fdai_operator_service.alert_quality_runtime import (
    AlertQualityBridge,
    AlertQualityTransport,
    command_from_record,
)
from fdai_operator_service.alert_quality_store import alert_quality_requester_ref
from fdai_operator_service.postgres_family_store import PostgresFamilyStore
from fdai_service_contracts.alert_noise import NoiseAssessment, digest_record
from fdai_service_contracts.alert_noise_wire import (
    AlertNoiseResult,
    SignedAlertResult,
    sign_alert_record,
)

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)
SCOPE = "scope:example"
SUBJECT = "operator-example"
KEY = b"test-only-alert-transport-key-0000"
REQUEST = "request:example"
RESULT_KEY = "operator-alert-quality-result:" + REQUEST


class State:
    """Test-only insert-if-absent storage with deterministic projection interruptions."""

    def __init__(self) -> None:
        self.records: dict[str, dict] = {}
        self.before_report: Callable[[], Awaitable[None]] | None = None

    async def read_state(self, key: str) -> dict | None:
        return copy.deepcopy(self.records.get(key))

    async def create_state(self, key: str, value: Mapping) -> bool:
        if ":report:" in key and self.before_report is not None:
            callback, self.before_report = self.before_report, None
            await callback()
        if key in self.records:
            return False
        self.records[key] = copy.deepcopy(dict(value))
        return True

    async def find_state(self, *, prefix: str, field: str, value: str) -> dict | None:
        rows = [
            row
            for key, row in self.records.items()
            if key.startswith(prefix) and row.get(field) == value
        ]
        return copy.deepcopy(rows[-1]) if rows else None


def bridge_fixture() -> tuple[State, AlertQualityBridge, dict, dict]:
    state = State()
    outer = {
        "principal_id": SUBJECT,
        "idempotency_key": REQUEST,
        "operation": "alert_noise.assess",
        "payload": {
            "scope_ref": SCOPE,
            "requester_ref": alert_quality_requester_ref(SUBJECT, SCOPE),
        },
    }
    record = {**outer, "payload": outer, "accepted_at": NOW.isoformat()}
    record_key = "operator-proposal:operations:" + hashlib.sha256(REQUEST.encode()).hexdigest()
    state.records[record_key] = record
    command = command_from_record(record)
    assessment = NoiseAssessment(
        evidence_digest="sha256:" + "a" * 64,
        policy_digest="sha256:" + "b" * 64,
        tenant_ref="tenant:example",
        scope_ref=SCOPE,
        observed_at=NOW,
        valid_until=NOW + timedelta(hours=1),
        coverage="partial",
        reasons=("source_missing",),
        source_episodes=None,
        notification_attempts=None,
        confirmed_deliveries=None,
        acknowledgements=None,
        findings=(),
    )
    result = AlertNoiseResult(
        command=command,
        command_digest=digest_record(command),
        recorded_at=NOW,
        status="assessment_ready",
        assessment=assessment,
    )
    held = result.model_copy(update={"status": "held", "assessment": None, "reason": "held"})

    def signed(value: AlertNoiseResult) -> dict:
        return SignedAlertResult(result=value, signature=sign_alert_record(value, KEY)).model_dump(
            mode="json"
        )

    bridge = AlertQualityBridge(
        store=cast(PostgresFamilyStore, state),
        transport=cast(AlertQualityTransport, None),
        event_topic="test.events",
        transport_key=KEY,
        scopes=frozenset({SCOPE}),
        clock=lambda: NOW,
    )
    return state, bridge, signed(result), signed(held)


async def test_conflicting_result_cannot_win_during_projection() -> None:
    state, bridge, ready, held = bridge_fixture()
    rejected: list[str] = []

    async def competing_result() -> None:
        try:
            await bridge.accept_result(held)
        except ValueError:
            rejected.append("conflict")

    state.before_report = competing_result
    await bridge.accept_result(ready)
    assert rejected == ["conflict"]
    assert state.records[RESULT_KEY] == ready
    assert await bridge.projections.read(principal_id=SUBJECT, scope_ref=SCOPE) is not None


async def test_interruption_retains_identity_and_exact_replay_finishes_projection() -> None:
    state, bridge, ready, held = bridge_fixture()

    async def interrupted() -> None:
        raise RuntimeError("test-only interrupted projection")

    state.before_report = interrupted
    with pytest.raises(RuntimeError, match="interrupted"):
        await bridge.accept_result(ready)
    assert state.records.get(RESULT_KEY) == ready
    with pytest.raises(ValueError, match="conflict"):
        await bridge.accept_result(held)
    await bridge.accept_result(ready)
    saved = copy.deepcopy(state.records)
    await bridge.accept_result(ready)
    assert state.records == saved
    assert await bridge.projections.read(principal_id=SUBJECT, scope_ref=SCOPE) is not None


async def test_terminal_hold_blocks_later_projection() -> None:
    state, bridge, ready, held = bridge_fixture()
    await bridge.accept_result(held)
    with pytest.raises(ValueError, match="conflict"):
        await bridge.accept_result(ready)
    assert state.records[RESULT_KEY] == held
    assert await bridge.projections.read(principal_id=SUBJECT, scope_ref=SCOPE) is None

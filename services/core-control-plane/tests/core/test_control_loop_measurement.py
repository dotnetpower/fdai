"""Terminal measurement coverage, source fidelity, and failed-write replay."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from fdai.core.control_loop import _process
from fdai.core.control_loop._measurement import (
    TerminalMeasurementRecorder,
    build_control_loop_measurement,
    control_loop_measurement_audit_entry,
)
from fdai.core.control_loop.models import ControlLoopOutcome, ControlLoopResult
from fdai.core.event_ingest import EventIngest
from fdai.core.executor import ExecutionResult, ExecutorOutcome
from fdai.core.executor.direct_api import DirectApiExecutionOutcome, DirectApiExecutionResult
from fdai.core.executor.tool_call import ToolCallExecutionOutcome, ToolCallExecutionResult
from fdai.core.tiers.t0_deterministic.engine import NO_RULE_DENIED
from fdai.core.trust_router import RoutingDecision, RoutingTier
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.control_loop_measurement import (
    CONTROL_LOOP_MEASUREMENT_ACTION_KIND,
    ControlLoopMeasurement,
    control_loop_measurement_id,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 12, 7, tzinfo=UTC)


def _event(key: str = "source-key", event_type: str = "resource.changed") -> Event:
    return Event(
        schema_version="1.0.0",
        event_id=UUID("00000000-0000-0000-0000-000000000123"),
        idempotency_key=key,
        source="synthetic-observer",
        correlation_id="correlation-1",
        event_type=event_type,
        mode=Mode.SHADOW,
        detected_at=NOW - timedelta(minutes=2),
        ingested_at=NOW - timedelta(minutes=1),
        payload={"resource": {"type": "compute.vm", "id": "resource-1"}},
    )


def _result(
    outcome: ControlLoopOutcome = ControlLoopOutcome.COMPLIANT,
    tier: str = "t0",
    decision: str = "compliant",
) -> ControlLoopResult:
    return ControlLoopResult(
        outcome=outcome,
        tier=tier,
        decision=decision,
        resource_type="compute.vm",
        event_id="intentionally-not-the-normalized-event-id",
    )


def _host(store: InMemoryStateStore) -> SimpleNamespace:
    validator = JsonSchemaEventValidator(
        JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    )
    return SimpleNamespace(
        _audit_store=store,
        _event_ingest=EventIngest(validator=validator),
        _clock=lambda: NOW,
    )


def _measurements(store: InMemoryStateStore) -> list[Mapping[str, Any]]:
    return [
        row["entry"]
        for row in store.audit_entries
        if row["entry"].get("action_kind") == CONTROL_LOOP_MEASUREMENT_ACTION_KIND
    ]


async def test_retained_terminal_rejects_identity_collision_without_another_audit() -> None:
    store = InMemoryStateStore()
    await TerminalMeasurementRecorder(store).record(_event(), _result(), recorded_at=NOW)
    changed = _event().model_copy(update={"source": "another-observer"})
    with pytest.raises(ValueError, match="conflicts with retained"):
        await TerminalMeasurementRecorder(store).record(changed, _result(), recorded_at=NOW)
    assert len(_measurements(store)) == 1


async def test_replay_capture_times_do_not_replace_original_terminal() -> None:
    store = InMemoryStateStore()
    await TerminalMeasurementRecorder(store).record(_event(), _result(), recorded_at=NOW)
    replay = _event().model_copy(update={"ingested_at": NOW})
    await TerminalMeasurementRecorder(store).record(
        replay, _result(), recorded_at=NOW + timedelta(seconds=1)
    )
    assert len(_measurements(store)) == 1
    assert _measurements(store)[0]["recorded_at"] == NOW.isoformat().replace("+00:00", "Z")


async def test_duplicate_acknowledgement_without_retained_evidence_is_not_success() -> None:
    store = InMemoryStateStore()
    store.write_state_with_audit_if_absent = AsyncMock(return_value=False)
    with pytest.raises(ValueError, match="disappeared"):
        await TerminalMeasurementRecorder(store).record(_event(), _result(), recorded_at=NOW)


@pytest.mark.parametrize(
    "outcome", [value for value in ControlLoopOutcome if value is not ControlLoopOutcome.DEDUPED]
)
async def test_every_terminal_return_is_recorded_once_without_changing_result(
    monkeypatch: pytest.MonkeyPatch, outcome: ControlLoopOutcome
) -> None:
    store = InMemoryStateStore()
    host = _host(store)
    event = _event()
    expected = _result(outcome)
    runner = AsyncMock(return_value=expected)
    monkeypatch.setattr(_process, "_process_normalized_event", runner)

    assert await _process.process_event(host, event) is expected
    duplicate = await _process.process_event(host, event)
    assert duplicate.outcome is ControlLoopOutcome.DEDUPED
    runner.assert_awaited_once()
    rows = _measurements(store)
    assert len(rows) == 1
    assert rows[0]["terminal_outcome"] == outcome.value
    assert rows[0]["event_id"] == str(event.event_id)
    assert rows[0]["idempotency_key"] == event.idempotency_key
    assert rows[0]["gate_route"] == expected.decision
    assert rows[0]["actor"] == "fdai.measurement"
    assert ControlLoopMeasurement.from_audit_entry(rows[0]).measurement_id == (
        control_loop_measurement_id(event.idempotency_key)
    )
    assert rows[0]["occurred_at"] == event.detected_at.isoformat().replace("+00:00", "Z")
    assert rows[0]["ingested_at"] == event.ingested_at.isoformat().replace("+00:00", "Z")
    assert rows[0]["recorded_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert await store.verify_chain()


@pytest.mark.parametrize("tier", ["t0", "t1", "t2", "abstain", "operator", "unclassified"])
@pytest.mark.parametrize("mode", [Mode.SHADOW, Mode.ENFORCE])
def test_tier_is_explicit_or_unknown_and_does_not_imply_success(tier: str, mode: Mode) -> None:
    event = _event().model_copy(update={"mode": mode})
    result = _result(ControlLoopOutcome.EXECUTED, tier, "auto")
    measurement = build_control_loop_measurement(event, result, recorded_at=NOW)
    row = control_loop_measurement_audit_entry(measurement)
    assert row["tier"] == (tier if tier in {"t0", "t1", "t2"} else None)
    assert row["mode"] == mode.value
    assert row["terminal_outcome"] == "executed"
    assert row["gate_route"] == "auto"
    assert not {"success", "verification_passed", "scorable", "execution_results"} & row.keys()


@pytest.mark.parametrize("marker", [True, False, None, "false", 0, 1])
def test_only_explicit_boolean_synthetic_source_marker_is_retained(marker: object) -> None:
    event = _event().model_copy(update={"payload": {"synthetic": marker}})
    measurement = build_control_loop_measurement(event, _result(), recorded_at=NOW)
    assert measurement.synthetic is (marker if isinstance(marker, bool) else None)


@pytest.mark.parametrize("route", ["auto", "hil", "deny", "abstain", "compliant"])
async def test_all_attempted_action_identities_survive_without_upgrading_gate_route(
    monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    results = (
        ExecutionResult(action_id="pr-action", outcome=ExecutorOutcome.PUBLISHED),
        DirectApiExecutionResult(
            action_id="api-action", outcome=DirectApiExecutionOutcome.ABSTAINED_PRECONDITION
        ),
        ToolCallExecutionResult(
            action_id="tool-action", outcome=ToolCallExecutionOutcome.ABSTAINED_PRECONDITION
        ),
        ExecutionResult(
            action_id="unbuilt::source-key::rule-1", outcome=ExecutorOutcome.REJECTED_INVARIANT
        ),
        ExecutionResult(action_id="pr-action", outcome=ExecutorOutcome.ALREADY_EXISTED),
    )
    expected_ids = tuple(item.action_id for item in results)
    result = replace(
        _result(ControlLoopOutcome.EXECUTED, decision=route), execution_results=results
    )
    runner = AsyncMock(return_value=result)
    monkeypatch.setattr(_process, "_process_normalized_event", runner)
    store = InMemoryStateStore()
    await _process.process_event(_host(store), _event())
    measurement = ControlLoopMeasurement.from_audit_entry(_measurements(store)[0])
    assert measurement.action_ids == expected_ids
    assert measurement.gate_route == route
    assert measurement.terminal_outcome == "executed"


async def test_failed_measurement_retry_retains_complete_attempted_action_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _FailingStore()
    host = _host(store)
    result = replace(
        _result(ControlLoopOutcome.EXECUTED, decision="auto"),
        execution_results=(
            ExecutionResult(action_id="first", outcome=ExecutorOutcome.PUBLISHED),
            ExecutionResult(action_id="second", outcome=ExecutorOutcome.REJECTED_INVARIANT),
        ),
    )
    runner = AsyncMock(return_value=result)
    monkeypatch.setattr(_process, "_process_normalized_event", runner)
    with pytest.raises(OSError, match="persistence failure"):
        await _process.process_event(host, _event())
    store.fail = False
    assert (await _process.process_event(host, _event())).outcome is ControlLoopOutcome.DEDUPED
    assert ControlLoopMeasurement.from_audit_entry(_measurements(store)[0]).action_ids == (
        "first",
        "second",
    )
    runner.assert_awaited_once()


async def test_atomic_identity_survives_new_recorder_and_concurrent_replays() -> None:
    store = InMemoryStateStore()
    event = _event("x" * 500 + "-one")
    await asyncio.gather(
        *[
            TerminalMeasurementRecorder(store).record(event, _result(), recorded_at=NOW)
            for _ in range(4)
        ]
    )
    with pytest.raises(ValueError, match="conflicts with retained"):
        await TerminalMeasurementRecorder(store).record(
            event,
            _result(ControlLoopOutcome.HIL, decision="hil"),
            recorded_at=NOW + timedelta(days=1),
        )
    distinct = _event("x" * 500 + "-two")
    await TerminalMeasurementRecorder(store).record(distinct, _result(), recorded_at=NOW)
    rows = _measurements(store)
    assert len(rows) == 2
    assert rows[0]["terminal_outcome"] == "compliant"
    assert rows[0]["recorded_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert rows[0]["measurement_id"] != rows[1]["measurement_id"]
    retained = await store.read_state(
        f"measurement:control-loop:v1:{control_loop_measurement_id(event.idempotency_key)}"
    )
    assert retained is not None
    assert retained["terminal_outcome"] == "compliant"


class _FailingStore(InMemoryStateStore):
    fail = True
    commit_before_failure = False

    async def write_state_with_audit_if_absent(
        self, key: str, value: Mapping[str, Any], audit_entry: Mapping[str, Any]
    ) -> bool:
        if self.fail and not self.commit_before_failure:
            raise OSError("synthetic measurement persistence failure")
        created = await super().write_state_with_audit_if_absent(key, value, audit_entry)
        if self.fail:
            raise OSError("synthetic measurement persistence failure")
        return created


@pytest.mark.parametrize("commit_before_failure", [False, True])
async def test_failed_write_is_retried_before_ingest_dedup_without_reprocessing(
    monkeypatch: pytest.MonkeyPatch, commit_before_failure: bool
) -> None:
    store = _FailingStore()
    store.commit_before_failure = commit_before_failure
    host = _host(store)
    event = _event()
    runner = AsyncMock(return_value=_result())
    monkeypatch.setattr(_process, "_process_normalized_event", runner)
    with pytest.raises(OSError, match="persistence failure"):
        await _process.process_event(host, event)
    assert event.idempotency_key in host._event_ingest.seen_keys()

    with pytest.raises(OSError, match="persistence failure"):
        await _process.process_event(host, _event("must-not-be-ingested"))
    assert "must-not-be-ingested" not in host._event_ingest.seen_keys()

    store.fail = False
    host._clock = lambda: NOW + timedelta(days=1)
    result = await _process.process_event(host, event)
    assert result.outcome is ControlLoopOutcome.DEDUPED
    runner.assert_awaited_once()
    rows = _measurements(store)
    assert len(rows) == 1
    assert rows[0]["recorded_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert rows[0]["terminal_outcome"] == "compliant"


async def test_duplicate_result_and_nonterminal_exception_create_no_measurement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    await TerminalMeasurementRecorder(store).record(
        _event(), _result(ControlLoopOutcome.DEDUPED), recorded_at=NOW
    )
    runner = AsyncMock(side_effect=RuntimeError("synthetic process failure"))
    monkeypatch.setattr(_process, "_process_normalized_event", runner)
    with pytest.raises(RuntimeError, match="process failure"):
        await _process.process_event(_host(store), _event())
    assert _measurements(store) == []


async def test_invalid_terminal_fields_remain_an_explicit_failure_on_redelivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    host = _host(store)
    host._clock = lambda: NOW.replace(tzinfo=None)
    runner = AsyncMock(return_value=_result())
    monkeypatch.setattr(_process, "_process_normalized_event", runner)
    for _ in range(2):
        with pytest.raises(ValidationError, match="timezone"):
            await _process.process_event(host, _event())
    runner.assert_awaited_once()
    assert _measurements(store) == []


async def test_cancelled_persistence_keeps_the_original_terminal_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    host = _host(store)
    persist = store.write_state_with_audit_if_absent
    failing = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(store, "write_state_with_audit_if_absent", failing)
    runner = AsyncMock(return_value=_result())
    monkeypatch.setattr(_process, "_process_normalized_event", runner)
    with pytest.raises(asyncio.CancelledError):
        await _process.process_event(host, _event())
    monkeypatch.setattr(store, "write_state_with_audit_if_absent", persist)
    assert (await _process.process_event(host, _event())).outcome is ControlLoopOutcome.DEDUPED
    assert len(_measurements(store)) == 1
    runner.assert_awaited_once()


@pytest.mark.parametrize(
    ("route", "expected_outcome", "tier"),
    [
        (RoutingTier.ABSTAIN, ControlLoopOutcome.ABSTAINED_ROUTING, None),
        (RoutingTier.T0, ControlLoopOutcome.COMPLIANT, "t0"),
        (RoutingTier.T1, ControlLoopOutcome.ABSTAINED_ROUTING, "t1"),
    ],
)
async def test_actual_early_stage_returns_are_measured(
    route: RoutingTier, expected_outcome: ControlLoopOutcome, tier: str | None
) -> None:
    store = InMemoryStateStore()
    host = _host(store)
    decision = RoutingDecision(tier=route, resource_type="compute.vm", candidate_rule_ids=())
    host._trust_router = Mock(route=Mock(return_value=decision))
    host._t0_engine = Mock(
        evaluate=Mock(
            return_value=SimpleNamespace(
                matched=False,
                audit_hint=SimpleNamespace(reason=NO_RULE_DENIED, citing_rule_ids=()),
            )
        )
    )
    host._correlate_incident_id = Mock(return_value=None)
    host._change_safety_detector = None
    for name in (
        "_emit_stage",
        "_maybe_fire_workflows",
        "_analyze_and_audit_temporal_causality",
        "_write_abstain_audit",
        "_analyze_t2_rca_on_abstain",
        "_evaluate_fallback_tiers",
    ):
        setattr(host, name, AsyncMock(return_value=None))
    result = await _process.process_event(host, _event())
    assert result.outcome is expected_outcome
    rows = _measurements(store)
    assert len(rows) == 1
    assert rows[0]["tier"] == tier
    assert rows[0]["terminal_outcome"] == expected_outcome.value


async def test_raw_operator_proposal_records_normalized_not_guessed_source_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    host = _host(store)
    host._correlate_incident_id = Mock(return_value=None)
    host._emit_stage = AsyncMock()
    host._maybe_fire_workflows = AsyncMock()
    result = _result(ControlLoopOutcome.HIL, "operator", "hil")
    operator = AsyncMock(return_value=result)
    monkeypatch.setattr(_process, "process_operator_request", operator)
    proposal = {
        "event_type": "operator_request",
        "operator_initiated": True,
        "idempotency_key": "operator-source-key",
        "initiator_principal": "synthetic-operator",
        "action_type": "tool.synthetic",
        "params": {},
    }
    assert await _process.process_event(host, proposal) is result
    normalized = operator.await_args.kwargs["event"]
    rows = _measurements(store)
    assert len(rows) == 1
    assert rows[0]["event_id"] == str(normalized.event_id)
    assert rows[0]["source"] == normalized.source == "operator_console"
    assert rows[0]["event_type"] == "operator_request"
    assert rows[0]["mode"] == normalized.mode.value
    assert rows[0]["tier"] is None
    assert rows[0]["terminal_outcome"] == rows[0]["gate_route"] == "hil"

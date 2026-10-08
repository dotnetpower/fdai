from __future__ import annotations

import stat
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fdai_lifecycle_agent.state import (
    MAX_PLAN_RECORDS,
    AgentState,
    AgentStateError,
    LocalStateStore,
    PlanRecord,
    PlanResult,
)


def _record(sequence: int, *, retryable: bool = False, **overrides: Any) -> PlanRecord:
    result = PlanResult(outcome="rejected", reason_code="plan_expired", retryable=retryable)
    return replace(
        PlanRecord(sequence=sequence, payload_digest="a" * 64, result=result), **overrides
    )


def test_missing_state_starts_below_sequence_zero(tmp_path: Path) -> None:
    assert LocalStateStore(tmp_path / "state").load() == AgentState()
    assert AgentState().last_accepted_sequence == -1


def test_state_round_trips_with_owner_only_permissions(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path / "state")
    state = AgentState(
        last_accepted_sequence=8,
        rejected_sequences=frozenset({3, 9}),
        plans={
            "plan-0008": _record(
                8,
                result=PlanResult(
                    outcome="dry-run-admitted",
                    reason_code="dry_run_computed",
                    exact_plan_digest="sha256:" + "b" * 64,
                    summary='{"entity_count":2}',
                ),
                attempts=2,
                reported=True,
            ),
            "plan-0009": _record(
                9, retryable=True, attempts=1, reported_at=datetime(2026, 10, 7, 12, tzinfo=UTC)
            ),
        },
    )

    store.save(state)

    assert store.load() == state
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700
    assert {path.name for path in store.path.parent.iterdir()} == {store.path.name}


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        b"{}",
        b'{"schema": "other", "last_accepted_sequence": 1, "rejected_sequences": [], "plans": {}}',
        b'{"schema": "fdai.lifecycle-agent-state.v1", "last_accepted_sequence": -2,'
        b' "rejected_sequences": [], "plans": {}}',
        b'{"schema": "fdai.lifecycle-agent-state.v1", "last_accepted_sequence": 1,'
        b' "rejected_sequences": [true], "plans": {}}',
        b'{"schema": "fdai.lifecycle-agent-state.v1", "last_accepted_sequence": 1,'
        b' "rejected_sequences": [], "plans": {"p": {"sequence": 1}}}',
    ],
)
def test_invalid_state_fails_closed(tmp_path: Path, content: bytes) -> None:
    store = LocalStateStore(tmp_path)
    store.path.write_bytes(content)

    with pytest.raises(AgentStateError):
        store.load()


def test_plan_records_are_bounded_by_newest_sequence() -> None:
    state = AgentState()
    for sequence in range(MAX_PLAN_RECORDS + 5):
        state = state.with_record(f"plan-{sequence}", _record(sequence))

    assert len(state.plans) == MAX_PLAN_RECORDS
    assert "plan-0" not in state.plans
    assert f"plan-{MAX_PLAN_RECORDS + 4}" in state.plans


def test_retryable_records_are_evicted_before_final_results() -> None:
    state = AgentState()
    for sequence in range(MAX_PLAN_RECORDS):
        state = state.with_record(f"plan-{sequence}", _record(sequence))

    state = state.with_record("forged", _record(10**9, retryable=True))

    assert "forged" not in state.plans
    assert "plan-0" in state.plans


@pytest.mark.parametrize(
    ("result", "floor", "blocked"),
    [
        (PlanResult(outcome="dry-run-admitted", reason_code="ok", exact_plan_digest="x"), 7, set()),
        (PlanResult(outcome="rejected", reason_code="plan_expired"), -1, {7}),
        (
            PlanResult(outcome="rejected", reason_code="release_unavailable", retryable=True),
            -1,
            set(),
        ),
    ],
)
def test_with_result_applies_the_replay_rule(
    result: PlanResult, floor: int, blocked: set[int]
) -> None:
    state = AgentState().with_result("plan-7", _record(7, result=result))

    assert state.last_accepted_sequence == floor
    assert state.rejected_sequences == blocked
    assert state.plans["plan-7"].result == result


def test_lock_refuses_a_concurrent_poll(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path / "state")

    with store.lock():
        with pytest.raises(AgentStateError, match="another poll holds"):
            with LocalStateStore(tmp_path / "state").lock():
                pass
    with store.lock():
        pass


def test_unwritable_state_raises_agent_state_error(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x")

    with pytest.raises(AgentStateError, match="not writable"):
        LocalStateStore(blocker / "state").save(AgentState())


def test_utf16_state_file_is_refused(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path)
    store.path.write_bytes(
        '{"schema": "fdai.lifecycle-agent-state.v1", "last_accepted_sequence": -1,'
        ' "rejected_sequences": [], "plans": {}}'.encode("utf-16")
    )

    with pytest.raises(AgentStateError, match="invalid"):
        store.load()

from __future__ import annotations

import json
import stat
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fdai_lifecycle_agent.state import (
    MAX_PLAN_RECORDS,
    MAX_REPORT_HISTORY,
    AgentState,
    AgentStateError,
    LocalStateStore,
    PlanRecord,
    PlanResult,
    StoredReport,
)


def _record(sequence: int, *, retryable: bool = False, **overrides: Any) -> PlanRecord:
    result = PlanResult(outcome="rejected", reason_code="plan_expired", retryable=retryable)
    record = replace(
        PlanRecord(sequence=sequence, payload_digest="a" * 64, result=result), **overrides
    )
    if record.attempts == 1 and record.reported_at is not None and not record.report_history:
        report = StoredReport(
            attempt=1,
            result=record.result,
            reported_at=record.reported_at,
        )
        record = replace(record, report_history=(report,))
    return record


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
                attempts=1,
                reported_at=datetime(2026, 10, 7, 11, tzinfo=UTC),
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


def test_legacy_apply_started_expiry_is_migrated_and_persisted(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path)
    legacy: dict[str, Any] = {
        "schema": "fdai.lifecycle-agent-state.v1",
        "last_accepted_sequence": 7,
        "rejected_sequences": [],
        "plans": {
            "plan-7": {
                "sequence": 7,
                "payload_digest": "a" * 64,
                "result": {
                    "outcome": "rejected",
                    "reason_code": "plan_expired",
                    "exact_plan_digest": None,
                    "summary": "",
                    "retryable": False,
                },
                "attempts": 1,
                "reported_at": "2026-10-07T12:00:00+00:00",
                "reported": True,
            }
        },
    }
    store.path.write_text(json.dumps(legacy))

    state = store.load()

    assert state.rejected_sequences == {7}
    persisted = json.loads(store.path.read_text())
    assert persisted["schema"] == "fdai.lifecycle-agent-state.v3"
    assert persisted["rejected_sequences"] == [7]
    plans = persisted["plans"]
    assert isinstance(plans, dict)
    assert plans["plan-7"] | {
        "apply_started_report": None,
        "report_history": [
            {
                "attempt": 1,
                "result": legacy["plans"]["plan-7"]["result"],
                "reported_at": legacy["plans"]["plan-7"]["reported_at"],
            }
        ],
        "pending_reports": [],
    } == legacy["plans"]["plan-7"] | {
        "apply_started_report": None,
        "report_history": [
            {
                "attempt": 1,
                "result": legacy["plans"]["plan-7"]["result"],
                "reported_at": legacy["plans"]["plan-7"]["reported_at"],
            }
        ],
        "pending_reports": [],
    }
    assert store.load() == state


def test_legacy_rewound_terminal_report_migrates_to_durable_replay_sequence(
    tmp_path: Path,
) -> None:
    store = LocalStateStore(tmp_path)
    reported_at = "2026-10-07T12:00:00+00:00"
    result = {
        "outcome": "applied",
        "reason_code": "applied",
        "exact_plan_digest": "sha256:" + "b" * 64,
        "summary": '{"update":1}',
        "retryable": False,
    }
    store.path.write_text(
        json.dumps(
            {
                "schema": "fdai.lifecycle-agent-state.v1",
                "last_accepted_sequence": 7,
                "rejected_sequences": [],
                "plans": {
                    "plan-7": {
                        "sequence": 7,
                        "payload_digest": "a" * 64,
                        "result": result,
                        "attempts": 1,
                        "reported_at": reported_at,
                        "reported": False,
                    }
                },
            }
        )
    )

    record = store.load().plans["plan-7"]

    assert record.attempts == 2
    assert record.apply_started_report == StoredReport(
        attempt=1,
        result=PlanResult(
            outcome="apply-started",
            reason_code="apply_started",
            exact_plan_digest="sha256:" + "b" * 64,
            summary='{"update":1}',
        ),
        reported_at=datetime(2026, 10, 7, 11, 59, 59, 999999, tzinfo=UTC),
    )
    assert [report.attempt for report in record.pending_reports] == [1, 2]
    assert record.pending_reports[-1].result == record.result
    assert [report.attempt for report in record.report_history] == [1, 2]
    assert json.loads(store.path.read_text())["schema"] == "fdai.lifecycle-agent-state.v3"


def test_legacy_accepted_single_terminal_report_remains_complete(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path)
    store.path.write_text(
        json.dumps(
            {
                "schema": "fdai.lifecycle-agent-state.v1",
                "last_accepted_sequence": 7,
                "rejected_sequences": [],
                "plans": {
                    "plan-7": {
                        "sequence": 7,
                        "payload_digest": "a" * 64,
                        "result": {
                            "outcome": "applied",
                            "reason_code": "applied",
                            "exact_plan_digest": "sha256:" + "b" * 64,
                            "summary": "",
                            "retryable": False,
                        },
                        "attempts": 1,
                        "reported_at": "2026-10-07T12:00:00+00:00",
                        "reported": True,
                    }
                },
            }
        )
    )

    record = store.load().plans["plan-7"]

    assert record.reported is True
    assert record.apply_started_report is None
    assert [report.attempt for report in record.report_history] == [1]
    assert record.pending_reports == ()


def test_v2_contiguous_apply_progress_is_migrated(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path)
    started = {
        "attempt": 1,
        "result": {
            "outcome": "apply-started",
            "reason_code": "apply_started",
            "exact_plan_digest": "sha256:" + "b" * 64,
            "summary": "",
            "retryable": False,
        },
        "reported_at": "2026-10-07T11:59:59+00:00",
    }
    terminal = {
        "outcome": "applied",
        "reason_code": "applied",
        "exact_plan_digest": "sha256:" + "b" * 64,
        "summary": "",
        "retryable": False,
    }
    store.path.write_text(
        json.dumps(
            {
                "schema": "fdai.lifecycle-agent-state.v2",
                "last_accepted_sequence": 7,
                "rejected_sequences": [],
                "plans": {
                    "plan-7": {
                        "sequence": 7,
                        "payload_digest": "a" * 64,
                        "result": terminal,
                        "attempts": 2,
                        "reported_at": "2026-10-07T12:00:00+00:00",
                        "reported": False,
                        "apply_started_report": started,
                        "pending_reports": [
                            started,
                            {
                                "attempt": 2,
                                "result": terminal,
                                "reported_at": "2026-10-07T12:00:00+00:00",
                            },
                        ],
                    }
                },
            }
        )
    )

    record = store.load().plans["plan-7"]

    assert [report.attempt for report in record.report_history] == [1, 2]
    assert record.pending_reports == record.report_history
    assert json.loads(store.path.read_text())["schema"] == "fdai.lifecycle-agent-state.v3"


def test_v2_non_contiguous_retryable_apply_progress_fails_closed(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path)
    started = {
        "attempt": 2,
        "result": {
            "outcome": "apply-started",
            "reason_code": "apply_started",
            "exact_plan_digest": "sha256:" + "b" * 64,
            "summary": "",
            "retryable": False,
        },
        "reported_at": "2026-10-07T11:59:59+00:00",
    }
    document = {
        "schema": "fdai.lifecycle-agent-state.v2",
        "last_accepted_sequence": 7,
        "rejected_sequences": [],
        "plans": {
            "plan-7": {
                "sequence": 7,
                "payload_digest": "a" * 64,
                "result": {
                    "outcome": "applied",
                    "reason_code": "applied",
                    "exact_plan_digest": "sha256:" + "b" * 64,
                    "summary": "",
                    "retryable": False,
                },
                "attempts": 3,
                "reported_at": "2026-10-07T12:00:00+00:00",
                "reported": False,
                "apply_started_report": started,
                "pending_reports": [],
            }
        },
    }
    store.path.write_text(json.dumps(document))

    with pytest.raises(AgentStateError, match="invalid"):
        store.load()
    assert json.loads(store.path.read_text()) == document


@pytest.mark.parametrize(
    ("last_accepted_sequence", "reason_code"),
    [
        (-1, "plan_expired"),
        (7, "release_unavailable"),
    ],
)
def test_other_missing_tombstones_still_fail_closed(
    tmp_path: Path, last_accepted_sequence: int, reason_code: str
) -> None:
    store = LocalStateStore(tmp_path)
    document = {
        "schema": "fdai.lifecycle-agent-state.v1",
        "last_accepted_sequence": last_accepted_sequence,
        "rejected_sequences": [],
        "plans": {
            "plan-7": {
                "sequence": 7,
                "payload_digest": "a" * 64,
                "result": {
                    "outcome": "rejected",
                    "reason_code": reason_code,
                    "exact_plan_digest": None,
                    "summary": "",
                    "retryable": False,
                },
                "attempts": 0,
                "reported_at": None,
                "reported": False,
            }
        },
    }
    store.path.write_text(json.dumps(document))

    with pytest.raises(AgentStateError, match="invalid"):
        store.load()
    assert json.loads(store.path.read_text()) == document


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


def test_report_history_size_is_bounded(tmp_path: Path) -> None:
    reports = tuple(
        StoredReport(
            attempt=attempt,
            result=PlanResult(
                outcome="rejected",
                reason_code="release_unavailable",
                retryable=True,
            ),
            reported_at=datetime(2026, 10, 7, 12, attempt, tzinfo=UTC),
        )
        for attempt in range(1, MAX_REPORT_HISTORY + 2)
    )
    record = _record(
        1,
        retryable=True,
        attempts=len(reports),
        reported_at=reports[-1].reported_at,
        report_history=reports,
    )

    with pytest.raises(AgentStateError, match="invalid"):
        LocalStateStore(tmp_path).save(AgentState(plans={"plan-1": record}))


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


def test_final_rejection_after_admission_retains_the_replay_tombstone() -> None:
    admitted = _record(
        7,
        result=PlanResult(
            outcome="apply-started",
            reason_code="apply_started",
            exact_plan_digest="sha256:" + "a" * 64,
        ),
    )
    rejected = replace(
        admitted,
        result=PlanResult(outcome="rejected", reason_code="plan_expired"),
    )

    state = AgentState().with_result("plan-7", admitted).with_result("plan-7", rejected)

    assert state.last_accepted_sequence == 7
    assert state.rejected_sequences == {7}
    assert state.plans["plan-7"].result == rejected.result


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


@pytest.mark.parametrize(
    "record",
    [
        _record(1, attempts=0, reported=True),
        _record(1, attempts=0, reported_at=datetime(2026, 10, 7, 12, tzinfo=UTC)),
        _record(1, attempts=1, reported=True),
    ],
)
def test_invalid_report_progress_is_not_persisted(tmp_path: Path, record: PlanRecord) -> None:
    store = LocalStateStore(tmp_path)

    with pytest.raises(AgentStateError, match="invalid"):
        store.save(AgentState(rejected_sequences=frozenset({1}), plans={"plan-1": record}))
    assert not store.path.exists()


@pytest.mark.parametrize(
    "result",
    [
        PlanResult(outcome="rejected", reason_code="INVALID"),
        PlanResult(outcome="rejected", reason_code="valid", exact_plan_digest="sha256:bad"),
        PlanResult(outcome="rejected", reason_code="valid", summary="x" * 2001),
        PlanResult(
            outcome="dry-run-admitted",
            reason_code="dry_run_computed",
            exact_plan_digest=None,
        ),
        PlanResult(
            outcome="dry-run-admitted",
            reason_code="dry_run_computed",
            exact_plan_digest="sha256:" + "b" * 64,
            retryable=True,
        ),
    ],
)
def test_invalid_plan_result_is_not_persisted(tmp_path: Path, result: PlanResult) -> None:
    store = LocalStateStore(tmp_path)
    state = AgentState(
        last_accepted_sequence=1,
        rejected_sequences=frozenset({1}) if not result.admitted else frozenset(),
        plans={"plan-1": _record(1, result=result)},
    )

    with pytest.raises(AgentStateError, match="invalid"):
        store.save(state)
    assert not store.path.exists()


@pytest.mark.parametrize(
    "state",
    [
        AgentState(
            last_accepted_sequence=0,
            plans={
                "plan-1": _record(
                    1,
                    result=PlanResult(
                        outcome="dry-run-admitted",
                        reason_code="dry_run_computed",
                        exact_plan_digest="sha256:" + "b" * 64,
                    ),
                )
            },
        ),
        AgentState(
            last_accepted_sequence=1,
            rejected_sequences=frozenset({1}),
            plans={
                "plan-1": _record(
                    1,
                    result=PlanResult(
                        outcome="dry-run-admitted",
                        reason_code="dry_run_computed",
                        exact_plan_digest="sha256:" + "b" * 64,
                    ),
                )
            },
        ),
        AgentState(
            plans={"plan-1": _record(1)},
        ),
    ],
)
def test_inconsistent_replay_state_is_not_persisted(tmp_path: Path, state: AgentState) -> None:
    store = LocalStateStore(tmp_path)

    with pytest.raises(AgentStateError, match="invalid"):
        store.save(state)
    assert not store.path.exists()

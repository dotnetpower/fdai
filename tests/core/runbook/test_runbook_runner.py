"""Runbook DAG orchestrator - linear + on_failure branch."""

from __future__ import annotations

import pytest

from fdai.core.runbook import (
    Runbook,
    RunbookRunError,
    RunbookRunner,
    RunbookStep,
    RunbookStepOutcome,
    RunbookStepResult,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

# ---------------------------------------------------------------------------
# Structural validation - construction-time invariants
# ---------------------------------------------------------------------------


def test_empty_step_list_is_rejected() -> None:
    with pytest.raises(RunbookRunError, match="no steps"):
        Runbook(id="rb.empty", steps=())


def test_duplicate_step_ids_are_rejected() -> None:
    with pytest.raises(RunbookRunError, match="duplicate step id"):
        Runbook(
            id="rb.dup",
            steps=(
                RunbookStep(id="a", action_type="ops.x"),
                RunbookStep(id="a", action_type="ops.y"),
            ),
        )


def test_on_failure_targeting_unknown_step_is_rejected() -> None:
    with pytest.raises(RunbookRunError, match="unknown step"):
        Runbook(
            id="rb.bad-branch",
            steps=(RunbookStep(id="a", action_type="ops.x", on_failure="nowhere"),),
        )


def test_on_failure_targeting_a_known_step_is_accepted() -> None:
    Runbook(
        id="rb.branch",
        steps=(
            RunbookStep(id="main", action_type="ops.x", on_failure="rollback"),
            RunbookStep(id="rollback", action_type="ops.rollback"),
        ),
    )


# ---------------------------------------------------------------------------
# Runner behavior - happy path + failure + on_failure branch
# ---------------------------------------------------------------------------


class _StubExecutor:
    """Executes according to a script keyed by step id."""

    def __init__(self, outcomes: dict[str, RunbookStepOutcome]) -> None:
        self._outcomes = outcomes
        self.calls: list[str] = []

    async def execute(self, *, runbook_id, step):  # noqa: ANN001, ANN201, ARG002
        self.calls.append(step.id)
        return RunbookStepResult(
            step_id=step.id,
            action_type=step.action_type,
            outcome=self._outcomes.get(step.id, RunbookStepOutcome.SUCCESS),
            reason=None
            if self._outcomes.get(step.id, RunbookStepOutcome.SUCCESS) is RunbookStepOutcome.SUCCESS
            else "stub_failure",
        )


async def test_happy_path_runs_every_step_and_records_success() -> None:
    rb = Runbook(
        id="rb.happy",
        steps=(
            RunbookStep(id="s1", action_type="ops.a"),
            RunbookStep(id="s2", action_type="ops.b"),
            RunbookStep(id="s3", action_type="ops.c"),
        ),
    )
    executor = _StubExecutor(outcomes={})  # all success by default
    audit = InMemoryStateStore()
    runner = RunbookRunner(executor=executor, audit_store=audit)
    result = await runner.run(rb)
    assert result.terminal_outcome is RunbookStepOutcome.SUCCESS
    assert executor.calls == ["s1", "s2", "s3"]
    assert [r.outcome for r in result.step_results] == [
        RunbookStepOutcome.SUCCESS,
    ] * 3
    # One aggregate audit row emitted.
    kinds = [row["entry"]["action_kind"] for row in audit.audit_entries]
    assert kinds == ["runbook.terminal"]


async def test_failure_without_on_failure_short_circuits_and_marks_skipped() -> None:
    rb = Runbook(
        id="rb.fail",
        steps=(
            RunbookStep(id="s1", action_type="ops.a"),
            RunbookStep(id="s2", action_type="ops.b"),
            RunbookStep(id="s3", action_type="ops.c"),
        ),
    )
    executor = _StubExecutor(outcomes={"s2": RunbookStepOutcome.FAILURE})
    audit = InMemoryStateStore()
    runner = RunbookRunner(executor=executor, audit_store=audit)
    result = await runner.run(rb)
    assert result.terminal_outcome is RunbookStepOutcome.FAILURE
    # s3 was never executed; the runner marked it SKIPPED.
    assert executor.calls == ["s1", "s2"]
    outcomes = [r.outcome for r in result.step_results]
    assert outcomes == [
        RunbookStepOutcome.SUCCESS,
        RunbookStepOutcome.FAILURE,
        RunbookStepOutcome.SKIPPED,
    ]


async def test_on_failure_branch_runs_when_step_fails() -> None:
    rb = Runbook(
        id="rb.branch",
        steps=(
            RunbookStep(id="main", action_type="ops.failover", on_failure="rollback"),
            RunbookStep(id="verify", action_type="ops.healthcheck"),
            RunbookStep(id="rollback", action_type="ops.rollback"),
        ),
    )
    executor = _StubExecutor(outcomes={"main": RunbookStepOutcome.FAILURE})
    audit = InMemoryStateStore()
    runner = RunbookRunner(executor=executor, audit_store=audit)
    result = await runner.run(rb)
    assert result.terminal_outcome is RunbookStepOutcome.FAILURE
    # main -> rollback (on_failure) then short-circuit; verify skipped.
    assert executor.calls == ["main", "rollback"]
    outcomes = {r.step_id: r.outcome for r in result.step_results}
    assert outcomes["main"] is RunbookStepOutcome.FAILURE
    assert outcomes["rollback"] is RunbookStepOutcome.SUCCESS
    assert outcomes["verify"] is RunbookStepOutcome.SKIPPED


async def test_terminal_audit_row_carries_every_step_outcome() -> None:
    rb = Runbook(
        id="rb.audit",
        steps=(
            RunbookStep(id="s1", action_type="ops.a"),
            RunbookStep(id="s2", action_type="ops.b"),
        ),
    )
    audit = InMemoryStateStore()
    runner = RunbookRunner(executor=_StubExecutor(outcomes={}), audit_store=audit)
    await runner.run(rb)
    entry = list(audit.audit_entries)[0]["entry"]
    assert entry["action_kind"] == "runbook.terminal"
    assert entry["runbook_id"] == "rb.audit"
    assert entry["terminal_outcome"] == "success"
    step_outcomes = entry["step_outcomes"]
    assert [s["step_id"] for s in step_outcomes] == ["s1", "s2"]

"""Resilience runner invocation, status handling, and rollback."""

from __future__ import annotations

from datetime import datetime
from typing import Final

from fdai.core.verticals.resilience.models import (
    DrExperiment,
    DrRunResult,
    RunOutcome,
    SchedulerDecision,
)
from fdai.shared.providers.dr_experiment import DrExperimentRunner, DrRunHandle, DrRunStatus

_ROLLBACK_STATUSES: Final[frozenset[DrRunStatus]] = frozenset(
    {DrRunStatus.FAILED, DrRunStatus.STOPPED}
)
_ERROR_MESSAGE_CAP: Final[int] = 200


async def invoke_runner(
    *,
    runner: DrExperimentRunner,
    experiment: DrExperiment,
    decision: SchedulerDecision,
    at: datetime,
) -> DrRunResult:
    """Start, check, and roll back one experiment when required."""
    try:
        handle = await runner.start(experiment)
    except Exception as exc:  # noqa: BLE001 - runner Protocol surface
        return DrRunResult(
            experiment_id=experiment.experiment_id,
            outcome=RunOutcome.FAILED,
            decision=decision,
            at=at,
            error=truncate_error(exc),
            reasons=("runner:start_failed",),
        )

    try:
        status = await runner.check(handle)
    except Exception as exc:  # noqa: BLE001 - runner Protocol surface
        rollback_error = await safe_rollback(runner, handle)
        reasons: tuple[str, ...] = ("runner:check_failed",)
        if rollback_error is not None:
            reasons = (*reasons, "rollback:error")
        return DrRunResult(
            experiment_id=experiment.experiment_id,
            outcome=RunOutcome.ROLLED_BACK,
            decision=decision,
            handle=handle,
            at=at,
            error=truncate_error(exc),
            reasons=reasons,
        )

    if status in _ROLLBACK_STATUSES:
        rollback_error = await safe_rollback(runner, handle)
        reasons = (f"runner:status={status.value}",)
        if rollback_error is not None:
            reasons = (*reasons, "rollback:error")
        return DrRunResult(
            experiment_id=experiment.experiment_id,
            outcome=RunOutcome.ROLLED_BACK,
            decision=decision,
            handle=handle,
            status=status,
            at=at,
            reasons=reasons,
        )

    return DrRunResult(
        experiment_id=experiment.experiment_id,
        outcome=RunOutcome.EXECUTED,
        decision=decision,
        handle=handle,
        status=status,
        at=at,
        reasons=(f"runner:status={status.value}",),
    )


def truncate_error(exc: BaseException) -> str:
    """Return a short log-safe exception message without traceback data."""
    text = str(exc).replace("\n", " ")
    if len(text) > _ERROR_MESSAGE_CAP:
        return text[:_ERROR_MESSAGE_CAP] + "..."
    return text


async def safe_rollback(runner: DrExperimentRunner, handle: DrRunHandle) -> BaseException | None:
    """Attempt idempotent rollback and return any rollback error."""
    try:
        await runner.rollback(handle)
    except Exception as exc:  # noqa: BLE001 - runner Protocol surface
        return exc
    return None

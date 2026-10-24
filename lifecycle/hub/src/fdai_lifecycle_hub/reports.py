"""What an execution report means to the Hub beyond storing it.

The agent reports `dry-run-admitted` or `rejected` for a dry run. When it applies a Plan, it
reports `apply-started` right before the change and then `applied` or `rolled-back` with the next
attempt. A `rolled-back` report holds every Entity of the Plan, so the Hub doesn't plan the
failed Release for them again until the hold ends or an operator lifts it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Literal, Protocol

from fdai_deployment_cli.lifecycle_plan import SuppressionWindow

from fdai_lifecycle_hub.domain import IssuedPlan

type ReportOutcome = Literal[
    "dry-run-admitted", "rejected", "apply-started", "applied", "rolled-back"
]

ROLLED_BACK = "rolled-back"
# Outcomes whose reason code is fixed. Any other outcome takes any reason code.
FINAL_REASONS: Mapping[str, frozenset[str]] = {
    "applied": frozenset({"applied"}),
    ROLLED_BACK: frozenset({"health_check_failed", "apply_failed"}),
}
FAILURE_HOLD = timedelta(hours=24)
# The Hub writes this hold from its own process's clock, and a later recompute, possibly on
# another process or host, reads it back from its own clock. Backdating the start absorbs small
# clock skew between the two without weakening an operator's own future-dated suppression.
FAILURE_HOLD_GRACE = timedelta(minutes=1)
_TERMINAL_OUTCOMES = frozenset({"dry-run-admitted", "applied", ROLLED_BACK})
_EFFECT_OUTCOMES = frozenset({"applied", ROLLED_BACK})


class ReportProgress(Protocol):
    attempt: int
    outcome: str
    reported_at: datetime


def validate_report_progress(previous: ReportProgress | None, current: ReportProgress) -> None:
    """Reject gaps, time reversal, and impossible effect-result transitions."""

    if previous is None:
        if current.attempt != 1:
            raise ValueError("the first report attempt MUST be 1")
        if current.outcome in _EFFECT_OUTCOMES:
            raise ValueError("an effect result requires an apply-started report")
        return
    if current.attempt != previous.attempt + 1:
        raise ValueError("report attempts MUST be contiguous")
    if current.reported_at < previous.reported_at:
        raise ValueError("report timestamps MUST NOT move backwards")
    if previous.outcome in _TERMINAL_OUTCOMES:
        raise ValueError("a terminal report cannot be followed by another report")
    if current.outcome in _EFFECT_OUTCOMES and previous.outcome != "apply-started":
        raise ValueError("an effect result requires the preceding apply-started report")


def failure_suppressions(
    plan: IssuedPlan, now: datetime, *, hold: timedelta = FAILURE_HOLD
) -> tuple[SuppressionWindow, ...]:
    """One failure-origin suppression per Entity of a rolled-back Plan, starting just before now."""

    starts_at = now - FAILURE_HOLD_GRACE
    return tuple(
        SuppressionWindow(
            scope=f"entity:{entity_id}",
            starts_at=starts_at,
            ends_at=starts_at + hold,
            origin="failure",
            failed_plan_id=plan.plan_id,
        )
        for entity_id in sorted(plan.entity_ids)
    )

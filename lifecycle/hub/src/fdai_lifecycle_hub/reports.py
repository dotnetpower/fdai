"""What an execution report means to the Hub beyond storing it.

The agent reports `dry-run-admitted` or `rejected` for a dry run. When it applies a Plan, it
reports `apply-started` right before the change and then `applied` or `rolled-back` with the next
attempt. A `rolled-back` report holds every Entity of the Plan, so the Hub doesn't plan the
failed Release for them again until the hold ends or an operator lifts it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Literal

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

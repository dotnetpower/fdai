"""ActionRun lifecycle states shared by Thor's private helpers."""

from __future__ import annotations

from enum import StrEnum


class ActionRunState(StrEnum):
    PROPOSED = "proposed"
    VERDICTED = "verdicted"
    HIL_PENDING = "hil_pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DENY_DROPPED = "deny_dropped"
    EXECUTING = "executing"
    EXECUTION_UNKNOWN = "execution_unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"


TERMINAL_ACTION_RUN_STATES: frozenset[ActionRunState] = frozenset(
    {
        ActionRunState.SUCCEEDED,
        ActionRunState.REJECTED,
        ActionRunState.DENY_DROPPED,
        ActionRunState.ROLLED_BACK,
        ActionRunState.ROLLBACK_FAILED,
    }
)


__all__ = ["ActionRunState", "TERMINAL_ACTION_RUN_STATES"]

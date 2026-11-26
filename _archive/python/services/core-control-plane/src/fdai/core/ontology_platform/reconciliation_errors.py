"""Shared errors for effect reconciliation ledgers."""


class ReconciliationConflictError(RuntimeError):
    """A stable reconciliation identity was reused with inconsistent request content."""


class ReconciliationLedgerCorruptionError(RuntimeError):
    """Durable reconciliation state failed its strict replay contract."""


class ReconciliationAttemptLimitError(RuntimeError):
    """A reconciliation exhausted its bounded non-terminal observation attempts."""


class ReconciliationAggregateLimitError(RuntimeError):
    """A durable reconciliation aggregate exceeded its canonical byte ceiling."""

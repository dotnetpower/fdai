"""Canonical alert-noise ActionType names independent of any delivery mechanism."""

RESTORE_ACTION = "ops.restore-alert-configuration"
ALERT_ACTIONS = frozenset(
    {
        "ops.update-alert-routing",
        "ops.set-alert-notification-window",
        "ops.tune-alert-evaluation",
        RESTORE_ACTION,
    }
)

__all__ = ["ALERT_ACTIONS", "RESTORE_ACTION"]

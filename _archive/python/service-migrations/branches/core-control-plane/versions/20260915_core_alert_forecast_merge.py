"""Join retained alert/handover and forecast migration heads without rewriting history."""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "core_alert_forecast_merge_20260915"
down_revision: str | Sequence[str] | None = (
    "core_alert_handover_merge_20260915",
    "core_forecast_closure_observation_20260914",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "remove-alert-forecast-merge-marker",
    "restores": "core_alert_handover_merge_20260915,core_forecast_closure_observation_20260914",
    "requires": "none",
}


def upgrade() -> None:
    """Join both applied lineages without changing schema, data, grants or prior revisions."""


def downgrade() -> None:
    """Remove only this merge marker, preserving both parent effects and rollback contracts."""

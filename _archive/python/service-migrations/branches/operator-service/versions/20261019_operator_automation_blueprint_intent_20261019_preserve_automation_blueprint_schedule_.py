"""preserve automation blueprint schedule intent

Revision ID: operator_automation_blueprint_intent_20261019
Revises: operator_entitlement_state_read_20261001
Create Date: 2026-10-19 12:25:54.068222+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_automation_blueprint_intent_20261019"
down_revision: str | Sequence[str] | None = "operator_entitlement_state_read_20261001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables = ("automation_blueprint_candidate",)
rollback = {
    "strategy": "drop-additive-automation-blueprint-intent",
    "restores": "operator_entitlement_state_read_20261001",
    "requires": "automation-blueprint-writers-stopped",
}


def upgrade() -> None:
    """Persist the reviewed timezone and canonical event payload."""

    op.execute(
        """
        ALTER TABLE automation_blueprint_candidate
            ADD COLUMN schedule_timezone TEXT NOT NULL DEFAULT 'UTC',
            ADD COLUMN event_payload_json TEXT NOT NULL DEFAULT '{}',
            ADD CONSTRAINT automation_blueprint_schedule_timezone_nonempty
                CHECK (char_length(schedule_timezone) BETWEEN 1 AND 255),
            ADD CONSTRAINT automation_blueprint_event_payload_bounded
                CHECK (
                    char_length(event_payload_json) <= 16384
                    AND jsonb_typeof(event_payload_json::jsonb) = 'object'
                );
        """
    )


def downgrade() -> None:
    """Remove only the additive reviewed-intent fields."""

    op.execute(
        """
        ALTER TABLE automation_blueprint_candidate
            DROP COLUMN event_payload_json,
            DROP COLUMN schedule_timezone;
        """
    )

"""add trajectory deletion claim state

Revision ID: 20260814_0084
Revises: 20260814_0083
Create Date: 2026-08-14 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260814_0084"
down_revision: str | None = "20260814_0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_DELETION_GUARD_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM trajectory_dataset WHERE state = 'deleting'
    ) THEN
        RAISE EXCEPTION
            'cannot downgrade while trajectory deletion claims are active'
            USING ERRCODE = '55000';
    END IF;
END
$$;
"""


def upgrade() -> None:
    op.execute(
        """
        DROP INDEX trajectory_dataset_retention_idx;
        ALTER TABLE trajectory_dataset
            DROP CONSTRAINT trajectory_dataset_state_check,
            ADD CONSTRAINT ck_trajectory_dataset_state CHECK (
                state IN (
                    'pending', 'completed', 'cancelled', 'quarantined', 'deleting', 'deleted'
                )
            ),
            ADD CONSTRAINT ck_trajectory_deleting_claim CHECK (
                state <> 'deleting'
                OR (
                    legal_hold = FALSE
                    AND storage_ref IS NOT NULL
                    AND dataset_checksum IS NOT NULL
                    AND manifest_checksum IS NOT NULL
                )
            );
        CREATE INDEX trajectory_dataset_retention_idx
            ON trajectory_dataset (deletion_due_at, dataset_id)
            WHERE state IN ('completed', 'deleting') AND legal_hold = FALSE;
        """
    )


def downgrade() -> None:
    op.execute(_ACTIVE_DELETION_GUARD_SQL)
    op.execute(
        """
        DROP INDEX trajectory_dataset_retention_idx;
        ALTER TABLE trajectory_dataset
            DROP CONSTRAINT ck_trajectory_deleting_claim,
            DROP CONSTRAINT ck_trajectory_dataset_state,
            ADD CONSTRAINT trajectory_dataset_state_check CHECK (
                state IN ('pending', 'completed', 'cancelled', 'quarantined', 'deleted')
            );
        CREATE INDEX trajectory_dataset_retention_idx
            ON trajectory_dataset (deletion_due_at, dataset_id)
            WHERE state <> 'deleted' AND legal_hold = FALSE;
        """
    )

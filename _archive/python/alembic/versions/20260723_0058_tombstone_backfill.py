"""allow zero-size revision metadata for legacy tombstone backfill

Revision ID: 20260723_0058
Revises: 20260723_0057
Create Date: 2026-07-23 17:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260723_0058"
down_revision: str | None = "20260723_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE constraint_name TEXT;
        BEGIN
            FOR constraint_name IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'case_history_revision'::regclass
                  AND contype = 'c'
                  AND pg_get_constraintdef(oid) LIKE '%artifact_size%'
            LOOP
                EXECUTE format(
                    'ALTER TABLE case_history_revision DROP CONSTRAINT %I',
                    constraint_name
                );
            END LOOP;
        END $$;
        ALTER TABLE case_history_revision
            ADD CONSTRAINT ck_case_history_revision_artifact_size
            CHECK (artifact_size >= 0);
        """
    )


def downgrade() -> None:
    # Zero-size metadata is required to preserve deleted identities whose
    # artifacts were already removed. The table owner migration removes it.
    pass

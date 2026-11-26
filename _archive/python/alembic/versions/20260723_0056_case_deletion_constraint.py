"""allow completed case deletion to clear artifact references

Revision ID: 20260723_0056
Revises: 20260723_0055
Create Date: 2026-07-23 16:20:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260723_0056"
down_revision: str | None = "20260723_0055"
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
                WHERE conrelid = 'case_history'::regclass
                  AND contype = 'c'
                  AND pg_get_constraintdef(oid) LIKE '%deletion_storage_refs%'
                  AND pg_get_constraintdef(oid) LIKE '%deletion_started_at%'
            LOOP
                EXECUTE format(
                    'ALTER TABLE case_history DROP CONSTRAINT %I', constraint_name
                );
            END LOOP;
        END $$;
        ALTER TABLE case_history
            ADD CONSTRAINT ck_case_history_safe_deletion_refs CHECK (
                (deletion_started_at IS NULL AND cardinality(deletion_storage_refs) = 0)
                OR (deletion_started_at IS NOT NULL
                    AND deleted_at IS NULL
                    AND cardinality(deletion_storage_refs) > 0
                    AND array_position(deletion_storage_refs, '') IS NULL
                    AND array_to_string(deletion_storage_refs, ',') ~
                        '^case-history/[A-Za-z0-9._/-]+(,case-history/[A-Za-z0-9._/-]+)*$')
                OR (deletion_started_at IS NOT NULL
                    AND deleted_at IS NOT NULL
                    AND cardinality(deletion_storage_refs) = 0)
            );
        """
    )


def downgrade() -> None:
    # The repaired constraint is required for valid tombstones and remains in
    # place until the owning table is removed by migration 0054.
    pass

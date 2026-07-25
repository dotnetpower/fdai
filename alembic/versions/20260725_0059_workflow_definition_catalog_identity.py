"""bind workflow definition uniqueness to the resolved action catalog

Revision ID: 20260725_0059
Revises: 20260723_0058
Create Date: 2026-07-25 20:25:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260725_0059"
down_revision: str | None = "20260723_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE constraint_name TEXT;
        BEGIN
            SELECT conname INTO constraint_name
            FROM pg_constraint
            WHERE conrelid = 'workflow_definition'::regclass
              AND contype = 'u'
              AND pg_get_constraintdef(oid) =
                  'UNIQUE (workflow_name, workflow_version, definition_hash)';
            IF constraint_name IS NOT NULL THEN
                EXECUTE format(
                    'ALTER TABLE workflow_definition DROP CONSTRAINT %I',
                    constraint_name
                );
            END IF;
        END $$;
        ALTER TABLE workflow_definition
            ADD CONSTRAINT uq_workflow_definition_catalog_identity
            UNIQUE (
                workflow_name,
                workflow_version,
                definition_hash,
                action_catalog_digest
            );
        """
    )


def downgrade() -> None:
    # Multiple immutable definitions can legitimately share the workflow
    # document while pinning different action catalogs. Reintroducing the old
    # constraint would discard that history, so downgrade is intentionally safe-forward.
    pass

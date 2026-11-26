"""allow governed skill bundle trusted artifacts

Revision ID: 20260720_0042
Revises: 20260720_0041
Create Date: 2026-07-20 15:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260720_0042"
down_revision: str | None = "20260720_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE trusted_artifact
            DROP CONSTRAINT trusted_artifact_artifact_kind_check;
        ALTER TABLE trusted_artifact
            ADD CONSTRAINT trusted_artifact_artifact_kind_check
            CHECK (artifact_kind IN ('extension', 'skill', 'skill_bundle'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM trusted_artifact
                WHERE artifact_kind = 'skill_bundle'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade while trusted skill bundle artifacts exist';
            END IF;
        END $$;
        ALTER TABLE trusted_artifact
            DROP CONSTRAINT trusted_artifact_artifact_kind_check;
        ALTER TABLE trusted_artifact
            ADD CONSTRAINT trusted_artifact_artifact_kind_check
            CHECK (artifact_kind IN ('extension', 'skill'));
        """
    )

"""operational case metadata

Revision ID: 20260801_0067
Revises: 20260731_0066
Create Date: 2026-08-01 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260801_0067"
down_revision: str | None = "20260731_0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE case_history
            ALTER COLUMN detector_id DROP NOT NULL,
            ALTER COLUMN detector_version DROP NOT NULL,
            ALTER COLUMN metric DROP NOT NULL,
            ADD COLUMN metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            ADD CONSTRAINT ck_case_history_kind_metadata CHECK (
                (kind = 'prediction'
                    AND detector_id IS NOT NULL
                    AND detector_version IS NOT NULL
                    AND metric IS NOT NULL)
                OR (kind IN ('action', 'incident')
                    AND detector_id IS NULL
                    AND detector_version IS NULL
                    AND metric IS NULL)
            ),
            ADD CONSTRAINT ck_case_history_metadata_object CHECK (
                jsonb_typeof(metadata) = 'object'
            );

        ALTER TABLE case_history_revision
            ALTER COLUMN detector_id DROP NOT NULL,
            ALTER COLUMN detector_version DROP NOT NULL,
            ALTER COLUMN metric DROP NOT NULL,
            ADD COLUMN metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            ADD CONSTRAINT ck_case_history_revision_forecast_metadata CHECK (
                (detector_id IS NOT NULL
                    AND detector_version IS NOT NULL
                    AND metric IS NOT NULL)
                OR (detector_id IS NULL
                    AND detector_version IS NULL
                    AND metric IS NULL)
            ),
            ADD CONSTRAINT ck_case_history_revision_metadata_object CHECK (
                jsonb_typeof(metadata) = 'object'
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM case_history WHERE kind <> 'prediction') THEN
                RAISE EXCEPTION 'cannot downgrade while operational case history exists';
            END IF;
        END
        $$;

        ALTER TABLE case_history_revision
            DROP CONSTRAINT ck_case_history_revision_metadata_object,
            DROP CONSTRAINT ck_case_history_revision_forecast_metadata,
            DROP COLUMN metadata,
            ALTER COLUMN detector_id SET NOT NULL,
            ALTER COLUMN detector_version SET NOT NULL,
            ALTER COLUMN metric SET NOT NULL;

        ALTER TABLE case_history
            DROP CONSTRAINT ck_case_history_metadata_object,
            DROP CONSTRAINT ck_case_history_kind_metadata,
            DROP COLUMN metadata,
            ALTER COLUMN detector_id SET NOT NULL,
            ALTER COLUMN detector_version SET NOT NULL,
            ALTER COLUMN metric SET NOT NULL;
        """
    )

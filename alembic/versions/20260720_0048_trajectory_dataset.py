"""governed trajectory dataset metadata and quarantine

Revision ID: 20260720_0048
Revises: 20260720_0047
Create Date: 2026-07-21 12:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260720_0048"
down_revision: str | None = "20260720_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE trajectory_dataset (
            dataset_id TEXT PRIMARY KEY,
            purpose TEXT NOT NULL,
            access_scope TEXT NOT NULL,
            principal_scope_digest TEXT NOT NULL
                CHECK (principal_scope_digest ~ '^[0-9a-f]{64}$'),
            state TEXT NOT NULL CHECK (
                state IN ('pending', 'completed', 'cancelled', 'quarantined', 'deleted')
            ),
            schema_version TEXT NOT NULL,
            storage_ref TEXT,
            record_count BIGINT NOT NULL CHECK (record_count >= 0),
            dataset_checksum TEXT CHECK (dataset_checksum ~ '^[0-9a-f]{64}$'),
            manifest_checksum TEXT CHECK (manifest_checksum ~ '^[0-9a-f]{64}$'),
            created_at TIMESTAMPTZ NOT NULL,
            retention_until TIMESTAMPTZ NOT NULL,
            deletion_due_at TIMESTAMPTZ NOT NULL,
            legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
            legal_hold_ref TEXT,
            deleted_at TIMESTAMPTZ,
            CHECK (created_at <= retention_until AND retention_until <= deletion_due_at),
            CHECK (legal_hold = (legal_hold_ref IS NOT NULL)),
            CHECK (
                state <> 'completed'
                OR (
                    storage_ref IS NOT NULL
                    AND dataset_checksum IS NOT NULL
                    AND manifest_checksum IS NOT NULL
                )
            ),
            CHECK (
                (state = 'deleted' AND storage_ref IS NULL AND deleted_at IS NOT NULL)
                OR (state <> 'deleted' AND deleted_at IS NULL)
            )
        );
        CREATE INDEX trajectory_dataset_scope_purpose_idx
            ON trajectory_dataset (access_scope, purpose, created_at DESC, dataset_id);
        CREATE INDEX trajectory_dataset_retention_idx
            ON trajectory_dataset (deletion_due_at, dataset_id)
            WHERE state <> 'deleted' AND legal_hold = FALSE;

        CREATE TABLE trajectory_export_quarantine (
            quarantine_id BIGSERIAL PRIMARY KEY,
            dataset_id TEXT NOT NULL,
            trajectory_id TEXT NOT NULL,
            finding_codes JSONB NOT NULL CHECK (jsonb_typeof(finding_codes) = 'array'),
            quarantined_at TIMESTAMPTZ NOT NULL,
            UNIQUE (dataset_id, trajectory_id)
        );
        CREATE INDEX trajectory_export_quarantine_dataset_idx
            ON trajectory_export_quarantine (dataset_id, quarantined_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE trajectory_export_quarantine;
        DROP TABLE trajectory_dataset;
        """
    )

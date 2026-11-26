"""add durable document worker stage claims

Revision ID: 20260806_0075
Revises: 20260805_0074
Create Date: 2026-08-06 08:30:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260806_0075"
down_revision: str | None = "20260805_0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE document_worker_claim (
            upload_id UUID NOT NULL REFERENCES document_upload_session(upload_id)
                ON DELETE CASCADE,
            stage TEXT NOT NULL CHECK (stage IN (
                'received_replay', 'inspection', 'protection_replay',
                'safety_decision', 'indexing'
            )),
            owner TEXT NOT NULL CHECK (char_length(owner) BETWEEN 1 AND 256),
            attempt_id UUID NOT NULL,
            revision INTEGER NOT NULL CHECK (revision >= 1),
            status TEXT NOT NULL CHECK (status IN ('active', 'completed', 'released')),
            claimed_at TIMESTAMPTZ NOT NULL,
            lease_expires_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ,
            PRIMARY KEY (upload_id, stage),
            CHECK (lease_expires_at > claimed_at),
            CHECK (
                (status = 'active' AND finished_at IS NULL)
                OR (status IN ('completed', 'released') AND finished_at IS NOT NULL)
            )
        );

        CREATE INDEX ix_document_worker_claim_active_lease
            ON document_worker_claim (lease_expires_at, upload_id, stage)
            WHERE status = 'active';
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_worker_claim;")

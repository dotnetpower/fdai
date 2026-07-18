"""inventory realtime overlay

Revision ID: 20260718_0035
Revises: 20260718_0034
Create Date: 2026-07-18 00:00:00+00:00

Real-time resource changes remain separate from immutable reconciliation
snapshots. Readers merge these latest-per-key rows over the active snapshot;
the next complete reconciliation retires overlay rows observed before that
scan began.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260718_0035"
down_revision: str | None = "20260718_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE inventory_realtime_resource (
            resource_id TEXT PRIMARY KEY,
            change_kind TEXT NOT NULL CHECK (change_kind IN ('upsert', 'delete')),
            resource_type TEXT NOT NULL,
            props JSONB NOT NULL DEFAULT '{}'::jsonb,
            provider_ref TEXT,
            observed_at TIMESTAMPTZ NOT NULL,
            event_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_inventory_realtime_resource_type "
        "ON inventory_realtime_resource(resource_type, observed_at DESC);"
    )
    op.execute(
        """
        CREATE TABLE inventory_realtime_link (
            from_id TEXT NOT NULL,
            from_type TEXT NOT NULL,
            link_type TEXT NOT NULL CHECK (link_type IN
                ('contains', 'attached_to', 'depends_on')),
            to_id TEXT NOT NULL,
            to_type TEXT NOT NULL,
            change_kind TEXT NOT NULL CHECK (change_kind IN ('upsert', 'delete')),
            props JSONB NOT NULL DEFAULT '{}'::jsonb,
            observed_at TIMESTAMPTZ NOT NULL,
            event_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (from_id, link_type, to_id),
            UNIQUE (idempotency_key, from_id, link_type, to_id)
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_inventory_realtime_link_observed "
        "ON inventory_realtime_link(observed_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inventory_realtime_link;")
    op.execute("DROP TABLE IF EXISTS inventory_realtime_resource;")

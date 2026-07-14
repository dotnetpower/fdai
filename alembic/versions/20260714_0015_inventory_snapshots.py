"""immutable inventory snapshots and atomic active pointer

Revision ID: 20260714_0015
Revises: 20260713_0014
Create Date: 2026-07-14 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260714_0015"
down_revision: str | None = "20260713_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE inventory_snapshot (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK (status IN
                ('collecting', 'active', 'failed', 'superseded')),
            source TEXT NOT NULL,
            observation_kind TEXT NOT NULL CHECK (observation_kind IN ('observed', 'expected')),
            scopes JSONB NOT NULL,
            resource_types JSONB NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ,
            promoted_at TIMESTAMPTZ,
            failure_code TEXT,
            failure_message TEXT
        );
        """
    )
    op.execute(
        """
        CREATE TABLE inventory_snapshot_resource (
            snapshot_id TEXT NOT NULL REFERENCES inventory_snapshot(id) ON DELETE CASCADE,
            resource_id TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            props JSONB NOT NULL DEFAULT '{}'::jsonb,
            provider_ref TEXT,
            last_seen TIMESTAMPTZ,
            PRIMARY KEY (snapshot_id, resource_id)
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_inventory_snapshot_resource_type "
        "ON inventory_snapshot_resource(snapshot_id, resource_type);"
    )
    op.execute(
        """
        CREATE TABLE inventory_snapshot_link (
            snapshot_id TEXT NOT NULL REFERENCES inventory_snapshot(id) ON DELETE CASCADE,
            from_id TEXT NOT NULL,
            from_type TEXT NOT NULL,
            link_type TEXT NOT NULL CHECK (link_type IN ('contains', 'attached_to', 'depends_on')),
            to_id TEXT NOT NULL,
            to_type TEXT NOT NULL,
            props JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (snapshot_id, from_id, link_type, to_id)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE inventory_active (
            singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
            snapshot_id TEXT NOT NULL REFERENCES inventory_snapshot(id),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inventory_active;")
    op.execute("DROP TABLE IF EXISTS inventory_snapshot_link;")
    op.execute("DROP TABLE IF EXISTS inventory_snapshot_resource;")
    op.execute("DROP TABLE IF EXISTS inventory_snapshot;")

"""managed_mcp_catalog: durable manifests, health, and admin audit

Revision ID: 20260717_0025
Revises: 20260717_0024
Create Date: 2026-07-17 08:30:00+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0025"
down_revision: str | None = "20260717_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE mcp_catalog_state (
            singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
            revision BIGINT NOT NULL CHECK (revision >= 0),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        INSERT INTO mcp_catalog_state (singleton, revision) VALUES (TRUE, 0);

        CREATE TABLE mcp_server (
            server_id TEXT PRIMARY KEY,
            server_url TEXT NOT NULL,
            tool_map JSONB NOT NULL CHECK (jsonb_typeof(tool_map) = 'object'),
            audience TEXT,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            health_status TEXT NOT NULL CHECK (
                health_status IN ('unknown', 'healthy', 'unhealthy')
            ),
            health_checked_at TIMESTAMPTZ,
            health_reason TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE mcp_admin_audit (
            audit_id BIGSERIAL PRIMARY KEY,
            revision BIGINT NOT NULL UNIQUE,
            action TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            server_id TEXT NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mcp_admin_audit;")
    op.execute("DROP TABLE IF EXISTS mcp_server;")
    op.execute("DROP TABLE IF EXISTS mcp_catalog_state;")

"""trusted_artifact: restart-safe extension and skill trust records

Revision ID: 20260717_0031
Revises: 20260717_0030
Create Date: 2026-07-17 15:30:00+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0031"
down_revision: str | None = "20260717_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE trusted_artifact (
            artifact_kind TEXT NOT NULL CHECK (artifact_kind IN ('extension', 'skill')),
            artifact_id TEXT NOT NULL CHECK (artifact_id ~ '^[a-z][a-z0-9.-]{2,127}$'),
            version TEXT NOT NULL CHECK (
                version ~ ('^(0|[1-9][0-9]*)[.]' ||
                           '(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)$')
            ),
            source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 512),
            content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[a-f0-9]{64}$'),
            artifact BYTEA NOT NULL CHECK (octet_length(artifact) BETWEEN 1 AND 33554432),
            signature BYTEA NOT NULL CHECK (octet_length(signature) = 64),
            state TEXT NOT NULL CHECK (state IN ('disabled', 'enabled')),
            revision BIGINT NOT NULL CHECK (revision > 0),
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL CHECK (updated_at >= created_at),
            PRIMARY KEY (artifact_kind, artifact_id)
        );
        CREATE INDEX trusted_artifact_kind_state_idx
            ON trusted_artifact (artifact_kind, state, artifact_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE trusted_artifact;")

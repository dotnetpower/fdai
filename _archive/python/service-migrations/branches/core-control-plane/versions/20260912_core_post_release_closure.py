"""Create atomic executor post-release closure storage."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "core_post_release_closure_20260912"
down_revision: str | Sequence[str] | None = "core_safeguard_dispatch_evidence_20260911"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "executor_audit_closure",
    "executor_post_release_closure",
    "executor_post_release_outbox",
)
rollback = {
    "strategy": "drop-executor-post-release-closure",
    "restores": "core_safeguard_dispatch_evidence_20260911",
    "requires": "executor-post-release-writers-stopped-and-outbox-drained",
}


def upgrade() -> None:
    """Create one closure state, audit history, and deterministic outbox."""

    op.execute(
        """
        CREATE TABLE executor_post_release_closure (
            closure_key TEXT PRIMARY KEY
                CHECK (closure_key ~ '^sha256:[0-9a-f]{64}$'),
            reservation_identity_digest TEXT NOT NULL
                CHECK (reservation_identity_digest ~ '^sha256:[0-9a-f]{64}$'),
            attempt INTEGER NOT NULL CHECK (attempt > 0),
            target_digest TEXT NOT NULL
                CHECK (target_digest ~ '^sha256:[0-9a-f]{64}$'),
            generation INTEGER NOT NULL CHECK (generation > 0),
            revision INTEGER NOT NULL CHECK (revision > 0),
            outcome TEXT NOT NULL CHECK (outcome IN ('resolved', 'quarantined')),
            identity_digest TEXT NOT NULL
                CHECK (identity_digest ~ '^sha256:[0-9a-f]{64}$'),
            record_digest TEXT NOT NULL
                CHECK (record_digest ~ '^sha256:[0-9a-f]{64}$'),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (reservation_identity_digest, attempt)
        );

        CREATE TABLE executor_audit_closure (
            closure_key TEXT NOT NULL
                CHECK (closure_key ~ '^sha256:[0-9a-f]{64}$'),
            closure_revision INTEGER NOT NULL CHECK (closure_revision > 0),
            audit_closure_digest TEXT NOT NULL UNIQUE
                CHECK (audit_closure_digest ~ '^sha256:[0-9a-f]{64}$'),
            record_digest TEXT NOT NULL
                CHECK (record_digest ~ '^sha256:[0-9a-f]{64}$'),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (closure_key, closure_revision)
        );

        CREATE TABLE executor_post_release_outbox (
            event_id TEXT PRIMARY KEY
                CHECK (event_id ~ '^sha256:[0-9a-f]{64}$'),
            closure_key TEXT NOT NULL
                CHECK (closure_key ~ '^sha256:[0-9a-f]{64}$'),
            closure_revision INTEGER NOT NULL CHECK (closure_revision > 0),
            partition_key TEXT NOT NULL
                CHECK (partition_key ~ '^sha256:[0-9a-f]{64}$'),
            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            published_at TIMESTAMPTZ,
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (closure_key, closure_revision)
        );

        CREATE INDEX executor_post_release_outbox_pending_idx
        ON executor_post_release_outbox (next_attempt_at, created_at)
        WHERE published_at IS NULL;

        REVOKE ALL PRIVILEGES ON TABLE
            executor_post_release_closure,
            executor_audit_closure,
            executor_post_release_outbox
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, UPDATE ON TABLE executor_post_release_closure
        TO fdai_core;
        GRANT SELECT, INSERT ON TABLE executor_audit_closure
        TO fdai_core;
        GRANT SELECT, INSERT, UPDATE ON TABLE executor_post_release_outbox
        TO fdai_core;
        """
    )


def _require_drained_outbox() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE executor_post_release_outbox IN ACCESS EXCLUSIVE MODE"))
    count = connection.execute(
        sa.text("SELECT count(*) FROM executor_post_release_outbox WHERE published_at IS NULL")
    ).scalar_one()
    if int(count) != 0:
        raise RuntimeError(
            "Core downgrade is blocked while post-release outbox rows are unpublished"
        )


def downgrade() -> None:
    """Drop closure tables only after writers stop and publication drains."""

    _require_drained_outbox()
    op.execute("DROP TABLE executor_post_release_outbox")
    op.execute("DROP TABLE executor_audit_closure")
    op.execute("DROP TABLE executor_post_release_closure")

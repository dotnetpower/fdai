"""Create durable safeguard dispatch and pre-release evidence storage."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_safeguard_dispatch_evidence_20260911"
down_revision: str | Sequence[str] | None = "core_target_dispatch_fence_20260910"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("safeguard_dispatch_evidence",)
rollback = {
    "strategy": "drop-safeguard-dispatch-evidence",
    "restores": "core_target_dispatch_fence_20260910",
    "requires": "executor-dispatch-evidence-writers-stopped",
}


def upgrade() -> None:
    """Create one authoritative record per target-fence generation."""

    op.execute(
        """
        CREATE TABLE safeguard_dispatch_evidence (
            target_digest TEXT NOT NULL
                CHECK (target_digest ~ '^sha256:[0-9a-f]{64}$'),
            generation INTEGER NOT NULL CHECK (generation > 0),
            revision INTEGER NOT NULL CHECK (revision > 0),
            state TEXT NOT NULL CHECK (
                state IN (
                    'bundle_persisted',
                    'dispatch_started',
                    'dispatch_observed',
                    'pre_release'
                )
            ),
            evidence_identity_digest TEXT NOT NULL
                CHECK (evidence_identity_digest ~ '^sha256:[0-9a-f]{64}$'),
            record_digest TEXT NOT NULL
                CHECK (record_digest ~ '^sha256:[0-9a-f]{64}$'),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (target_digest, generation)
        );

        REVOKE ALL PRIVILEGES ON TABLE safeguard_dispatch_evidence
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, UPDATE ON TABLE safeguard_dispatch_evidence TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop safeguard evidence only after every executor writer stops."""

    op.execute("DROP TABLE safeguard_dispatch_evidence")

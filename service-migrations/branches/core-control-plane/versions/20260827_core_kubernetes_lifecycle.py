"""Persist typed resumable Kubernetes lifecycle evidence."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_kubernetes_lifecycle_20260827"
down_revision: str | Sequence[str] | None = "core_interactive_read_investigation_20260826"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "kubernetes_lifecycle_cursor",
    "kubernetes_lifecycle_observation",
)
rollback = {
    "strategy": "drop-rebuildable-kubernetes-lifecycle-evidence",
    "restores": "core_interactive_read_investigation_20260826",
    "requires": "kubernetes-lifecycle-collectors-stopped",
}


def upgrade() -> None:
    """Create exact-scope lifecycle observations and per-cluster cursors."""

    op.execute(
        """
        CREATE TABLE kubernetes_lifecycle_cursor (
            cluster_ref TEXT PRIMARY KEY CHECK (char_length(cluster_ref) BETWEEN 1 AND 512),
            sequence BIGINT NOT NULL CHECK (sequence >= 0),
            resume_token TEXT NULL CHECK (
                resume_token IS NULL OR char_length(resume_token) BETWEEN 1 AND 1024
            ),
            coverage_started_at TIMESTAMPTZ NOT NULL,
            coverage_through_at TIMESTAMPTZ NOT NULL,
            retention_floor_at TIMESTAMPTZ NOT NULL,
            limitation TEXT NULL CHECK (
                limitation IS NULL OR char_length(limitation) BETWEEN 1 AND 128
            ),
            lease_holder TEXT NULL CHECK (
                lease_holder IS NULL OR char_length(lease_holder) BETWEEN 1 AND 256
            ),
            lease_expires_at TIMESTAMPTZ NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (coverage_through_at >= coverage_started_at),
            CHECK (retention_floor_at >= coverage_started_at),
            CHECK ((lease_holder IS NULL) = (lease_expires_at IS NULL))
        );

        CREATE TABLE kubernetes_lifecycle_observation (
            observation_id TEXT PRIMARY KEY
                CHECK (observation_id ~ '^sha256:[0-9a-f]{64}$'),
            cluster_ref TEXT NOT NULL
                REFERENCES kubernetes_lifecycle_cursor(cluster_ref),
            event_uid TEXT NOT NULL CHECK (char_length(event_uid) BETWEEN 1 AND 512),
            object_uid TEXT NOT NULL CHECK (char_length(object_uid) BETWEEN 1 AND 512),
            object_kind TEXT NOT NULL CHECK (char_length(object_kind) BETWEEN 1 AND 128),
            namespace TEXT NULL CHECK (
                namespace IS NULL OR char_length(namespace) BETWEEN 1 AND 256
            ),
            owner_uid TEXT NULL CHECK (
                owner_uid IS NULL OR char_length(owner_uid) BETWEEN 1 AND 512
            ),
            reason TEXT NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 512),
            event_type TEXT NOT NULL CHECK (char_length(event_type) BETWEEN 1 AND 128),
            lifecycle_kind TEXT NOT NULL CHECK (char_length(lifecycle_kind) BETWEEN 1 AND 128),
            action TEXT NOT NULL CHECK (action IN ('added', 'modified', 'deleted')),
            occurred_at TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            source_revision TEXT NOT NULL
                CHECK (char_length(source_revision) BETWEEN 1 AND 1024),
            occurrence_count BIGINT NOT NULL CHECK (occurrence_count >= 1),
            evidence_ref TEXT NOT NULL UNIQUE
                CHECK (char_length(evidence_ref) BETWEEN 1 AND 512),
            CHECK (recorded_at >= occurred_at)
        );
        CREATE INDEX kubernetes_lifecycle_cluster_time_idx
            ON kubernetes_lifecycle_observation (
                cluster_ref, occurred_at DESC, evidence_ref DESC
            );
        CREATE INDEX kubernetes_lifecycle_object_time_idx
            ON kubernetes_lifecycle_observation (
                cluster_ref, object_uid, occurred_at DESC, evidence_ref DESC
            );

        REVOKE ALL PRIVILEGES ON TABLE
            kubernetes_lifecycle_cursor,
            kubernetes_lifecycle_observation
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, UPDATE
            ON TABLE kubernetes_lifecycle_cursor TO fdai_core;
        GRANT SELECT, INSERT
            ON TABLE kubernetes_lifecycle_observation TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop lifecycle evidence after every collector and reader stops."""

    op.execute(
        """
        DROP TABLE kubernetes_lifecycle_observation;
        DROP TABLE kubernetes_lifecycle_cursor;
        """
    )

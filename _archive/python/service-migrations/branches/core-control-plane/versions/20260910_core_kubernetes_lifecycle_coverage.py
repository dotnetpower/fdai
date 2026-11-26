"""Persist immutable incomplete Kubernetes lifecycle coverage segments."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_kubernetes_lifecycle_coverage_20260910"
down_revision: str | Sequence[str] | None = "core_semantic_transport_ordering_20260908"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("kubernetes_lifecycle_coverage_segment",)
rollback = {
    "strategy": "drop-rebuildable-kubernetes-lifecycle-coverage",
    "restores": "core_semantic_transport_ordering_20260908",
    "requires": "kubernetes-lifecycle-collectors-and-readers-stopped",
}


def upgrade() -> None:
    """Create append-only per-cluster incomplete coverage segments."""

    op.execute(
        """
        CREATE TABLE kubernetes_lifecycle_coverage_segment (
            coverage_segment_id TEXT PRIMARY KEY
                CHECK (coverage_segment_id ~ '^sha256:[0-9a-f]{64}$'),
            cluster_ref TEXT NOT NULL
                REFERENCES kubernetes_lifecycle_cursor(cluster_ref),
            started_at TIMESTAMPTZ NOT NULL,
            ended_at TIMESTAMPTZ NOT NULL,
            limitation TEXT NOT NULL CHECK (
                limitation IN (
                    'authorization_denied',
                    'cursor_expired',
                    'resource_event_response_invalid',
                    'result_limit',
                    'source_unavailable'
                )
            ),
            CHECK (ended_at > started_at)
        );
        CREATE INDEX kubernetes_lifecycle_coverage_segment_cluster_time_idx
            ON kubernetes_lifecycle_coverage_segment (
                cluster_ref, started_at, ended_at, coverage_segment_id
            );

        REVOKE ALL PRIVILEGES ON TABLE kubernetes_lifecycle_coverage_segment
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT
            ON TABLE kubernetes_lifecycle_coverage_segment TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop incomplete coverage segments after collectors and readers stop."""

    op.execute("DROP TABLE kubernetes_lifecycle_coverage_segment")

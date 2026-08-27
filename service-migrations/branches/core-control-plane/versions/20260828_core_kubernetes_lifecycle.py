"""Add durable resumption cursor and append-only Kubernetes lifecycle evidence."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_kubernetes_lifecycle_20260828"
down_revision: str | Sequence[str] | None = "core_interactive_read_investigation_20260826"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "kubernetes_lifecycle_cursor",
    "kubernetes_lifecycle_observation",
)
rollback = {
    "strategy": "drop-kubernetes-lifecycle-cursor-and-evidence",
    "restores": "core_interactive_read_investigation_20260826",
    "requires": "kubernetes-lifecycle-collector-stopped",
}


def upgrade() -> None:
    """Create the durable cursor row and the append-only lifecycle evidence table."""

    op.execute(
        """
        CREATE TABLE kubernetes_lifecycle_cursor (
            cluster_ref TEXT PRIMARY KEY CHECK (char_length(cluster_ref) BETWEEN 1 AND 512),
            resource_version TEXT NOT NULL CHECK (char_length(resource_version) BETWEEN 1 AND 128),
            updated_at TIMESTAMPTZ NOT NULL
        );

        CREATE TABLE kubernetes_lifecycle_observation (
            evidence_ref TEXT PRIMARY KEY
                CHECK (evidence_ref ~ '^kubernetes-lifecycle:[0-9a-f]{64}$'),
            cluster_ref TEXT NOT NULL CHECK (char_length(cluster_ref) BETWEEN 1 AND 512),
            namespace TEXT NULL
                CHECK (namespace IS NULL OR char_length(namespace) BETWEEN 1 AND 253),
            object_uid TEXT NOT NULL CHECK (char_length(object_uid) BETWEEN 1 AND 512),
            owner_uid TEXT NULL
                CHECK (owner_uid IS NULL OR char_length(owner_uid) BETWEEN 1 AND 512),
            reason TEXT NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 128),
            category TEXT NOT NULL CHECK (category IN (
                'killing', 'failed', 'backoff', 'unhealthy', 'successful_create',
                'scheduled', 'started', 'deletion', 'other'
            )),
            event_type TEXT NOT NULL CHECK (char_length(event_type) BETWEEN 1 AND 64),
            event_time TIMESTAMPTZ NOT NULL,
            recorded_time TIMESTAMPTZ NOT NULL,
            source_revision TEXT NOT NULL CHECK (char_length(source_revision) BETWEEN 1 AND 128),
            record JSONB NOT NULL,
            CHECK (jsonb_typeof(record) = 'object')
        );
        CREATE INDEX kubernetes_lifecycle_observation_cluster_time_idx
            ON kubernetes_lifecycle_observation (cluster_ref, event_time, evidence_ref);
        CREATE INDEX kubernetes_lifecycle_observation_object_idx
            ON kubernetes_lifecycle_observation (cluster_ref, object_uid, event_time);

        CREATE FUNCTION fdai_reject_kubernetes_lifecycle_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'kubernetes lifecycle evidence is append-only';
        END;
        $$;
        CREATE TRIGGER kubernetes_lifecycle_observation_no_modify
            BEFORE UPDATE ON kubernetes_lifecycle_observation
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_kubernetes_lifecycle_mutation();
        CREATE TRIGGER kubernetes_lifecycle_observation_no_delete
            BEFORE DELETE ON kubernetes_lifecycle_observation
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_kubernetes_lifecycle_mutation();

        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE kubernetes_lifecycle_cursor TO fdai_core;
        GRANT SELECT, INSERT ON TABLE kubernetes_lifecycle_observation TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop lifecycle evidence and its cursor after the collector fully stops."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            kubernetes_lifecycle_observation,
            kubernetes_lifecycle_cursor
        FROM fdai_core;
        DROP TABLE kubernetes_lifecycle_observation;
        DROP TABLE kubernetes_lifecycle_cursor;
        DROP FUNCTION fdai_reject_kubernetes_lifecycle_mutation();
        """
    )

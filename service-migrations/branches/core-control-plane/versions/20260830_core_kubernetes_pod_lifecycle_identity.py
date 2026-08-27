"""Add immutable Pod controller identity for lifecycle cohort reads."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_kubernetes_pod_lifecycle_identity_20260830"
down_revision: str | Sequence[str] | None = "core_kubernetes_lifecycle_completeness_20260829"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("kubernetes_pod_lifecycle_identity",)
rollback = {
    "strategy": "drop-kubernetes-pod-lifecycle-identity",
    "restores": "core_kubernetes_lifecycle_completeness_20260829",
    "requires": "inventory-and-lifecycle-collectors-stopped",
}


def upgrade() -> None:
    """Create the append-only Pod controller identity table."""

    op.execute(
        """
        CREATE TABLE kubernetes_pod_lifecycle_identity (
            cluster_ref TEXT NOT NULL CHECK (char_length(cluster_ref) BETWEEN 1 AND 512),
            namespace TEXT NOT NULL CHECK (char_length(namespace) BETWEEN 1 AND 253),
            pod_id TEXT NOT NULL CHECK (char_length(pod_id) BETWEEN 1 AND 1024),
            pod_uid TEXT NOT NULL CHECK (char_length(pod_uid) BETWEEN 1 AND 512),
            controller_uid TEXT NOT NULL
                CHECK (char_length(controller_uid) BETWEEN 1 AND 512),
            root_controller_uid TEXT NOT NULL
                CHECK (char_length(root_controller_uid) BETWEEN 1 AND 512),
            root_controller_kind TEXT NOT NULL
                CHECK (char_length(root_controller_kind) BETWEEN 1 AND 64),
            observed_at TIMESTAMPTZ NOT NULL,
            source_revision TEXT NOT NULL
                CHECK (char_length(source_revision) BETWEEN 1 AND 128),
            evidence_ref TEXT NOT NULL UNIQUE
                CHECK (evidence_ref ~ '^kubernetes-pod-lifecycle:[0-9a-f]{64}$'),
            PRIMARY KEY (cluster_ref, pod_uid)
        );
        CREATE INDEX kubernetes_pod_lifecycle_root_idx
            ON kubernetes_pod_lifecycle_identity (
                cluster_ref, namespace, root_controller_uid, observed_at, pod_uid
            );

        CREATE TRIGGER kubernetes_pod_lifecycle_identity_no_modify
            BEFORE UPDATE ON kubernetes_pod_lifecycle_identity
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_kubernetes_lifecycle_mutation();
        CREATE TRIGGER kubernetes_pod_lifecycle_identity_no_delete
            BEFORE DELETE ON kubernetes_pod_lifecycle_identity
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_kubernetes_lifecycle_mutation();

        GRANT SELECT, INSERT ON TABLE kubernetes_pod_lifecycle_identity TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop Pod controller identities after both collectors stop."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE kubernetes_pod_lifecycle_identity FROM fdai_core;
        DROP TABLE kubernetes_pod_lifecycle_identity;
        """
    )

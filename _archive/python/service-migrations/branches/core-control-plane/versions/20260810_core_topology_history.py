"""Add append-only bitemporal topology revisions owned by Core."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_topology_history_20260810"
down_revision: str | Sequence[str] | None = "core_inventory_peered_links_20260810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "topology_revision_batch",
    "topology_object_revision",
    "topology_link_revision",
)
rollback = {
    "strategy": "drop-rebuildable-topology-history",
    "restores": "core_inventory_peered_links_20260810",
    "requires": "topology-history-writers-stopped",
}


def upgrade() -> None:
    """Create immutable provider-generation, object, link, and tombstone history."""
    op.execute(
        """
        CREATE TABLE topology_revision_batch (
            revision_id TEXT PRIMARY KEY,
            provider_generation_ref TEXT NOT NULL,
            ontology_release_digest TEXT NOT NULL
                CHECK (ontology_release_digest ~ '^sha256:[a-f0-9]{64}$'),
            source_receipt_digest TEXT NOT NULL
                CHECK (source_receipt_digest ~ '^sha256:[a-f0-9]{64}$'),
            effective_at TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            complete_snapshot BOOLEAN NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (char_length(revision_id) BETWEEN 1 AND 256),
            CHECK (char_length(provider_generation_ref) BETWEEN 1 AND 512)
        );
        CREATE INDEX topology_revision_batch_cutoff_idx
            ON topology_revision_batch (effective_at, recorded_at, revision_id);

        CREATE TABLE topology_object_revision (
            revision_id TEXT NOT NULL REFERENCES topology_revision_batch(revision_id),
            object_id TEXT NOT NULL,
            object_type TEXT NOT NULL,
            properties JSONB NOT NULL,
            effective_at TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            deleted BOOLEAN NOT NULL,
            evidence_ref TEXT NOT NULL,
            PRIMARY KEY (revision_id, object_id),
            CHECK (NOT deleted OR properties = '{}'::jsonb),
            CHECK (char_length(object_id) BETWEEN 1 AND 512),
            CHECK (char_length(object_type) BETWEEN 1 AND 256),
            CHECK (char_length(evidence_ref) BETWEEN 1 AND 512)
        );
        CREATE INDEX topology_object_revision_history_idx
            ON topology_object_revision (object_id, effective_at, recorded_at);

        CREATE TABLE topology_link_revision (
            revision_id TEXT NOT NULL REFERENCES topology_revision_batch(revision_id),
            from_id TEXT NOT NULL,
            from_type TEXT NOT NULL,
            link_type TEXT NOT NULL,
            to_id TEXT NOT NULL,
            to_type TEXT NOT NULL,
            properties JSONB NOT NULL,
            effective_at TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            deleted BOOLEAN NOT NULL,
            evidence_ref TEXT NOT NULL,
            PRIMARY KEY (revision_id, from_id, link_type, to_id),
            CHECK (NOT deleted OR properties = '{}'::jsonb),
            CHECK (char_length(from_id) BETWEEN 1 AND 512),
            CHECK (char_length(to_id) BETWEEN 1 AND 512),
            CHECK (char_length(link_type) BETWEEN 1 AND 256),
            CHECK (char_length(evidence_ref) BETWEEN 1 AND 512)
        );
        CREATE INDEX topology_link_revision_history_idx
            ON topology_link_revision (from_id, link_type, to_id, effective_at, recorded_at);

        CREATE FUNCTION fdai_reject_topology_history_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'topology history is append-only';
        END;
        $$;
        CREATE TRIGGER topology_revision_batch_no_modify
            BEFORE UPDATE ON topology_revision_batch
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_topology_history_mutation();
        CREATE TRIGGER topology_revision_batch_no_delete
            BEFORE DELETE ON topology_revision_batch
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_topology_history_mutation();
        CREATE TRIGGER topology_object_revision_no_modify
            BEFORE UPDATE ON topology_object_revision
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_topology_history_mutation();
        CREATE TRIGGER topology_object_revision_no_delete
            BEFORE DELETE ON topology_object_revision
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_topology_history_mutation();
        CREATE TRIGGER topology_link_revision_no_modify
            BEFORE UPDATE ON topology_link_revision
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_topology_history_mutation();
        CREATE TRIGGER topology_link_revision_no_delete
            BEFORE DELETE ON topology_link_revision
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_topology_history_mutation();

        GRANT SELECT, INSERT ON TABLE
            topology_revision_batch,
            topology_object_revision,
            topology_link_revision
        TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop the rebuildable topology history projection in dependency order."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            topology_link_revision,
            topology_object_revision,
            topology_revision_batch
        FROM fdai_core;
        DROP TABLE topology_link_revision;
        DROP TABLE topology_object_revision;
        DROP TABLE topology_revision_batch;
        DROP FUNCTION fdai_reject_topology_history_mutation();
        """
    )

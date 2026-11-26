"""Persist compact per-generation inventory membership for replay and history reads."""

from __future__ import annotations

from alembic import op

revision = "core_inventory_snapshot_membership_20261029"
down_revision = "core_accepted_entitlement_20261021"
branch_labels = None
depends_on = None

migration_owner = "core-control-plane"
owned_tables = (
    "inventory_observation_snapshot_generation",
    "inventory_observation_snapshot_member",
)
rollback = {
    "strategy": "drop-rebuildable-inventory-snapshot-membership",
    "restores": "core_accepted_entitlement_20261021",
    "requires": "snapshot-membership-writers-and-readers-stopped",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE inventory_observation_snapshot_generation (
            generation_id TEXT PRIMARY KEY
                CHECK (char_length(generation_id) BETWEEN 1 AND 512),
            source TEXT NOT NULL CHECK (char_length(source) BETWEEN 1 AND 512),
            observation_kind TEXT NOT NULL
                CHECK (observation_kind IN ('observed', 'expected')),
            scopes JSONB NOT NULL CHECK (jsonb_typeof(scopes) = 'array'),
            resource_types JSONB NOT NULL CHECK (jsonb_typeof(resource_types) = 'array'),
            coverage_scope TEXT,
            semantic_content_digest TEXT NOT NULL
                CHECK (semantic_content_digest ~ '^sha256:[a-f0-9]{64}$'),
            journal_high_watermark BIGINT NOT NULL CHECK (journal_high_watermark >= 0),
            recorded_at TIMESTAMPTZ NOT NULL,
            history_visible BOOLEAN NOT NULL,
            links_complete BOOLEAN NOT NULL
        );
        CREATE TABLE inventory_observation_snapshot_member (
            generation_id TEXT NOT NULL
                REFERENCES inventory_observation_snapshot_generation(generation_id),
            subject_kind TEXT NOT NULL CHECK (subject_kind IN ('object', 'relationship')),
            subject_ref TEXT NOT NULL CHECK (char_length(subject_ref) BETWEEN 1 AND 512),
            subject_type TEXT NOT NULL CHECK (char_length(subject_type) BETWEEN 1 AND 512),
            semantic_digest TEXT NOT NULL
                CHECK (semantic_digest ~ '^sha256:[a-f0-9]{64}$'),
            provider_ref TEXT CHECK (
                provider_ref IS NULL OR char_length(provider_ref) BETWEEN 1 AND 512
            ),
            scope_ref TEXT CHECK (
                scope_ref IS NULL OR char_length(scope_ref) BETWEEN 1 AND 512
            ),
            observed_at TIMESTAMPTZ NOT NULL,
            freshness_properties JSONB NOT NULL
                CHECK (jsonb_typeof(freshness_properties) = 'object'),
            from_id TEXT,
            from_type TEXT,
            link_type TEXT,
            to_id TEXT,
            to_type TEXT,
            PRIMARY KEY (generation_id, subject_kind, subject_ref),
            CHECK (
                (subject_kind = 'object'
                    AND from_id IS NULL AND from_type IS NULL AND link_type IS NULL
                    AND to_id IS NULL AND to_type IS NULL)
                OR
                (subject_kind = 'relationship'
                    AND from_id IS NOT NULL AND from_type IS NOT NULL
                    AND link_type IS NOT NULL AND to_id IS NOT NULL AND to_type IS NOT NULL)
            )
        );
        CREATE INDEX inventory_observation_snapshot_member_history_idx
            ON inventory_observation_snapshot_member
                (subject_kind, subject_ref, generation_id);
        CREATE INDEX inventory_observation_snapshot_journal_lookup_idx
            ON inventory_observation_journal (subject_kind, subject_ref, watermark DESC)
            WHERE source_identity='inventory.reconciliation'
                AND observation_kind='full' AND mutation_kind='upsert';
        CREATE FUNCTION fdai_reject_inventory_snapshot_membership_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'inventory snapshot membership is append-only';
        END;
        $$;
        CREATE TRIGGER inventory_observation_snapshot_generation_no_update
            BEFORE UPDATE ON inventory_observation_snapshot_generation
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_inventory_snapshot_membership_mutation();
        CREATE TRIGGER inventory_observation_snapshot_generation_no_delete
            BEFORE DELETE ON inventory_observation_snapshot_generation
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_inventory_snapshot_membership_mutation();
        CREATE TRIGGER inventory_observation_snapshot_member_no_update
            BEFORE UPDATE ON inventory_observation_snapshot_member
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_inventory_snapshot_membership_mutation();
        CREATE TRIGGER inventory_observation_snapshot_member_no_delete
            BEFORE DELETE ON inventory_observation_snapshot_member
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_inventory_snapshot_membership_mutation();
        REVOKE ALL PRIVILEGES ON TABLE inventory_observation_snapshot_generation FROM PUBLIC;
        REVOKE ALL PRIVILEGES ON TABLE inventory_observation_snapshot_member FROM PUBLIC;
        GRANT SELECT, INSERT ON TABLE inventory_observation_snapshot_generation TO fdai_core;
        GRANT SELECT, INSERT ON TABLE inventory_observation_snapshot_member TO fdai_core;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM inventory_observation_snapshot_generation)
               OR EXISTS (SELECT 1 FROM inventory_observation_snapshot_member) THEN
                RAISE EXCEPTION
                    'retained inventory snapshot membership blocks schema rollback';
            END IF;
        END;
        $$;
        DROP INDEX inventory_observation_snapshot_journal_lookup_idx;
        DROP INDEX inventory_observation_snapshot_member_history_idx;
        DROP TABLE inventory_observation_snapshot_member;
        DROP TABLE inventory_observation_snapshot_generation;
        DROP FUNCTION fdai_reject_inventory_snapshot_membership_mutation();
        """
    )

"""Add the Core-owned normalized inventory observation journal."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_inventory_observation_journal_20260905"
down_revision: str | Sequence[str] | None = "core_operational_state_transitions_20260902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "inventory_observation_journal",
    "inventory_observation_pending_tombstone",
)
rollback = {
    "strategy": "drop-rebuildable-inventory-observation-journal",
    "restores": "core_operational_state_transitions_20260902",
    "requires": "inventory-observation-writers-stopped",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE inventory_observation_journal (
            watermark BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            observation_id TEXT NOT NULL UNIQUE
                CHECK (observation_id ~ '^sha256:[a-f0-9]{64}$'),
            content_digest TEXT NOT NULL
                CHECK (content_digest ~ '^sha256:[a-f0-9]{64}$'),
            schema_version TEXT NOT NULL CHECK (schema_version = '1.0.0'),
            idempotency_key TEXT NOT NULL
                CHECK (char_length(idempotency_key) BETWEEN 1 AND 512),
            subject_kind TEXT NOT NULL CHECK (subject_kind IN ('object', 'relationship')),
            observation_kind TEXT NOT NULL
                CHECK (observation_kind IN ('full', 'partial', 'change_hint', 'tombstone')),
            mutation_kind TEXT NOT NULL CHECK (mutation_kind IN ('upsert', 'delete')),
            subject_ref TEXT NOT NULL CHECK (char_length(subject_ref) BETWEEN 1 AND 512),
            subject_type TEXT NOT NULL CHECK (char_length(subject_type) BETWEEN 1 AND 512),
            properties JSONB NOT NULL CHECK (jsonb_typeof(properties) = 'object'),
            property_mask TEXT[] NOT NULL DEFAULT '{}'
                CHECK (fdai_text_array_elements_bounded(property_mask, 256, 128)),
            properties_complete BOOLEAN NOT NULL,
            links_complete BOOLEAN NOT NULL,
            tombstone_confirmed BOOLEAN NOT NULL,
            provider_ref TEXT CHECK (
                provider_ref IS NULL OR char_length(provider_ref) BETWEEN 1 AND 512
            ),
            scope_ref TEXT CHECK (
                scope_ref IS NULL OR char_length(scope_ref) BETWEEN 1 AND 512
            ),
            operation TEXT CHECK (
                operation IS NULL OR char_length(operation) BETWEEN 1 AND 512
            ),
            operation_status TEXT CHECK (
                operation_status IS NULL OR char_length(operation_status) BETWEEN 1 AND 512
            ),
            source_identity TEXT NOT NULL
                CHECK (char_length(source_identity) BETWEEN 1 AND 512),
            source_event_id TEXT NOT NULL
                CHECK (char_length(source_event_id) BETWEEN 1 AND 512),
            source_revision TEXT NOT NULL
                CHECK (char_length(source_revision) BETWEEN 1 AND 512),
            effective_at TIMESTAMPTZ NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            evidence_cutoff TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            from_id TEXT,
            from_type TEXT,
            link_type TEXT,
            to_id TEXT,
            to_type TEXT,
            projection_mode TEXT NOT NULL DEFAULT 'shadow'
                CHECK (projection_mode = 'shadow'),
            UNIQUE (idempotency_key, subject_kind, subject_ref),
            CHECK (effective_at <= evidence_cutoff),
            CHECK (
                (subject_kind = 'object'
                    AND from_id IS NULL AND from_type IS NULL AND link_type IS NULL
                    AND to_id IS NULL AND to_type IS NULL)
                OR
                (subject_kind = 'relationship'
                    AND from_id IS NOT NULL AND from_type IS NOT NULL
                    AND link_type IS NOT NULL AND to_id IS NOT NULL AND to_type IS NOT NULL)
            ),
            CHECK (
                (observation_kind = 'full' AND mutation_kind = 'upsert'
                    AND properties_complete AND NOT tombstone_confirmed)
                OR
                (observation_kind IN ('partial', 'change_hint')
                    AND mutation_kind = 'upsert'
                    AND NOT properties_complete AND NOT tombstone_confirmed)
                OR
                (observation_kind = 'tombstone' AND mutation_kind = 'delete'
                    AND NOT properties_complete AND properties = '{}'::jsonb
                    AND cardinality(property_mask) = 0)
            )
        );
        CREATE INDEX inventory_observation_subject_history_idx
            ON inventory_observation_journal (
                subject_kind, subject_ref, effective_at, source_event_id, content_digest
            );
        CREATE TABLE inventory_observation_pending_tombstone (
            resource_id TEXT PRIMARY KEY CHECK (char_length(resource_id) BETWEEN 1 AND 512),
            resource_type TEXT NOT NULL CHECK (char_length(resource_type) BETWEEN 1 AND 512),
            scope_ref TEXT CHECK (
                scope_ref IS NULL OR char_length(scope_ref) BETWEEN 1 AND 512
            ),
            observation_id TEXT NOT NULL UNIQUE
                REFERENCES inventory_observation_journal(observation_id),
            observed_at TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL
        );
        CREATE FUNCTION fdai_reject_inventory_observation_journal_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'inventory observation journal is append-only';
        END;
        $$;
        CREATE TRIGGER inventory_observation_journal_no_modify
            BEFORE UPDATE ON inventory_observation_journal
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_inventory_observation_journal_mutation();
        CREATE TRIGGER inventory_observation_journal_no_delete
            BEFORE DELETE ON inventory_observation_journal
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_inventory_observation_journal_mutation();
        GRANT SELECT, INSERT ON TABLE inventory_observation_journal TO fdai_core;
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON TABLE inventory_observation_pending_tombstone TO fdai_core;
        GRANT USAGE, SELECT
            ON SEQUENCE inventory_observation_journal_watermark_seq TO fdai_core;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE ALL PRIVILEGES
            ON SEQUENCE inventory_observation_journal_watermark_seq FROM fdai_core;
        REVOKE ALL PRIVILEGES
            ON TABLE inventory_observation_pending_tombstone FROM fdai_core;
        REVOKE ALL PRIVILEGES ON TABLE inventory_observation_journal FROM fdai_core;
        DROP TABLE inventory_observation_pending_tombstone;
        DROP TABLE inventory_observation_journal;
        DROP FUNCTION fdai_reject_inventory_observation_journal_mutation();
        """
    )

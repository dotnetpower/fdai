"""Add Core-owned append-only operational state transitions."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_operational_state_transitions_20260902"
down_revision: str | Sequence[str] | None = "core_t2_cache_lifecycle_20260831"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "operational_state_transition_batch",
    "operational_state_transition",
    "operational_state_transition_coverage",
)
rollback = {
    "strategy": "drop-rebuildable-operational-transition-history",
    "restores": "core_t2_cache_lifecycle_20260831",
    "requires": "operational-transition-writers-stopped",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION fdai_text_array_elements_bounded(
            values_to_check TEXT[],
            max_items INTEGER,
            max_length INTEGER
        )
        RETURNS BOOLEAN LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT cardinality(values_to_check) <= max_items
               AND NOT EXISTS (
                   SELECT 1
                     FROM unnest(values_to_check) AS item
                    WHERE item IS NULL
                       OR char_length(item) NOT BETWEEN 1 AND max_length
               )
        $$;
        CREATE TABLE operational_state_transition_batch (
            batch_id TEXT PRIMARY KEY CHECK (batch_id ~ '^sha256:[a-f0-9]{64}$'),
            recorded_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE operational_state_transition (
            transition_id TEXT PRIMARY KEY CHECK (transition_id ~ '^sha256:[a-f0-9]{64}$'),
            batch_id TEXT NOT NULL REFERENCES operational_state_transition_batch(batch_id),
            idempotency_key TEXT NOT NULL UNIQUE
                CHECK (char_length(idempotency_key) BETWEEN 1 AND 512),
            subject_ref TEXT NOT NULL CHECK (char_length(subject_ref) BETWEEN 1 AND 512),
            subject_type TEXT NOT NULL CHECK (char_length(subject_type) BETWEEN 1 AND 512),
            state_type TEXT NOT NULL CHECK (char_length(state_type) BETWEEN 1 AND 512),
            from_state TEXT NOT NULL CHECK (char_length(from_state) BETWEEN 1 AND 512),
            to_state TEXT NOT NULL CHECK (char_length(to_state) BETWEEN 1 AND 512),
            lane TEXT NOT NULL CHECK (lane IN ('observed', 'derived')),
            authority TEXT NOT NULL CHECK (
                authority IN ('provider', 'telemetry', 'deterministic_function')
            ),
            effective_at TIMESTAMPTZ NOT NULL,
            evidence_cutoff TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            source_identity TEXT NOT NULL
                CHECK (char_length(source_identity) BETWEEN 1 AND 512),
            source_revision TEXT NOT NULL
                CHECK (char_length(source_revision) BETWEEN 1 AND 512),
            producer_id TEXT NOT NULL CHECK (char_length(producer_id) BETWEEN 1 AND 512),
            producer_version TEXT NOT NULL
                CHECK (char_length(producer_version) BETWEEN 1 AND 512),
            freshness_ceiling_seconds INTEGER NOT NULL,
            completeness_basis_points INTEGER NOT NULL,
            evidence_refs TEXT[] NOT NULL
                CHECK (
                    cardinality(evidence_refs) >= 1
                    AND fdai_text_array_elements_bounded(evidence_refs, 64, 512)
                ),
            conflicts TEXT[] NOT NULL DEFAULT '{}'
                CHECK (fdai_text_array_elements_bounded(conflicts, 64, 512)),
            correlation_refs TEXT[] NOT NULL DEFAULT '{}'
                CHECK (fdai_text_array_elements_bounded(correlation_refs, 64, 512)),
            synthetic BOOLEAN NOT NULL,
            execution_authority BOOLEAN NOT NULL DEFAULT FALSE CHECK (NOT execution_authority),
            CHECK (from_state <> to_state),
            CHECK (effective_at <= evidence_cutoff AND evidence_cutoff <= recorded_at),
            CHECK (freshness_ceiling_seconds BETWEEN 1 AND 31536000),
            CHECK (completeness_basis_points BETWEEN 0 AND 10000)
        );
        CREATE INDEX operational_state_transition_history_idx
            ON operational_state_transition (
                subject_ref, state_type, effective_at, recorded_at, transition_id
            );
        CREATE TABLE operational_state_transition_coverage (
            coverage_id TEXT PRIMARY KEY CHECK (coverage_id ~ '^sha256:[a-f0-9]{64}$'),
            batch_id TEXT NOT NULL REFERENCES operational_state_transition_batch(batch_id),
            subject_ref TEXT NOT NULL CHECK (char_length(subject_ref) BETWEEN 1 AND 512),
            state_type TEXT NOT NULL CHECK (char_length(state_type) BETWEEN 1 AND 512),
            coverage_start_at TIMESTAMPTZ NOT NULL,
            coverage_end_at TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            source_identity TEXT NOT NULL
                CHECK (char_length(source_identity) BETWEEN 1 AND 512),
            source_revision TEXT NOT NULL
                CHECK (char_length(source_revision) BETWEEN 1 AND 512),
            watermark TEXT NOT NULL CHECK (char_length(watermark) BETWEEN 1 AND 512),
            evidence_ref TEXT NOT NULL CHECK (char_length(evidence_ref) BETWEEN 1 AND 512),
            complete BOOLEAN NOT NULL,
            limitation TEXT
                CHECK (limitation IS NULL OR char_length(limitation) BETWEEN 1 AND 128),
            synthetic BOOLEAN NOT NULL,
            CHECK (coverage_start_at <= coverage_end_at AND coverage_end_at <= recorded_at),
            CHECK (complete = (limitation IS NULL))
        );
        CREATE INDEX operational_state_transition_coverage_idx
            ON operational_state_transition_coverage (
                subject_ref, state_type, coverage_start_at, coverage_end_at, recorded_at
            );
        CREATE FUNCTION fdai_reject_operational_state_transition_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'operational state transition history is append-only';
        END;
        $$;
        CREATE TRIGGER operational_state_transition_batch_no_modify
            BEFORE UPDATE ON operational_state_transition_batch
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_state_transition_mutation();
        CREATE TRIGGER operational_state_transition_batch_no_delete
            BEFORE DELETE ON operational_state_transition_batch
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_state_transition_mutation();
        CREATE TRIGGER operational_state_transition_no_modify
            BEFORE UPDATE ON operational_state_transition
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_state_transition_mutation();
        CREATE TRIGGER operational_state_transition_no_delete
            BEFORE DELETE ON operational_state_transition
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_state_transition_mutation();
        CREATE TRIGGER operational_state_transition_coverage_no_modify
            BEFORE UPDATE ON operational_state_transition_coverage
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_state_transition_mutation();
        CREATE TRIGGER operational_state_transition_coverage_no_delete
            BEFORE DELETE ON operational_state_transition_coverage
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_state_transition_mutation();
        """
    )
    op.execute(
        """
        GRANT SELECT, INSERT ON TABLE
            operational_state_transition_batch,
            operational_state_transition,
            operational_state_transition_coverage
        TO fdai_core;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            operational_state_transition_coverage,
            operational_state_transition,
            operational_state_transition_batch
        FROM fdai_core;
        DROP TABLE operational_state_transition_coverage;
        DROP TABLE operational_state_transition;
        DROP TABLE operational_state_transition_batch;
        DROP FUNCTION fdai_reject_operational_state_transition_mutation();
        DROP FUNCTION fdai_text_array_elements_bounded(TEXT[], INTEGER, INTEGER);
        """
    )

"""Add append-only operational-history archive lifecycle evidence."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_operational_archive_20260822"
down_revision: str | Sequence[str] | None = "core_question_assurance_20260820"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "operational_archive_manifest",
    "operational_archive_coverage_receipt",
    "operational_archive_verification_receipt",
    "operational_archive_restore_receipt",
    "operational_retention_hold_event",
    "operational_archive_purge_receipt",
)
rollback = {
    "strategy": "drop-rebuildable-operational-archive-ledgers",
    "restores": "core_question_assurance_20260820",
    "requires": "archive-writers-and-purge-workers-stopped",
}


def upgrade() -> None:
    """Create immutable archive manifests, gates, holds, and purge receipts."""

    op.execute(
        """
        CREATE TABLE operational_archive_manifest (
            manifest_digest TEXT PRIMARY KEY
                CHECK (manifest_digest ~ '^sha256:[0-9a-f]{64}$'),
            archive_content_digest TEXT NOT NULL
                CHECK (archive_content_digest ~ '^sha256:[0-9a-f]{64}$'),
            covered_start TIMESTAMPTZ NOT NULL,
            covered_end TIMESTAMPTZ NOT NULL,
            object_count BIGINT NOT NULL CHECK (object_count >= 0),
            relationship_count BIGINT NOT NULL CHECK (relationship_count >= 0),
            coverage_complete BOOLEAN NOT NULL,
            record JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            CHECK (covered_end > covered_start),
            CHECK (jsonb_typeof(record) = 'object')
        );
        CREATE INDEX operational_archive_manifest_coverage_idx
            ON operational_archive_manifest (covered_start, covered_end, manifest_digest);

        CREATE TABLE operational_archive_coverage_receipt (
            receipt_digest TEXT PRIMARY KEY
                CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            coverage_start TIMESTAMPTZ NOT NULL,
            coverage_end TIMESTAMPTZ NOT NULL,
            complete BOOLEAN NOT NULL,
            manifest_digests JSONB NOT NULL,
            record JSONB NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            CHECK (coverage_end > coverage_start),
            CHECK (jsonb_typeof(manifest_digests) = 'array'),
            CHECK (jsonb_typeof(record) = 'object')
        );
        CREATE INDEX operational_archive_coverage_time_idx
            ON operational_archive_coverage_receipt (
                coverage_start, coverage_end, recorded_at
            );

        CREATE TABLE operational_archive_verification_receipt (
            receipt_digest TEXT PRIMARY KEY
                CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            manifest_digest TEXT NOT NULL
                REFERENCES operational_archive_manifest(manifest_digest),
            verified BOOLEAN NOT NULL,
            reason_codes JSONB NOT NULL,
            record JSONB NOT NULL,
            verified_at TIMESTAMPTZ NOT NULL,
            CHECK (jsonb_typeof(reason_codes) = 'array'),
            CHECK (jsonb_typeof(record) = 'object')
        );
        CREATE INDEX operational_archive_verification_manifest_idx
            ON operational_archive_verification_receipt (manifest_digest, verified_at);

        CREATE TABLE operational_archive_restore_receipt (
            receipt_digest TEXT PRIMARY KEY
                CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            manifest_digest TEXT NOT NULL
                REFERENCES operational_archive_manifest(manifest_digest),
            verification_receipt_digest TEXT NOT NULL
                REFERENCES operational_archive_verification_receipt(receipt_digest),
            passed BOOLEAN NOT NULL,
            reason_codes JSONB NOT NULL,
            record JSONB NOT NULL,
            sampled_at TIMESTAMPTZ NOT NULL,
            CHECK (jsonb_typeof(reason_codes) = 'array'),
            CHECK (jsonb_typeof(record) = 'object')
        );
        CREATE INDEX operational_archive_restore_manifest_idx
            ON operational_archive_restore_receipt (manifest_digest, sampled_at);

        CREATE TABLE operational_retention_hold_event (
            event_digest TEXT PRIMARY KEY
                CHECK (event_digest ~ '^sha256:[0-9a-f]{64}$'),
            hold_id TEXT NOT NULL CHECK (char_length(hold_id) BETWEEN 1 AND 256),
            manifest_digest TEXT NOT NULL
                REFERENCES operational_archive_manifest(manifest_digest),
            event_type TEXT NOT NULL CHECK (event_type IN ('placed', 'released')),
            hold_kind TEXT NOT NULL CHECK (hold_kind IN ('retention', 'legal')),
            starts_at TIMESTAMPTZ NOT NULL,
            ends_at TIMESTAMPTZ NULL,
            record JSONB NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            CHECK (ends_at IS NULL OR ends_at > starts_at),
            CHECK (hold_kind <> 'legal' OR ends_at IS NULL),
            CHECK (jsonb_typeof(record) = 'object')
        );
        CREATE INDEX operational_retention_hold_manifest_idx
            ON operational_retention_hold_event (manifest_digest, hold_id, recorded_at);

        CREATE TABLE operational_archive_purge_receipt (
            receipt_digest TEXT PRIMARY KEY
                CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            idempotency_key TEXT NOT NULL
                CHECK (char_length(idempotency_key) BETWEEN 1 AND 256),
            attempt INTEGER NOT NULL CHECK (attempt >= 1),
            manifest_digest TEXT NOT NULL
                REFERENCES operational_archive_manifest(manifest_digest),
            status TEXT NOT NULL CHECK (
                status IN ('blocked', 'pending', 'succeeded', 'failed', 'duplicate')
            ),
            reason_codes JSONB NOT NULL,
            source_data_preserved BOOLEAN NOT NULL,
            storage_pressure BOOLEAN NOT NULL,
            record JSONB NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            UNIQUE (idempotency_key, attempt, status),
            CHECK (jsonb_typeof(reason_codes) = 'array'),
            CHECK (jsonb_typeof(record) = 'object'),
            CHECK (
                (status IN ('succeeded', 'duplicate')) <> source_data_preserved
            ),
            CHECK (NOT storage_pressure OR status IN ('blocked', 'failed'))
        );
        CREATE INDEX operational_archive_purge_latest_idx
            ON operational_archive_purge_receipt (
                idempotency_key, recorded_at DESC, receipt_digest DESC
            );

        CREATE FUNCTION fdai_reject_operational_archive_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'operational archive evidence is append-only';
        END;
        $$;
        CREATE TRIGGER operational_archive_manifest_no_modify
            BEFORE UPDATE ON operational_archive_manifest
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_archive_mutation();
        CREATE TRIGGER operational_archive_manifest_no_delete
            BEFORE DELETE ON operational_archive_manifest
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_archive_mutation();
        CREATE TRIGGER operational_archive_verification_no_modify
            BEFORE UPDATE ON operational_archive_verification_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_archive_mutation();
        CREATE TRIGGER operational_archive_coverage_no_modify
            BEFORE UPDATE ON operational_archive_coverage_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_archive_mutation();
        CREATE TRIGGER operational_archive_coverage_no_delete
            BEFORE DELETE ON operational_archive_coverage_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_archive_mutation();
        CREATE TRIGGER operational_archive_verification_no_delete
            BEFORE DELETE ON operational_archive_verification_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_archive_mutation();
        CREATE TRIGGER operational_archive_restore_no_modify
            BEFORE UPDATE ON operational_archive_restore_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_archive_mutation();
        CREATE TRIGGER operational_archive_restore_no_delete
            BEFORE DELETE ON operational_archive_restore_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_archive_mutation();
        CREATE TRIGGER operational_retention_hold_no_modify
            BEFORE UPDATE ON operational_retention_hold_event
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_archive_mutation();
        CREATE TRIGGER operational_retention_hold_no_delete
            BEFORE DELETE ON operational_retention_hold_event
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_archive_mutation();
        CREATE TRIGGER operational_archive_purge_no_modify
            BEFORE UPDATE ON operational_archive_purge_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_archive_mutation();
        CREATE TRIGGER operational_archive_purge_no_delete
            BEFORE DELETE ON operational_archive_purge_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_reject_operational_archive_mutation();

        GRANT SELECT, INSERT ON TABLE
            operational_archive_manifest,
            operational_archive_coverage_receipt,
            operational_archive_verification_receipt,
            operational_archive_restore_receipt,
            operational_retention_hold_event,
            operational_archive_purge_receipt
        TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop archive lifecycle evidence after all writers and purgers stop."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            operational_archive_purge_receipt,
            operational_retention_hold_event,
            operational_archive_restore_receipt,
            operational_archive_verification_receipt,
            operational_archive_coverage_receipt,
            operational_archive_manifest
        FROM fdai_core;
        DROP TABLE operational_archive_purge_receipt;
        DROP TABLE operational_retention_hold_event;
        DROP TABLE operational_archive_restore_receipt;
        DROP TABLE operational_archive_verification_receipt;
        DROP TABLE operational_archive_coverage_receipt;
        DROP TABLE operational_archive_manifest;
        DROP FUNCTION fdai_reject_operational_archive_mutation();
        """
    )

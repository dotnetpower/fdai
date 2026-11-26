"""relational case-history lifecycle, revisions, and chunk lineage

Revision ID: 20260723_0054
Revises: 20260723_0053
Create Date: 2026-07-23 15:10:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260723_0054"
down_revision: str | None = "20260723_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute(
        """
        CREATE TABLE case_history (
            case_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            purpose TEXT NOT NULL,
            access_scope_digest TEXT NOT NULL CHECK (
                access_scope_digest ~ '^[0-9a-f]{64}$'
            ),
            latest_revision INTEGER NOT NULL CHECK (latest_revision >= 1),
            latest_manifest_digest TEXT NOT NULL CHECK (
                latest_manifest_digest ~ '^[0-9a-f]{64}$'
            ),
            state_revision INTEGER NOT NULL CHECK (state_revision >= latest_revision),
            detector_id TEXT NOT NULL,
            detector_version TEXT NOT NULL,
            metric TEXT NOT NULL,
            outcome_label TEXT NOT NULL,
            retention_until TIMESTAMPTZ NOT NULL,
            deletion_due_at TIMESTAMPTZ NOT NULL,
            legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
            legal_hold_ref TEXT,
            deletion_started_at TIMESTAMPTZ,
            deletion_storage_refs TEXT[] NOT NULL DEFAULT '{}',
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CHECK (retention_until <= deletion_due_at),
            CHECK (legal_hold = (legal_hold_ref IS NOT NULL)),
            CONSTRAINT ck_case_history_safe_deletion_refs CHECK (
                (deletion_started_at IS NULL AND cardinality(deletion_storage_refs) = 0)
                OR (deletion_started_at IS NOT NULL
                    AND deleted_at IS NULL
                    AND cardinality(deletion_storage_refs) > 0
                    AND array_position(deletion_storage_refs, '') IS NULL
                    AND array_to_string(deletion_storage_refs, ',') ~
                        '^case-history/[A-Za-z0-9._/-]+(,case-history/[A-Za-z0-9._/-]+)*$')
                OR (deletion_started_at IS NOT NULL
                    AND deleted_at IS NOT NULL
                    AND cardinality(deletion_storage_refs) = 0)
            ),
            CHECK (deleted_at IS NULL OR deleted_at >= deletion_due_at)
        );

        CREATE TABLE case_history_revision (
            case_id TEXT NOT NULL REFERENCES case_history(case_id),
            revision INTEGER NOT NULL CHECK (revision >= 1),
            manifest_digest TEXT NOT NULL CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
            parent_manifest_digest TEXT CHECK (
                parent_manifest_digest IS NULL OR parent_manifest_digest ~ '^[0-9a-f]{64}$'
            ),
            source_set_digest TEXT NOT NULL CHECK (source_set_digest ~ '^[0-9a-f]{64}$'),
            storage_ref TEXT NOT NULL,
            artifact_size BIGINT NOT NULL CHECK (artifact_size > 0),
            outcome_label TEXT NOT NULL,
            detector_id TEXT NOT NULL,
            detector_version TEXT NOT NULL,
            metric TEXT NOT NULL,
            event_time_cutoff TIMESTAMPTZ NOT NULL,
            created_by_agent TEXT NOT NULL,
            sealed_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (case_id, revision),
            UNIQUE (manifest_digest),
            UNIQUE (case_id, source_set_digest),
            CHECK (
                (revision = 1 AND parent_manifest_digest IS NULL)
                OR (revision > 1 AND parent_manifest_digest IS NOT NULL)
            )
        );
        CREATE INDEX ix_case_history_revision_sealed
            ON case_history_revision (sealed_at DESC, case_id, revision DESC);

        CREATE TABLE case_history_chunk (
            chunk_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            chunk_kind TEXT NOT NULL,
            text TEXT NOT NULL CHECK (octet_length(text) BETWEEN 1 AND 16384),
            embedding vector(384),
            embedding_model_version TEXT,
            source_manifest_digest TEXT NOT NULL CHECK (
                source_manifest_digest ~ '^[0-9a-f]{64}$'
            ),
            access_scope_digest TEXT NOT NULL CHECK (
                access_scope_digest ~ '^[0-9a-f]{64}$'
            ),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ,
            FOREIGN KEY (case_id, revision)
                REFERENCES case_history_revision(case_id, revision),
            UNIQUE (case_id, revision, ordinal),
            CHECK ((embedding IS NULL) = (embedding_model_version IS NULL))
        );
        CREATE INDEX ix_case_history_chunk_scope_manifest
            ON case_history_chunk (access_scope_digest, source_manifest_digest)
            WHERE deleted_at IS NULL;

        CREATE INDEX ix_case_history_closed_cohort
            ON case_history (
                access_scope_digest, purpose, detector_id, metric, outcome_label,
                updated_at DESC, case_id
            ) WHERE deleted_at IS NULL AND deletion_started_at IS NULL;
        CREATE INDEX ix_case_history_due
            ON case_history (deletion_due_at, case_id)
            WHERE deleted_at IS NULL AND legal_hold = FALSE;

        CREATE TABLE case_history_migration_state (
            singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
            status TEXT NOT NULL CHECK (status IN ('pending', 'verified')),
            mismatch_count BIGINT NOT NULL DEFAULT 0 CHECK (mismatch_count >= 0),
            verified_at TIMESTAMPTZ,
            CHECK (
                (status = 'pending' AND verified_at IS NULL)
                OR (status = 'verified' AND mismatch_count = 0 AND verified_at IS NOT NULL)
            )
        );
        INSERT INTO case_history_migration_state (singleton, status)
        VALUES (TRUE, 'pending');
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS case_history_migration_state;")
    op.execute("DROP TABLE IF EXISTS case_history_chunk;")
    op.execute("DROP TABLE IF EXISTS case_history_revision;")
    op.execute("DROP TABLE IF EXISTS case_history;")

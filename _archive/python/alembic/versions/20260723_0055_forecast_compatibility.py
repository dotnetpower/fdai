"""converge previously applied forecast and case-history draft schemas

Revision ID: 20260723_0055
Revises: 20260723_0054
Create Date: 2026-07-23 16:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260723_0055"
down_revision: str | None = "20260723_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.forecast_publication_outbox') IS NULL
               AND to_regclass('public.forecast_outcome_outbox') IS NOT NULL THEN
                ALTER TABLE forecast_outcome_outbox RENAME TO forecast_publication_outbox;
            END IF;
        END $$;

        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'forecast_publication_outbox'
                  AND column_name = 'outcome_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'forecast_publication_outbox'
                  AND column_name = 'publication_id'
            ) THEN
                ALTER TABLE forecast_publication_outbox
                    RENAME COLUMN outcome_id TO publication_id;
            END IF;
        END $$;

        ALTER TABLE forecast_publication_outbox
            ADD COLUMN IF NOT EXISTS topic TEXT,
            ADD COLUMN IF NOT EXISTS dead_lettered_at TIMESTAMPTZ;
        UPDATE forecast_publication_outbox
           SET topic = 'object.forecast-outcome'
         WHERE topic IS NULL;
        ALTER TABLE forecast_publication_outbox
            ALTER COLUMN topic SET NOT NULL,
            ALTER COLUMN created_at SET DEFAULT now();
        ALTER TABLE forecast_publication_outbox
            DROP CONSTRAINT IF EXISTS forecast_outcome_outbox_episode_id_key;

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'forecast_publication_outbox'::regclass
                  AND contype = 'u'
                  AND pg_get_constraintdef(oid) = 'UNIQUE (episode_id, topic)'
            ) THEN
                ALTER TABLE forecast_publication_outbox
                    ADD CONSTRAINT uq_forecast_publication_episode_topic
                    UNIQUE (episode_id, topic);
            END IF;
        END $$;

        DROP INDEX IF EXISTS ix_forecast_outcome_outbox_pending;
        CREATE INDEX IF NOT EXISTS ix_forecast_publication_outbox_pending
            ON forecast_publication_outbox (available_at, publication_id)
            WHERE published_at IS NULL AND dead_lettered_at IS NULL;

        CREATE TABLE IF NOT EXISTS case_history_migration_state (
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
        VALUES (TRUE, 'pending') ON CONFLICT (singleton) DO NOTHING;

        ALTER TABLE forecast_episode
            DROP CONSTRAINT IF EXISTS ck_forecast_episode_nonempty_evidence,
            ADD CONSTRAINT ck_forecast_episode_nonempty_evidence
            CHECK (cardinality(evidence_refs) > 0 AND array_position(evidence_refs, '') IS NULL);

        DO $$
        DECLARE constraint_name TEXT;
        BEGIN
            FOR constraint_name IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'case_history'::regclass
                  AND contype = 'c'
                  AND pg_get_constraintdef(oid) LIKE '%deletion_storage_refs%'
                  AND pg_get_constraintdef(oid) LIKE '%deletion_started_at%'
            LOOP
                EXECUTE format(
                    'ALTER TABLE case_history DROP CONSTRAINT %I', constraint_name
                );
            END LOOP;
        END $$;
        ALTER TABLE case_history
            ADD CONSTRAINT ck_case_history_safe_deletion_refs CHECK (
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
            );
        """
    )


def downgrade() -> None:
    # Compatibility changes converge old-applied and fresh schemas. Earlier
    # downgrades own table removal and work with the converged names.
    pass

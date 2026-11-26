"""T2 cache TTL, exact partitions, catalog state, and atomic receipts.

Revision ID: 20260831_0089
Revises: 20260829_0088
Create Date: 2026-08-31 02:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260831_0089"
down_revision: str | None = "20260829_0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE t2_cache
            ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
        UPDATE t2_cache
           SET expires_at = created_at + INTERVAL '24 hours'
         WHERE expires_at IS NULL;
        ALTER TABLE t2_cache
            ALTER COLUMN expires_at SET NOT NULL,
            ALTER COLUMN expires_at DROP DEFAULT;

        DROP INDEX IF EXISTS idx_t2_cache_input_hash;
        DROP INDEX IF EXISTS idx_t2_cache_expires_at;
        CREATE INDEX IF NOT EXISTS idx_t2_cache_lookup
            ON t2_cache (catalog_version, input_hash, expires_at DESC, created_at DESC);

        ALTER TABLE t2_cache DETACH PARTITION t2_cache_default;
        ALTER TABLE t2_cache_default RENAME TO t2_cache_legacy_default;

        CREATE TABLE t2_cache_partition_registry (
            catalog_version TEXT PRIMARY KEY CHECK (
                catalog_version ~ '^sha256:[a-f0-9]{64}$'
            ),
            partition_name TEXT NOT NULL UNIQUE CHECK (
                partition_name ~ '^t2_cache_p_[a-f0-9]{24}$'
            ),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE t2_cache_catalog_state (
            singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
            active_catalog_version TEXT NOT NULL CHECK (
                active_catalog_version ~ '^sha256:[a-f0-9]{64}$'
            ),
            rollback_catalog_version TEXT CHECK (
                rollback_catalog_version IS NULL
                OR rollback_catalog_version ~ '^sha256:[a-f0-9]{64}$'
            ),
            revision BIGINT NOT NULL CHECK (revision >= 1),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (
                rollback_catalog_version IS NULL
                OR rollback_catalog_version <> active_catalog_version
            )
        );

        CREATE TABLE t2_cache_catalog_transition (
            idempotency_key TEXT PRIMARY KEY CHECK (char_length(idempotency_key) <= 256),
            transition_kind TEXT NOT NULL CHECK (
                transition_kind IN ('promote', 'rollback')
            ),
            requested_catalog_version TEXT CHECK (
                requested_catalog_version IS NULL
                OR requested_catalog_version ~ '^sha256:[a-f0-9]{64}$'
            ),
            previous_active_catalog_version TEXT CHECK (
                previous_active_catalog_version IS NULL
                OR previous_active_catalog_version ~ '^sha256:[a-f0-9]{64}$'
            ),
            active_catalog_version TEXT NOT NULL CHECK (
                active_catalog_version ~ '^sha256:[a-f0-9]{64}$'
            ),
            rollback_catalog_version TEXT CHECK (
                rollback_catalog_version IS NULL
                OR rollback_catalog_version ~ '^sha256:[a-f0-9]{64}$'
            ),
            state_revision BIGINT NOT NULL CHECK (state_revision >= 1),
            receipt_digest TEXT NOT NULL UNIQUE CHECK (
                receipt_digest ~ '^sha256:[a-f0-9]{64}$'
            ),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE t2_cache_rotation_receipt (
            idempotency_key TEXT PRIMARY KEY CHECK (char_length(idempotency_key) <= 256),
            active_catalog_version TEXT NOT NULL CHECK (
                active_catalog_version ~ '^sha256:[a-f0-9]{64}$'
            ),
            rollback_catalog_version TEXT NOT NULL CHECK (
                rollback_catalog_version ~ '^sha256:[a-f0-9]{64}$'
            ),
            cutoff TIMESTAMPTZ NOT NULL,
            dropped_catalog_versions TEXT[] NOT NULL DEFAULT '{}',
            receipt_digest TEXT NOT NULL UNIQUE CHECK (
                receipt_digest ~ '^sha256:[a-f0-9]{64}$'
            ),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE FUNCTION fdai_t2_cache_create_partition(requested_catalog_version TEXT)
        RETURNS TEXT
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            expected_partition_name TEXT;
            registered_partition_name TEXT;
        BEGIN
            IF requested_catalog_version !~ '^sha256:[a-f0-9]{64}$' THEN
                RAISE EXCEPTION 'catalog version must be an immutable SHA-256 digest';
            END IF;
            expected_partition_name :=
                't2_cache_p_' || substring(requested_catalog_version FROM 8 FOR 24);
            SELECT partition_name
              INTO registered_partition_name
              FROM public.t2_cache_partition_registry
             WHERE catalog_version = requested_catalog_version;
            IF registered_partition_name IS NOT NULL THEN
                IF registered_partition_name <> expected_partition_name THEN
                    RAISE EXCEPTION 'T2 cache partition registry is inconsistent';
                END IF;
                RETURN registered_partition_name;
            END IF;
            EXECUTE format(
                'CREATE ' || 'TABLE public.%I PARTITION OF public.t2_cache FOR VALUES IN (%L)',
                expected_partition_name,
                requested_catalog_version
            );
            INSERT INTO public.t2_cache_partition_registry (
                catalog_version,
                partition_name
            )
            VALUES (requested_catalog_version, expected_partition_name);
            RETURN expected_partition_name;
        END
        $$;

        CREATE FUNCTION fdai_t2_cache_drop_partition(requested_partition_name TEXT)
        RETURNS TEXT
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            registered_catalog_version TEXT;
        BEGIN
            IF requested_partition_name !~ '^t2_cache_p_[a-f0-9]{24}$' THEN
                RAISE EXCEPTION 'T2 cache partition name is invalid';
            END IF;
            SELECT catalog_version
              INTO registered_catalog_version
              FROM public.t2_cache_partition_registry
             WHERE partition_name = requested_partition_name;
            IF registered_catalog_version IS NULL THEN
                RAISE EXCEPTION 'T2 cache partition is not registered';
            END IF;
            IF EXISTS (
                SELECT 1
                  FROM public.t2_cache_catalog_state
                 WHERE singleton = TRUE
                   AND registered_catalog_version IN (
                       active_catalog_version,
                       rollback_catalog_version
                   )
            ) THEN
                RAISE EXCEPTION 'T2 cache partition is protected';
            END IF;
            EXECUTE format('DROP TABLE public.%I', requested_partition_name);
            RETURN registered_catalog_version;
        END
        $$;

        REVOKE ALL ON FUNCTION fdai_t2_cache_create_partition(TEXT) FROM PUBLIC;
        REVOKE ALL ON FUNCTION fdai_t2_cache_drop_partition(TEXT) FROM PUBLIC;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            registered RECORD;
            detached_name TEXT;
        BEGIN
            FOR registered IN
                SELECT partition_name FROM t2_cache_partition_registry
            LOOP
                detached_name := replace(
                    registered.partition_name,
                    't2_cache_p_',
                    't2_cache_detached_'
                ) || '_' || txid_current();
                EXECUTE format(
                    'ALTER TABLE t2_cache DETACH PARTITION %I',
                    registered.partition_name
                );
                EXECUTE format(
                    'ALTER TABLE %I RENAME TO %I',
                    registered.partition_name,
                    detached_name
                );
            END LOOP;
        END
        $$;

        DROP FUNCTION IF EXISTS fdai_t2_cache_drop_partition(TEXT);
        DROP FUNCTION IF EXISTS fdai_t2_cache_create_partition(TEXT);
        DROP TABLE t2_cache_rotation_receipt;
        DROP TABLE t2_cache_catalog_transition;
        DROP TABLE t2_cache_catalog_state;
        DROP TABLE t2_cache_partition_registry;

        ALTER TABLE t2_cache_legacy_default RENAME TO t2_cache_default;
        ALTER TABLE t2_cache ATTACH PARTITION t2_cache_default DEFAULT;
        DROP INDEX idx_t2_cache_lookup;
        ALTER TABLE t2_cache DROP COLUMN expires_at;
        CREATE INDEX idx_t2_cache_input_hash
            ON t2_cache (catalog_version, input_hash);
        """
    )

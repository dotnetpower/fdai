"""Bound exact-key cache storage and reclaim expired rows without deleting bindings."""

from __future__ import annotations

from alembic import op

revision = "core_cache_storage_efficiency_20261030"
down_revision = "core_inventory_snapshot_membership_20261029"
branch_labels = None
depends_on = None

migration_owner = "core-control-plane"
owned_tables = ("t2_cache", "t2_cache_rotation_receipt")
rollback = {
    "strategy": "remove-cache-efficiency-enforcement-preserving-receipts",
    "restores": "core_inventory_snapshot_membership_20261029",
    "requires": "t2-cache-writers-and-maintenance-stopped",
}


def upgrade() -> None:
    """Keep the existing read winner; leave detached legacy rollback material untouched."""
    op.execute(
        """
        SET LOCAL statement_timeout = '15s';
        SET LOCAL lock_timeout = '2s';
        SELECT pg_advisory_xact_lock(1178878281, 1412580168);
        LOCK TABLE public.t2_cache IN SHARE ROW EXCLUSIVE MODE;

        DO $deduplicate$
        DECLARE
            removed_rows BIGINT;
        BEGIN
            WITH ranked AS (
                SELECT catalog_version, id,
                       row_number() OVER (
                           PARTITION BY catalog_version, input_hash
                           ORDER BY expires_at DESC, created_at DESC, id DESC
                       ) AS position
                  FROM public.t2_cache
            ), victims AS (
                SELECT catalog_version, id FROM ranked
                 WHERE position > 1
                 LIMIT 10001
            ), removed AS (
                DELETE FROM public.t2_cache AS cache
                 USING victims
                 WHERE cache.catalog_version = victims.catalog_version
                   AND cache.id = victims.id
                RETURNING 1
            )
            SELECT count(*) INTO removed_rows FROM removed;
            IF removed_rows > 10000 THEN
                RAISE EXCEPTION
                    'T2 cache has more than 10000 duplicates; bounded owner maintenance required';
            END IF;
        END
        $deduplicate$;

        ALTER TABLE public.t2_cache
            ADD CONSTRAINT t2_cache_effective_key UNIQUE (catalog_version, input_hash);
        CREATE INDEX idx_t2_cache_expiry_cleanup
            ON public.t2_cache (expires_at, catalog_version, id);
        ALTER TABLE public.t2_cache_rotation_receipt
            ALTER COLUMN rollback_catalog_version DROP NOT NULL,
            ADD COLUMN IF NOT EXISTS expired_rows_deleted INTEGER NOT NULL DEFAULT 0
                CHECK (expired_rows_deleted BETWEEN 0 AND 1000),
            ADD COLUMN IF NOT EXISTS cleanup_cutoff TIMESTAMPTZ;

        CREATE FUNCTION public.fdai_t2_cache_prune_expired(
            requested_cutoff TIMESTAMPTZ,
            requested_row_limit INTEGER
        )
        RETURNS INTEGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        SET lock_timeout = '1s'
        SET statement_timeout = '5s'
        AS $prune$
        DECLARE
            removed_rows INTEGER;
        BEGIN
            IF requested_cutoff IS NULL OR NOT isfinite(requested_cutoff) THEN
                RAISE EXCEPTION 'T2 cache cleanup requires a finite cutoff';
            END IF;
            IF requested_row_limit IS NULL
               OR requested_row_limit < 1 OR requested_row_limit > 1000 THEN
                RAISE EXCEPTION 'T2 cache cleanup row limit must be between 1 and 1000';
            END IF;
            PERFORM pg_advisory_xact_lock(1178878281, 1412580168);
            WITH expired AS (
                SELECT catalog_version, id
                  FROM public.t2_cache
                 WHERE expires_at <= LEAST(requested_cutoff, statement_timestamp())
                 ORDER BY expires_at, catalog_version, id
                 LIMIT requested_row_limit
                 FOR UPDATE SKIP LOCKED
            ), removed AS (
                DELETE FROM public.t2_cache AS cache
                 USING expired
                 WHERE cache.catalog_version = expired.catalog_version
                   AND cache.id = expired.id
                RETURNING 1
            )
            SELECT count(*)::INTEGER INTO removed_rows FROM removed;
            RETURN removed_rows;
        END
        $prune$;
        REVOKE ALL ON FUNCTION public.fdai_t2_cache_prune_expired(TIMESTAMPTZ, INTEGER)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.fdai_t2_cache_prune_expired(TIMESTAMPTZ, INTEGER)
            TO fdai_core;
        """
    )


def downgrade() -> None:
    """Preserve nullable rollback history and receipt fields when restoring append-style writes."""
    op.execute(
        """
        SET LOCAL statement_timeout = '15s';
        SET LOCAL lock_timeout = '2s';
        SELECT pg_advisory_xact_lock(1178878281, 1412580168);
        DROP FUNCTION public.fdai_t2_cache_prune_expired(TIMESTAMPTZ, INTEGER);
        DROP INDEX public.idx_t2_cache_expiry_cleanup;
        ALTER TABLE public.t2_cache DROP CONSTRAINT t2_cache_effective_key;
        """
    )

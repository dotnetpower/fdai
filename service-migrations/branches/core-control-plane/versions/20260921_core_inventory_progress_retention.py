"""Bound terminal inventory progress hot replay without deleting active attempts."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_inventory_progress_retention_20260921"
down_revision: str | Sequence[str] | None = "core_canonical_incident_storage_20260921"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("inventory_progress_event",)
rollback = {
    "strategy": "drop-inventory-progress-retention-function",
    "restores": "core_canonical_incident_storage_20260921",
    "requires": "inventory progress writers stopped",
}


def upgrade() -> None:
    """Expose one guarded terminal-attempt retention operation to Core."""

    op.execute(
        """
        CREATE FUNCTION fdai_prune_inventory_progress(retain_terminal_attempts INTEGER)
        RETURNS BIGINT
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $function$
        DECLARE
            deleted_rows BIGINT;
        BEGIN
            IF retain_terminal_attempts < 1 OR retain_terminal_attempts > 1000 THEN
                RAISE EXCEPTION 'inventory progress terminal retention is outside its bound'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_advisory_xact_lock(
                hashtextextended('inventory-progress-retention', 0)
            );

            WITH latest_attempt_state AS MATERIALIZED (
                SELECT DISTINCT ON (run_id, attempt_id)
                       run_id,
                       attempt_id,
                       event_id,
                                             state,
                       NULLIF(
                           payload->>'deadline_at',
                           ''
                       )::TIMESTAMPTZ AS deadline_at
                  FROM inventory_progress_event
                 ORDER BY run_id, attempt_id, sequence DESC, event_id DESC
            ),
                        expired_terminal_attempts AS MATERIALIZED (
                SELECT run_id, attempt_id
                  FROM latest_attempt_state
                 WHERE state IN ('complete', 'failed')
                 ORDER BY event_id DESC, run_id DESC, attempt_id DESC
                OFFSET retain_terminal_attempts
                        ),
                        expired_attempts AS MATERIALIZED (
                                SELECT run_id, attempt_id
                                    FROM expired_terminal_attempts
                                UNION ALL
                                SELECT run_id, attempt_id
                                    FROM latest_attempt_state
                                 WHERE state = 'running'
                                     AND deadline_at < CURRENT_TIMESTAMP
            )
            DELETE FROM inventory_progress_event AS progress
             USING expired_attempts AS expired
             WHERE progress.run_id = expired.run_id
               AND progress.attempt_id = expired.attempt_id;

            GET DIAGNOSTICS deleted_rows = ROW_COUNT;
            RETURN deleted_rows;
        END;
        $function$;

        REVOKE ALL PRIVILEGES ON FUNCTION fdai_prune_inventory_progress(INTEGER)
        FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_prune_inventory_progress(INTEGER) TO fdai_core;
        """
    )


def downgrade() -> None:
    """Remove the guarded retention operation without changing retained rows."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON FUNCTION fdai_prune_inventory_progress(INTEGER)
        FROM fdai_core;
        DROP FUNCTION fdai_prune_inventory_progress(INTEGER);
        """
    )

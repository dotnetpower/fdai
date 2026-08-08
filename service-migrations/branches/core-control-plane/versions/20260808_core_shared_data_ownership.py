"""Enforce canonical ingestion ownership on shared state and audit tables."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "core_shared_data_ownership_20260808"
down_revision: str | Sequence[str] | None = "core_base_20260808"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("audit_log", "state_kv")
rollback = {
    "strategy": "restore-legacy-grants-after-dependent-runtime-stop",
    "restores": "core_base_20260808",
    "requires": "api-worker-base-heads-shared-database-drained-and-explicit-stop-ack",
    "risk": "restores-overbroad-legacy-grants-for-monolith-recovery-only",
}

_DEPENDENT_RUNTIME_GUARD = sa.text(
    """
    SELECT
        current_setting('fdai.dependent_runtimes_stopped', true) = 'on'
        AND (
            SELECT version_num
            FROM alembic_version_document_ingestion_api
        ) = 'ingestion_api_base_20260808'
        AND (
            SELECT version_num
            FROM alembic_version_document_processing_worker
        ) = 'document_worker_base_20260808'
        AND (
            SELECT version_num
            FROM alembic_version_isolated_executor
        ) = 'executor_base_20260808'
        AND NOT EXISTS (
            SELECT 1
            FROM pg_stat_activity
            WHERE datname = current_database()
            AND pid <> pg_backend_pid()
        )
    """
)


def _require_dependent_runtimes_stopped() -> None:
    """Refuse legacy grant restoration without explicit stopped-runtime proof."""
    safe_to_restore = op.get_bind().execute(_DEPENDENT_RUNTIME_GUARD).scalar_one()
    if safe_to_restore is not True:
        raise RuntimeError(
            "core shared-data downgrade requires stopped ingestion runtimes and Executor "
            "at their baseline revisions and fdai.dependent_runtimes_stopped=on"
        )


def upgrade() -> None:
    op.execute(
        "REVOKE ALL PRIVILEGES ON TABLE state_kv "
        "FROM fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE state_kv "
        "TO fdai_ingestion_api, fdai_ingestion_worker"
    )
    op.execute("GRANT SELECT ON TABLE state_kv TO fdai_ingestion_cohost")
    op.execute(
        "REVOKE INSERT, UPDATE, DELETE ON TABLE audit_log "
        "FROM fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost"
    )
    op.execute(
        "REVOKE TRUNCATE, REFERENCES, TRIGGER ON TABLE audit_log "
        "FROM fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost"
    )
    op.execute(
        "GRANT SELECT ON TABLE audit_log "
        "TO fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost"
    )
    op.execute(
        """
        CREATE FUNCTION enforce_state_kv_namespace_owner()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $state_owner$
        DECLARE
            source_key TEXT;
            target_key TEXT;
        BEGIN
            source_key := CASE WHEN TG_OP = 'INSERT' THEN NEW.key ELSE OLD.key END;
            target_key := CASE WHEN TG_OP = 'DELETE' THEN OLD.key ELSE NEW.key END;
            IF current_user = 'fdai_ingestion_api'
               AND NOT (
                   (
                       starts_with(source_key, 'stewardship_merge:')
                       OR starts_with(source_key, 'stewardship_repository_draft:')
                   )
                   AND (
                       starts_with(target_key, 'stewardship_merge:')
                       OR starts_with(target_key, 'stewardship_repository_draft:')
                   )
               ) THEN
                RAISE EXCEPTION
                    'fdai_ingestion_api does not own this state_kv namespace';
            ELSIF current_user = 'fdai_ingestion_worker'
                  AND NOT (
                      starts_with(source_key, 'handover_draft:')
                      AND starts_with(target_key, 'handover_draft:')
                  ) THEN
                RAISE EXCEPTION
                    'fdai_ingestion_worker does not own this state_kv namespace';
            ELSIF current_user = 'fdai_ingestion_cohost' THEN
                RAISE EXCEPTION
                    'fdai_ingestion_cohost has no state_kv write ownership';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $state_owner$;

        CREATE TRIGGER state_kv_namespace_owner
        BEFORE INSERT OR DELETE OR UPDATE ON state_kv
        FOR EACH ROW EXECUTE FUNCTION enforce_state_kv_namespace_owner();
        """
    )


def downgrade() -> None:
    _require_dependent_runtimes_stopped()
    op.execute("DROP TRIGGER state_kv_namespace_owner ON state_kv")
    op.execute("DROP FUNCTION enforce_state_kv_namespace_owner()")
    op.execute(
        "REVOKE ALL PRIVILEGES ON TABLE state_kv, audit_log "
        "FROM fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE state_kv "
        "TO fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost"
    )
    op.execute(
        "GRANT SELECT, INSERT ON TABLE audit_log "
        "TO fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost"
    )

"""Create and constrain the independent Core PostgreSQL runtime role."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_runtime_role_20260809"
down_revision: str | Sequence[str] | None = "core_shared_data_ownership_20260808"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "action_outbox",
    "audit_log",
    "case_history",
    "case_history_chunk",
    "case_history_migration_state",
    "case_history_revision",
    "catalog_search_document",
    "catalog_search_generation",
    "catalog_search_generation_document",
    "forecast_episode",
    "forecast_publication_outbox",
    "inventory_active",
    "inventory_realtime_link",
    "inventory_realtime_resource",
    "inventory_snapshot",
    "inventory_snapshot_link",
    "inventory_snapshot_resource",
    "learned_action",
    "ontology_embedding",
    "ontology_finding",
    "ontology_link",
    "ontology_link_type",
    "ontology_object_type",
    "ontology_resource",
    "process_event",
    "process_projection_outbox",
    "process_runtime",
    "report_signal",
    "schedule_dispatch_run",
    "scheduled_task",
    "state_kv",
    "t1_pattern_library",
    "t2_cache",
    "t2_cache_default",
)
rollback = {
    "strategy": "revoke-and-drop-core-runtime-role",
    "restores": "core_shared_data_ownership_20260808",
    "requires": "core-runtime-stopped",
}


def upgrade() -> None:
    op.execute(
        """
        DO $role$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_core') THEN
                CREATE ROLE fdai_core
                    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOINHERIT NOREPLICATION NOBYPASSRLS;
            END IF;
        END
        $role$;

        ALTER ROLE fdai_core
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
        REVOKE pg_read_all_data, pg_write_all_data FROM fdai_core;
        GRANT fdai_core TO CURRENT_USER;
        REVOKE CREATE ON SCHEMA public FROM fdai_core;
        GRANT USAGE ON SCHEMA public TO fdai_core;

        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
            action_outbox,
            audit_log,
            case_history,
            case_history_chunk,
            case_history_migration_state,
            case_history_revision,
            catalog_search_document,
            catalog_search_generation,
            catalog_search_generation_document,
            forecast_episode,
            forecast_publication_outbox,
            inventory_active,
            inventory_realtime_link,
            inventory_realtime_resource,
            inventory_snapshot,
            inventory_snapshot_link,
            inventory_snapshot_resource,
            learned_action,
            ontology_embedding,
            ontology_finding,
            ontology_link,
            ontology_link_type,
            ontology_object_type,
            ontology_resource,
            process_event,
            process_projection_outbox,
            process_runtime,
            report_signal,
            schedule_dispatch_run,
            scheduled_task,
            state_kv,
            t1_pattern_library,
            t2_cache,
            t2_cache_default
        TO fdai_core;
        GRANT USAGE, SELECT ON SEQUENCE audit_log_seq_seq TO fdai_core;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE
            action_outbox,
            audit_log,
            case_history,
            case_history_chunk,
            case_history_migration_state,
            case_history_revision,
            catalog_search_document,
            catalog_search_generation,
            catalog_search_generation_document,
            forecast_episode,
            forecast_publication_outbox,
            inventory_active,
            inventory_realtime_link,
            inventory_realtime_resource,
            inventory_snapshot,
            inventory_snapshot_link,
            inventory_snapshot_resource,
            learned_action,
            ontology_embedding,
            ontology_finding,
            ontology_link,
            ontology_link_type,
            ontology_object_type,
            ontology_resource,
            process_event,
            process_projection_outbox,
            process_runtime,
            report_signal,
            schedule_dispatch_run,
            scheduled_task,
            state_kv,
            t1_pattern_library,
            t2_cache,
            t2_cache_default
        FROM fdai_core;
        REVOKE ALL PRIVILEGES ON SEQUENCE audit_log_seq_seq FROM fdai_core;
        REVOKE USAGE ON SCHEMA public FROM fdai_core;
        REVOKE fdai_core FROM CURRENT_USER;
        DROP ROLE fdai_core;
        """
    )

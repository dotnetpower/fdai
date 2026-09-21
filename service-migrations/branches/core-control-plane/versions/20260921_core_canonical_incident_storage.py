"""Store temporal Incident projections only after canonical lifecycle admission."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_canonical_incident_storage_20260921"
down_revision: str | Sequence[str] | None = "core_ontology_writer_fence_20260920"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("audit_log", "operator_incident_projection")
rollback = {
    "strategy": "restore-broad-audit-correlation-projection",
    "restores": "core_ontology_writer_fence_20260920",
    "requires": "operator reads remain canonical-only while broad storage is restored",
}


def upgrade() -> None:
    """Remove noncanonical rows and stop recreating them from generic audit traffic."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fdai_project_operator_incident_audit_row(
            audit_row audit_log
        ) RETURNS VOID
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $function$
        DECLARE
            candidate TEXT;
        BEGIN
            FOR candidate IN
                SELECT DISTINCT candidates.correlation_id
                  FROM (
                    SELECT COALESCE(
                        NULLIF(BTRIM(audit_row.correlation_id), ''),
                        NULLIF(BTRIM(audit_row.entry->>'correlation_id'), '')
                    ) AS correlation_id
                    UNION ALL
                    SELECT COALESCE(
                        NULLIF(BTRIM(existing.correlation_id), ''),
                        NULLIF(BTRIM(existing.entry->>'correlation_id'), '')
                    )
                      FROM audit_log AS existing
                     WHERE existing.seq <= audit_row.seq
                       AND existing.event_id = audit_row.event_id
                    UNION ALL
                    SELECT COALESCE(
                        NULLIF(BTRIM(existing.correlation_id), ''),
                        NULLIF(BTRIM(existing.entry->>'correlation_id'), '')
                    )
                      FROM audit_log AS existing
                     WHERE existing.seq <= audit_row.seq
                       AND NULLIF(BTRIM(existing.entry->>'incident_id'), '') =
                           NULLIF(BTRIM(audit_row.entry->>'incident_id'), '')
                  ) AS candidates
                 WHERE candidates.correlation_id IS NOT NULL
                   AND LOWER(BTRIM(candidates.correlation_id)) NOT IN ('none', 'null')
            LOOP
                IF NOT EXISTS (
                    SELECT 1
                      FROM audit_log AS opened
                     WHERE opened.seq <= audit_row.seq
                       AND opened.entry->>'kind' = 'incident.open'
                       AND NULLIF(BTRIM(opened.entry->>'incident_id'), '') IS NOT NULL
                       AND COALESCE(
                           NULLIF(BTRIM(opened.correlation_id), ''),
                           NULLIF(BTRIM(opened.entry->>'correlation_id'), '')
                       ) = candidate
                ) THEN
                    CONTINUE;
                END IF;
                PERFORM fdai_refresh_operator_incident_projection(candidate, audit_row.seq);
            END LOOP;
        END;
        $function$;

        DELETE FROM operator_incident_projection
         WHERE NOT has_canonical_incident;
        """
    )


def downgrade() -> None:
    """Restore broad correlation projection for subsequently appended audit rows."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fdai_project_operator_incident_audit_row(
            audit_row audit_log
        ) RETURNS VOID
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $function$
        DECLARE
            candidate TEXT;
        BEGIN
            FOR candidate IN
                SELECT DISTINCT candidates.correlation_id
                  FROM (
                    SELECT COALESCE(
                        NULLIF(BTRIM(audit_row.correlation_id), ''),
                        NULLIF(BTRIM(audit_row.entry->>'correlation_id'), '')
                    ) AS correlation_id
                    UNION ALL
                    SELECT COALESCE(
                        NULLIF(BTRIM(existing.correlation_id), ''),
                        NULLIF(BTRIM(existing.entry->>'correlation_id'), '')
                    )
                      FROM audit_log AS existing
                     WHERE existing.seq <= audit_row.seq
                       AND existing.event_id = audit_row.event_id
                    UNION ALL
                    SELECT COALESCE(
                        NULLIF(BTRIM(existing.correlation_id), ''),
                        NULLIF(BTRIM(existing.entry->>'correlation_id'), '')
                    )
                      FROM audit_log AS existing
                     WHERE existing.seq <= audit_row.seq
                       AND NULLIF(BTRIM(existing.entry->>'incident_id'), '') =
                           NULLIF(BTRIM(audit_row.entry->>'incident_id'), '')
                  ) AS candidates
                 WHERE candidates.correlation_id IS NOT NULL
                   AND LOWER(BTRIM(candidates.correlation_id)) NOT IN ('none', 'null')
            LOOP
                PERFORM fdai_refresh_operator_incident_projection(candidate, audit_row.seq);
            END LOOP;
        END;
        $function$;
        """
    )

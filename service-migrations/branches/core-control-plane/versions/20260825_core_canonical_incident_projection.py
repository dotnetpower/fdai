"""Certify canonical Incident lifecycle membership in the Operator projection."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_canonical_incident_projection_20260825"
down_revision: str | Sequence[str] | None = "core_query_index_maintenance_20260825"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("audit_log", "operator_incident_projection")
rollback = {
    "strategy": "restore-audit-correlation-incident-roster",
    "restores": "core_query_index_maintenance_20260825",
    "requires": "operator-service-canonical-incident-read-rollback",
}


def upgrade() -> None:
    """Record canonical lifecycle membership for every temporal projection version."""
    op.execute(
        """
        ALTER TABLE operator_incident_projection
            ADD COLUMN has_canonical_incident BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN canonical_incident_id TEXT,
            ADD COLUMN canonical_incident_number TEXT,
            ADD COLUMN canonical_ticket_id TEXT,
            ADD COLUMN canonical_opened_at TEXT,
            ADD CONSTRAINT operator_incident_projection_canonical_identity_ck
                CHECK (has_canonical_incident = (canonical_incident_id IS NOT NULL));

        CREATE FUNCTION fdai_canonical_incident_identity(
            target_correlation TEXT,
            through_seq BIGINT
        ) RETURNS TABLE (
            incident_id TEXT,
            incident_number TEXT,
            ticket_id TEXT,
            opened_at TEXT
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $function$
            SELECT NULLIF(BTRIM(opened.entry->>'incident_id'), ''),
                   NULLIF(BTRIM(opened.entry->>'incident_number'), ''),
                   (
                       SELECT NULLIF(BTRIM(ticket.entry->>'ticket_id'), '')
                         FROM audit_log AS ticket
                        WHERE ticket.seq <= through_seq
                          AND ticket.entry->>'kind' = 'incident.ticket'
                          AND COALESCE(
                              NULLIF(BTRIM(ticket.correlation_id), ''),
                              NULLIF(BTRIM(ticket.entry->>'correlation_id'), '')
                          ) = target_correlation
                          AND NULLIF(BTRIM(ticket.entry->>'ticket_id'), '') IS NOT NULL
                        ORDER BY ticket.seq DESC
                        LIMIT 1
                        ),
                        NULLIF(BTRIM(opened.entry->>'opened_at'), '')
              FROM audit_log AS opened
             WHERE opened.seq <= through_seq
               AND opened.entry->>'kind' = 'incident.open'
               AND COALESCE(
                   NULLIF(BTRIM(opened.correlation_id), ''),
                   NULLIF(BTRIM(opened.entry->>'correlation_id'), '')
               ) = target_correlation
               AND NULLIF(BTRIM(opened.entry->>'incident_id'), '') IS NOT NULL
             ORDER BY opened.seq DESC
             LIMIT 1;
        $function$;

        WITH canonical AS (
            SELECT projection.correlation_id,
                   projection.valid_from_seq,
                   identity.incident_id,
                   identity.incident_number,
                   identity.ticket_id,
                   identity.opened_at
              FROM operator_incident_projection AS projection
              LEFT JOIN LATERAL fdai_canonical_incident_identity(
                  projection.correlation_id,
                  projection.valid_from_seq
              ) AS identity ON TRUE
        )
        UPDATE operator_incident_projection AS projection
           SET has_canonical_incident = canonical.incident_id IS NOT NULL,
               canonical_incident_id = canonical.incident_id,
               canonical_incident_number = canonical.incident_number,
               canonical_ticket_id = canonical.ticket_id,
               canonical_opened_at = canonical.opened_at
          FROM canonical
         WHERE canonical.correlation_id = projection.correlation_id
           AND canonical.valid_from_seq = projection.valid_from_seq;

        CREATE INDEX operator_incident_projection_canonical_current_page_idx
            ON operator_incident_projection (last_seq DESC, correlation_id)
            WHERE valid_to_seq IS NULL
              AND has_incident_activity
              AND has_canonical_incident;
        CREATE INDEX operator_incident_projection_canonical_snapshot_page_idx
            ON operator_incident_projection
                (valid_from_seq, valid_to_seq, last_seq DESC, correlation_id)
            WHERE has_incident_activity
              AND has_canonical_incident;

        CREATE FUNCTION fdai_mark_operator_incident_projection_canonical(
            audit_row audit_log
        ) RETURNS VOID
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $function$
        BEGIN
            WITH canonical AS (
                SELECT projection.correlation_id,
                       projection.valid_from_seq,
                       identity.incident_id,
                       identity.incident_number,
                       identity.ticket_id,
                       identity.opened_at
                  FROM operator_incident_projection AS projection
                  LEFT JOIN LATERAL fdai_canonical_incident_identity(
                      projection.correlation_id,
                      audit_row.seq
                  ) AS identity ON TRUE
                 WHERE projection.valid_from_seq = audit_row.seq
            )
            UPDATE operator_incident_projection AS projection
               SET has_canonical_incident = canonical.incident_id IS NOT NULL,
                   canonical_incident_id = canonical.incident_id,
                   canonical_incident_number = canonical.incident_number,
                   canonical_ticket_id = canonical.ticket_id,
                   canonical_opened_at = canonical.opened_at
              FROM canonical
             WHERE canonical.correlation_id = projection.correlation_id
               AND canonical.valid_from_seq = projection.valid_from_seq;
        END;
        $function$;

        CREATE FUNCTION fdai_mark_operator_incident_projection_canonical_trigger()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $function$
        BEGIN
            PERFORM fdai_mark_operator_incident_projection_canonical(NEW);
            RETURN NEW;
        END;
        $function$;

        REVOKE EXECUTE ON FUNCTION
            fdai_canonical_incident_identity(TEXT, BIGINT),
            fdai_mark_operator_incident_projection_canonical(audit_log),
            fdai_mark_operator_incident_projection_canonical_trigger()
        FROM PUBLIC;

        DROP TRIGGER IF EXISTS audit_log_zz_operator_incident_canonical ON audit_log;
        CREATE TRIGGER audit_log_zz_operator_incident_canonical
            AFTER INSERT ON audit_log
            FOR EACH ROW
            EXECUTE FUNCTION fdai_mark_operator_incident_projection_canonical_trigger();
        """
    )


def downgrade() -> None:
    """Restore the broader audit-correlation projection contract."""
    op.execute(
        """
        DROP TRIGGER audit_log_zz_operator_incident_canonical ON audit_log;
        DROP FUNCTION fdai_mark_operator_incident_projection_canonical_trigger();
        DROP FUNCTION fdai_mark_operator_incident_projection_canonical(audit_log);
        DROP FUNCTION fdai_canonical_incident_identity(TEXT, BIGINT);
        DROP INDEX operator_incident_projection_canonical_snapshot_page_idx;
        DROP INDEX operator_incident_projection_canonical_current_page_idx;
        ALTER TABLE operator_incident_projection
            DROP COLUMN canonical_opened_at,
            DROP COLUMN canonical_ticket_id,
            DROP COLUMN canonical_incident_number,
            DROP COLUMN canonical_incident_id,
            DROP COLUMN has_canonical_incident;
        """
    )

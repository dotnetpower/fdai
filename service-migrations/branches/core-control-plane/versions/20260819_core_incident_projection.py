"""Maintain a temporal incident read projection from append-only audit rows."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_incident_projection_20260819"
down_revision: str | Sequence[str] | None = "core_ontology_release_access_20260813"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("audit_log", "operator_incident_projection")
rollback = {
    "strategy": "drop-rebuildable-incident-projection",
    "restores": "core_ontology_release_access_20260813",
    "requires": "core-and-operator-runtimes-stopped",
}


def upgrade() -> None:
    """Create and backfill the audit-triggered temporal incident projection."""
    op.execute(
        """
        CREATE TABLE operator_incident_projection (
            correlation_id TEXT NOT NULL,
            valid_from_seq BIGINT NOT NULL,
            valid_to_seq BIGINT,
            last_seq BIGINT NOT NULL,
            projected_state TEXT NOT NULL,
            projected_vertical TEXT NOT NULL,
            projected_severity TEXT NOT NULL,
            search_document TEXT NOT NULL,
            group_history_count BIGINT NOT NULL CHECK (group_history_count >= 1),
            has_incident_activity BOOLEAN NOT NULL,
            history JSONB NOT NULL CHECK (
                JSONB_TYPEOF(history) = 'array'
                AND JSONB_ARRAY_LENGTH(history) BETWEEN 1 AND 100
            ),
            PRIMARY KEY (correlation_id, valid_from_seq),
            CHECK (BTRIM(correlation_id) <> ''),
            CHECK (LOWER(BTRIM(correlation_id)) NOT IN ('none', 'null')),
            CHECK (valid_to_seq IS NULL OR valid_to_seq > valid_from_seq)
        );
        CREATE UNIQUE INDEX operator_incident_projection_current_uq
            ON operator_incident_projection (correlation_id)
            WHERE valid_to_seq IS NULL;
        CREATE INDEX operator_incident_projection_current_page_idx
            ON operator_incident_projection (last_seq DESC, correlation_id)
            WHERE valid_to_seq IS NULL AND has_incident_activity;
        CREATE INDEX operator_incident_projection_snapshot_page_idx
            ON operator_incident_projection
                (valid_from_seq, valid_to_seq, last_seq DESC, correlation_id)
            WHERE has_incident_activity;
        CREATE INDEX audit_log_entry_correlation_idx
            ON audit_log ((NULLIF(BTRIM(entry->>'correlation_id'), '')))
            WHERE NULLIF(BTRIM(entry->>'correlation_id'), '') IS NOT NULL;
        CREATE INDEX audit_log_entry_incident_idx
            ON audit_log ((NULLIF(BTRIM(entry->>'incident_id'), '')))
            WHERE NULLIF(BTRIM(entry->>'incident_id'), '') IS NOT NULL;

        CREATE FUNCTION fdai_refresh_operator_incident_projection(
            target_correlation TEXT,
            refresh_seq BIGINT
        ) RETURNS VOID
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $function$
        DECLARE
            projected RECORD;
            normalized_target TEXT := NULLIF(BTRIM(target_correlation), '');
        BEGIN
            IF normalized_target IS NULL
               OR LOWER(normalized_target) IN ('none', 'null') THEN
                RETURN;
            END IF;

            SELECT grouped.last_seq,
                   grouped.projected_state,
                   grouped.projected_vertical,
                   grouped.projected_severity,
                   grouped.search_document,
                   grouped.group_history_count,
                   grouped.has_incident_activity,
                   grouped.history
              INTO projected
              FROM (
                WITH relevant_events AS (
                    SELECT DISTINCT audit.event_id
                      FROM audit_log AS audit
                     WHERE audit.seq <= refresh_seq
                       AND COALESCE(
                           NULLIF(BTRIM(audit.correlation_id), ''),
                           NULLIF(BTRIM(audit.entry->>'correlation_id'), '')
                       ) = normalized_target
                ),
                event_anchor AS (
                    SELECT audit.event_id,
                           MIN(COALESCE(
                               NULLIF(BTRIM(audit.correlation_id), ''),
                               NULLIF(BTRIM(audit.entry->>'correlation_id'), '')
                           )) AS correlation_id
                      FROM audit_log AS audit
                      JOIN relevant_events USING (event_id)
                     WHERE audit.seq <= refresh_seq
                       AND COALESCE(
                           NULLIF(BTRIM(audit.correlation_id), ''),
                           NULLIF(BTRIM(audit.entry->>'correlation_id'), '')
                       ) IS NOT NULL
                     GROUP BY audit.event_id
                    HAVING COUNT(DISTINCT COALESCE(
                               NULLIF(BTRIM(audit.correlation_id), ''),
                               NULLIF(BTRIM(audit.entry->>'correlation_id'), '')
                           )) = 1
                       AND MIN(COALESCE(
                               NULLIF(BTRIM(audit.correlation_id), ''),
                               NULLIF(BTRIM(audit.entry->>'correlation_id'), '')
                           )) = normalized_target
                ),
                relevant_incidents AS (
                    SELECT DISTINCT NULLIF(BTRIM(audit.entry->>'incident_id'), '')
                           AS incident_id
                      FROM audit_log AS audit
                     WHERE audit.seq <= refresh_seq
                       AND audit.entry->>'kind' = 'incident.open'
                       AND COALESCE(
                           NULLIF(BTRIM(audit.correlation_id), ''),
                           NULLIF(BTRIM(audit.entry->>'correlation_id'), '')
                       ) = normalized_target
                ),
                incident_anchor AS (
                    SELECT NULLIF(BTRIM(audit.entry->>'incident_id'), '') AS incident_id,
                           MIN(COALESCE(
                               NULLIF(BTRIM(audit.correlation_id), ''),
                               NULLIF(BTRIM(audit.entry->>'correlation_id'), '')
                           )) AS correlation_id
                      FROM audit_log AS audit
                      JOIN relevant_incidents
                        ON relevant_incidents.incident_id =
                           NULLIF(BTRIM(audit.entry->>'incident_id'), '')
                     WHERE audit.seq <= refresh_seq
                       AND audit.entry->>'kind' = 'incident.open'
                       AND COALESCE(
                           NULLIF(BTRIM(audit.correlation_id), ''),
                           NULLIF(BTRIM(audit.entry->>'correlation_id'), '')
                       ) IS NOT NULL
                     GROUP BY NULLIF(BTRIM(audit.entry->>'incident_id'), '')
                    HAVING COUNT(DISTINCT COALESCE(
                               NULLIF(BTRIM(audit.correlation_id), ''),
                               NULLIF(BTRIM(audit.entry->>'correlation_id'), '')
                           )) = 1
                       AND MIN(COALESCE(
                               NULLIF(BTRIM(audit.correlation_id), ''),
                               NULLIF(BTRIM(audit.entry->>'correlation_id'), '')
                           )) = normalized_target
                ),
                normalized AS (
                    SELECT audit.*,
                           CASE
                               WHEN audit.entry->>'kind' = 'incident.transition'
                               THEN audit.entry->>'to_state'
                               WHEN audit.entry->>'kind' = 'incident.open'
                               THEN audit.entry->>'state'
                               ELSE NULL
                           END AS lifecycle_state,
                           CASE LOWER(REPLACE(COALESCE(
                               audit.entry->>'vertical', audit.entry->>'category', ''
                           ), '-', '_'))
                               WHEN 'resilience' THEN 'resilience'
                               WHEN 'dr' THEN 'resilience'
                               WHEN 'reliability' THEN 'resilience'
                               WHEN 'chaos' THEN 'resilience'
                               WHEN 'change' THEN 'change_safety'
                               WHEN 'change_safety' THEN 'change_safety'
                               WHEN 'config_drift' THEN 'change_safety'
                               WHEN 'security' THEN 'change_safety'
                               WHEN 'cost' THEN 'cost_governance'
                               WHEN 'cost_governance' THEN 'cost_governance'
                               WHEN 'finops' THEN 'cost_governance'
                               ELSE NULL
                           END AS vertical_bucket,
                           CASE LOWER(BTRIM(COALESCE(audit.entry->>'severity', '')))
                               WHEN 'critical' THEN 'critical'
                               WHEN 'sev1' THEN 'critical'
                               WHEN 'high' THEN 'high'
                               WHEN 'sev2' THEN 'high'
                               WHEN 'medium' THEN 'medium'
                               WHEN 'sev3' THEN 'medium'
                               WHEN 'low' THEN 'low'
                               WHEN 'sev4' THEN 'low'
                               ELSE NULL
                           END AS severity_bucket,
                           SPLIT_PART(LOWER(COALESCE(audit.action_kind, '')), '.', 1) IN (
                               'background-task',
                               'iam',
                               'startup_readiness',
                               'semantic_turn',
                               'observation-campaign',
                               'read-investigation'
                           ) AS platform_activity
                      FROM audit_log AS audit
                      LEFT JOIN event_anchor
                        ON event_anchor.event_id = audit.event_id
                      LEFT JOIN incident_anchor
                        ON incident_anchor.incident_id =
                           NULLIF(BTRIM(audit.entry->>'incident_id'), '')
                     WHERE audit.seq <= refresh_seq
                       AND COALESCE(
                           NULLIF(BTRIM(audit.correlation_id), ''),
                           NULLIF(BTRIM(audit.entry->>'correlation_id'), ''),
                           incident_anchor.correlation_id,
                           event_anchor.correlation_id
                       ) = normalized_target
                ),
                ranked AS (
                    SELECT normalized.*,
                           ROW_NUMBER() OVER (ORDER BY seq DESC) AS recent_rank
                      FROM normalized
                )
                SELECT MAX(seq) AS last_seq,
                       COALESCE(
                           (ARRAY_AGG(lifecycle_state ORDER BY seq DESC)
                                FILTER (WHERE lifecycle_state IS NOT NULL))[1],
                           CASE
                               WHEN BOOL_OR(LOWER(COALESCE(entry->>'outcome', '')) IN (
                                   'resolved', 'remediated', 'mitigated',
                                   'rollback_succeeded', 'rollback_completed'
                               )) THEN 'resolved'
                               WHEN COUNT(*) > 1 OR BOOL_OR(
                                   LOWER(COALESCE(entry->>'decision', '')) = 'hil'
                               ) THEN 'in_progress'
                               ELSE 'open'
                           END
                       ) AS projected_state,
                       COALESCE(
                           (ARRAY_AGG(vertical_bucket ORDER BY seq DESC)
                                FILTER (WHERE vertical_bucket IS NOT NULL))[1],
                           'unknown'
                       ) AS projected_vertical,
                       COALESCE(
                           (ARRAY_AGG(severity_bucket ORDER BY seq DESC)
                                FILTER (WHERE severity_bucket IS NOT NULL))[1],
                           'unknown'
                       ) AS projected_severity,
                       LOWER(STRING_AGG(CONCAT_WS(
                           ' ', normalized_target, event_id, action_kind,
                           entry->>'title', entry->>'summary', entry->>'rule_id',
                           (entry->'citing_rules')::text,
                           (entry->'correlation_keys')::text,
                           entry->>'resource_id', entry->>'resource_type',
                           entry->>'reason', entry->>'stage',
                           entry#>>'{payload,title}', entry#>>'{payload,summary}',
                           entry#>>'{payload,rule_id}',
                           (entry#>'{payload,citing_rules}')::text,
                           (entry#>'{payload,correlation_keys}')::text,
                           entry#>>'{payload,resource_id}',
                           entry#>>'{payload,resource_type}',
                           entry#>>'{payload,reason}', entry#>>'{payload,stage}'
                       ), ' ' ORDER BY seq)) AS search_document,
                       COUNT(*) AS group_history_count,
                       BOOL_OR(NOT platform_activity) AS has_incident_activity,
                       JSONB_AGG(JSONB_BUILD_OBJECT(
                           'seq', seq,
                           'event_id', event_id,
                           'correlation_id', correlation_id,
                           'actor', actor,
                           'action_kind', action_kind,
                           'mode', mode,
                           'entry', entry,
                           'previous_hash', previous_hash,
                           'entry_hash', entry_hash,
                           'created_at', created_at
                       ) ORDER BY seq) FILTER (WHERE recent_rank <= 100) AS history
                  FROM ranked
              ) AS grouped
             WHERE grouped.has_incident_activity;

            DELETE FROM operator_incident_projection
             WHERE correlation_id = normalized_target
               AND valid_from_seq = refresh_seq;
            UPDATE operator_incident_projection
               SET valid_to_seq = refresh_seq
             WHERE correlation_id = normalized_target
               AND valid_to_seq IS NULL
               AND valid_from_seq < refresh_seq;

            IF projected.last_seq IS NULL THEN
                RETURN;
            END IF;

            INSERT INTO operator_incident_projection (
                correlation_id,
                valid_from_seq,
                valid_to_seq,
                last_seq,
                projected_state,
                projected_vertical,
                projected_severity,
                search_document,
                group_history_count,
                has_incident_activity,
                history
            ) VALUES (
                normalized_target,
                refresh_seq,
                NULL,
                projected.last_seq,
                projected.projected_state,
                projected.projected_vertical,
                projected.projected_severity,
                projected.search_document,
                projected.group_history_count,
                projected.has_incident_activity,
                projected.history
            );
        END;
        $function$;

        CREATE FUNCTION fdai_project_operator_incident_audit_row(audit_row audit_log)
        RETURNS VOID
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

        CREATE FUNCTION fdai_project_operator_incident_audit_trigger()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $function$
        BEGIN
            PERFORM fdai_project_operator_incident_audit_row(NEW);
            RETURN NEW;
        END;
        $function$;

        REVOKE ALL PRIVILEGES ON TABLE operator_incident_projection FROM PUBLIC;
        REVOKE EXECUTE ON FUNCTION
            fdai_refresh_operator_incident_projection(TEXT, BIGINT),
            fdai_project_operator_incident_audit_row(audit_log),
            fdai_project_operator_incident_audit_trigger()
        FROM PUBLIC;

        INSERT INTO operator_incident_projection (
            correlation_id,
            valid_from_seq,
            valid_to_seq,
            last_seq,
            projected_state,
            projected_vertical,
            projected_severity,
            search_document,
            group_history_count,
            has_incident_activity,
            history
        )
        WITH snapshot AS (
            SELECT COALESCE(MAX(seq), 0) AS snapshot_seq
              FROM audit_log
        ),
        event_anchor AS (
            SELECT event_id,
                   MIN(COALESCE(
                       NULLIF(BTRIM(correlation_id), ''),
                       NULLIF(BTRIM(entry->>'correlation_id'), '')
                   )) AS correlation_id
              FROM audit_log
             WHERE seq <= (SELECT snapshot_seq FROM snapshot)
               AND COALESCE(
                       NULLIF(BTRIM(correlation_id), ''),
                       NULLIF(BTRIM(entry->>'correlation_id'), '')
                   ) IS NOT NULL
             GROUP BY event_id
            HAVING COUNT(DISTINCT COALESCE(
                       NULLIF(BTRIM(correlation_id), ''),
                       NULLIF(BTRIM(entry->>'correlation_id'), '')
                   )) = 1
        ),
        incident_anchor AS (
            SELECT NULLIF(BTRIM(entry->>'incident_id'), '') AS incident_id,
                   MIN(COALESCE(
                       NULLIF(BTRIM(correlation_id), ''),
                       NULLIF(BTRIM(entry->>'correlation_id'), '')
                   )) AS correlation_id
              FROM audit_log
             WHERE seq <= (SELECT snapshot_seq FROM snapshot)
               AND entry->>'kind' = 'incident.open'
               AND NULLIF(BTRIM(entry->>'incident_id'), '') IS NOT NULL
               AND COALESCE(
                       NULLIF(BTRIM(correlation_id), ''),
                       NULLIF(BTRIM(entry->>'correlation_id'), '')
                   ) IS NOT NULL
             GROUP BY NULLIF(BTRIM(entry->>'incident_id'), '')
            HAVING COUNT(DISTINCT COALESCE(
                       NULLIF(BTRIM(correlation_id), ''),
                       NULLIF(BTRIM(entry->>'correlation_id'), '')
                   )) = 1
        ),
        normalized AS (
            SELECT audit.*,
                   COALESCE(
                       NULLIF(BTRIM(audit.correlation_id), ''),
                       NULLIF(BTRIM(audit.entry->>'correlation_id'), ''),
                       incident_anchor.correlation_id,
                       event_anchor.correlation_id
                   ) AS normalized_correlation_id,
                   CASE
                       WHEN audit.entry->>'kind' = 'incident.transition'
                       THEN audit.entry->>'to_state'
                       WHEN audit.entry->>'kind' = 'incident.open'
                       THEN audit.entry->>'state'
                       ELSE NULL
                   END AS lifecycle_state,
                   CASE LOWER(REPLACE(COALESCE(
                       audit.entry->>'vertical', audit.entry->>'category', ''
                   ), '-', '_'))
                       WHEN 'resilience' THEN 'resilience'
                       WHEN 'dr' THEN 'resilience'
                       WHEN 'reliability' THEN 'resilience'
                       WHEN 'chaos' THEN 'resilience'
                       WHEN 'change' THEN 'change_safety'
                       WHEN 'change_safety' THEN 'change_safety'
                       WHEN 'config_drift' THEN 'change_safety'
                       WHEN 'security' THEN 'change_safety'
                       WHEN 'cost' THEN 'cost_governance'
                       WHEN 'cost_governance' THEN 'cost_governance'
                       WHEN 'finops' THEN 'cost_governance'
                       ELSE NULL
                   END AS vertical_bucket,
                   CASE LOWER(BTRIM(COALESCE(audit.entry->>'severity', '')))
                       WHEN 'critical' THEN 'critical'
                       WHEN 'sev1' THEN 'critical'
                       WHEN 'high' THEN 'high'
                       WHEN 'sev2' THEN 'high'
                       WHEN 'medium' THEN 'medium'
                       WHEN 'sev3' THEN 'medium'
                       WHEN 'low' THEN 'low'
                       WHEN 'sev4' THEN 'low'
                       ELSE NULL
                   END AS severity_bucket,
                   SPLIT_PART(LOWER(COALESCE(audit.action_kind, '')), '.', 1) IN (
                       'background-task',
                       'iam',
                       'startup_readiness',
                       'semantic_turn',
                       'observation-campaign',
                       'read-investigation'
                   ) AS platform_activity
              FROM audit_log AS audit
              LEFT JOIN event_anchor ON event_anchor.event_id = audit.event_id
              LEFT JOIN incident_anchor
                ON incident_anchor.incident_id =
                   NULLIF(BTRIM(audit.entry->>'incident_id'), '')
             WHERE audit.seq <= (SELECT snapshot_seq FROM snapshot)
        ),
        ranked AS (
            SELECT normalized.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY normalized_correlation_id ORDER BY seq DESC
                   ) AS recent_rank
              FROM normalized
             WHERE normalized_correlation_id IS NOT NULL
               AND LOWER(BTRIM(normalized_correlation_id)) NOT IN ('none', 'null')
        )
        SELECT normalized_correlation_id,
               (SELECT snapshot_seq FROM snapshot),
               NULL,
               MAX(seq),
               COALESCE(
                   (ARRAY_AGG(lifecycle_state ORDER BY seq DESC)
                        FILTER (WHERE lifecycle_state IS NOT NULL))[1],
                   CASE
                       WHEN BOOL_OR(LOWER(COALESCE(entry->>'outcome', '')) IN (
                           'resolved', 'remediated', 'mitigated',
                           'rollback_succeeded', 'rollback_completed'
                       )) THEN 'resolved'
                       WHEN COUNT(*) > 1 OR BOOL_OR(
                           LOWER(COALESCE(entry->>'decision', '')) = 'hil'
                       ) THEN 'in_progress'
                       ELSE 'open'
                   END
               ),
               COALESCE(
                   (ARRAY_AGG(vertical_bucket ORDER BY seq DESC)
                        FILTER (WHERE vertical_bucket IS NOT NULL))[1],
                   'unknown'
               ),
               COALESCE(
                   (ARRAY_AGG(severity_bucket ORDER BY seq DESC)
                        FILTER (WHERE severity_bucket IS NOT NULL))[1],
                   'unknown'
               ),
               LOWER(STRING_AGG(CONCAT_WS(
                   ' ', normalized_correlation_id, event_id, action_kind,
                   entry->>'title', entry->>'summary', entry->>'rule_id',
                   (entry->'citing_rules')::text,
                   (entry->'correlation_keys')::text,
                   entry->>'resource_id', entry->>'resource_type',
                   entry->>'reason', entry->>'stage',
                   entry#>>'{payload,title}', entry#>>'{payload,summary}',
                   entry#>>'{payload,rule_id}',
                   (entry#>'{payload,citing_rules}')::text,
                   (entry#>'{payload,correlation_keys}')::text,
                   entry#>>'{payload,resource_id}',
                   entry#>>'{payload,resource_type}',
                   entry#>>'{payload,reason}', entry#>>'{payload,stage}'
               ), ' ' ORDER BY seq)),
               COUNT(*),
               TRUE,
               JSONB_AGG(JSONB_BUILD_OBJECT(
                   'seq', seq,
                   'event_id', event_id,
                   'correlation_id', correlation_id,
                   'actor', actor,
                   'action_kind', action_kind,
                   'mode', mode,
                   'entry', entry,
                   'previous_hash', previous_hash,
                   'entry_hash', entry_hash,
                   'created_at', created_at
               ) ORDER BY seq) FILTER (WHERE recent_rank <= 100)
          FROM ranked
         GROUP BY normalized_correlation_id
        HAVING BOOL_OR(NOT platform_activity);

        CREATE TRIGGER audit_log_operator_incident_projection
            AFTER INSERT ON audit_log
            FOR EACH ROW
            EXECUTE FUNCTION fdai_project_operator_incident_audit_trigger();
        """
    )


def downgrade() -> None:
    """Drop the rebuildable projection without changing append-only audit history."""
    op.execute(
        """
        DROP TRIGGER audit_log_operator_incident_projection ON audit_log;
        DROP FUNCTION fdai_project_operator_incident_audit_trigger();
        DROP FUNCTION fdai_project_operator_incident_audit_row(audit_log);
        DROP FUNCTION fdai_refresh_operator_incident_projection(TEXT, BIGINT);
        DROP TABLE operator_incident_projection;
        DROP INDEX audit_log_entry_incident_idx;
        DROP INDEX audit_log_entry_correlation_idx;
        """
    )

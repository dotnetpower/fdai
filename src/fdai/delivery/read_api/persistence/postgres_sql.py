"""SQL statements used by the Postgres console read model."""

from typing import Final

INCIDENT_SUMMARY_HISTORY_LIMIT: Final[int] = 500

INCIDENT_PAGE_SQL: Final[str] = """
WITH snapshot AS (
        SELECT COALESCE(%(snapshot_seq)s, MAX(seq), 0) AS snapshot_seq
            FROM audit_log
),
bounded_audit AS (
        SELECT * FROM audit_log
         WHERE seq <= (SELECT snapshot_seq FROM snapshot)
),
event_anchor AS (
    SELECT event_id, MIN(correlation_id) AS correlation_id
            FROM bounded_audit
     WHERE correlation_id IS NOT NULL AND correlation_id <> ''
     GROUP BY event_id
    HAVING COUNT(DISTINCT correlation_id) = 1
),
correlation_anchor AS (
    SELECT DISTINCT correlation_id
      FROM bounded_audit
     WHERE correlation_id IS NOT NULL AND correlation_id <> ''
),
hil_park AS (
    SELECT value->>'approval_id' AS approval_id,
         LOWER(value->'rule'->>'severity') AS severity,
         LOWER(value->'rule'->>'category') AS category
     FROM state_kv
    WHERE key LIKE 'hil_park:%%'
),
incident_open_raw AS (
    SELECT a.entry->>'incident_id' AS incident_id,
           CASE
               WHEN a.correlation_id IS NOT NULL AND a.correlation_id <> ''
               THEN a.correlation_id
               ELSE key_stats.correlation_id
           END AS explicit_correlation_id,
           CASE
               WHEN a.correlation_id IS NOT NULL AND a.correlation_id <> ''
               THEN FALSE
               ELSE key_stats.candidate_count > 1
           END AS ambiguous
      FROM bounded_audit AS a
      LEFT JOIN LATERAL (
          SELECT COUNT(DISTINCT SUBSTRING(value FROM 6)) AS candidate_count,
                 CASE
                     WHEN COUNT(DISTINCT SUBSTRING(value FROM 6)) = 1
                     THEN MIN(SUBSTRING(value FROM 6))
                     ELSE NULL
                 END AS correlation_id
            FROM jsonb_array_elements_text(
                CASE
                    WHEN jsonb_typeof(a.entry->'correlation_keys') = 'array'
                    THEN a.entry->'correlation_keys'
                    ELSE '[]'::jsonb
                END
            ) AS value
           WHERE value LIKE 'corr:%%'
      ) AS key_stats ON TRUE
     WHERE a.entry->>'kind' = 'incident.open'
),
incident_open AS (
    SELECT incident_id,
           CASE
               WHEN BOOL_OR(ambiguous)
                    OR COUNT(DISTINCT explicit_correlation_id) > 1
               THEN NULL
               WHEN COUNT(DISTINCT explicit_correlation_id) = 1
               THEN MIN(explicit_correlation_id)
               ELSE incident_id
           END AS correlation_id,
           BOOL_OR(ambiguous)
               OR COUNT(DISTINCT explicit_correlation_id) > 1 AS ambiguous
      FROM incident_open_raw
     GROUP BY incident_id
),
normalized AS (
    SELECT a.*,
           CASE
               WHEN a.correlation_id IS NOT NULL AND a.correlation_id <> ''
               THEN a.correlation_id
               WHEN a.entry->>'kind' LIKE 'incident.%%'
               THEN CASE WHEN NOT io.ambiguous THEN io.correlation_id ELSE NULL END
               ELSE COALESCE(
                   a.entry->>'correlation_id',
                   ea.correlation_id,
                   ca.correlation_id,
                   io.correlation_id
               )
           END AS normalized_correlation_id,
           COALESCE(a.entry->>'severity', hp.severity) AS projection_severity,
           COALESCE(a.entry->>'category', hp.category) AS projection_category,
           CASE
               WHEN a.entry->>'kind' = 'incident.transition' THEN a.entry->>'to_state'
               WHEN a.entry->>'kind' = 'incident.open' THEN a.entry->>'state'
               ELSE NULL
           END AS lifecycle_state,
           CASE LOWER(COALESCE(
               a.entry->>'vertical',
               a.entry->>'category',
               hp.category,
               ''
           ))
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
           END AS vertical_bucket
    FROM bounded_audit AS a
      LEFT JOIN event_anchor AS ea ON ea.event_id = a.event_id
            LEFT JOIN correlation_anchor AS ca ON ca.correlation_id = a.event_id::text
      LEFT JOIN incident_open AS io ON io.incident_id = a.entry->>'incident_id'
    LEFT JOIN hil_park AS hp ON hp.approval_id = a.entry->>'approval_id'
),
ranked AS (
    SELECT normalized.*,
           ROW_NUMBER() OVER (
               PARTITION BY normalized_correlation_id ORDER BY seq DESC
           ) AS recent_rank,
           ROW_NUMBER() OVER (
               PARTITION BY normalized_correlation_id ORDER BY seq ASC
           ) AS oldest_rank,
           COUNT(*) OVER (
               PARTITION BY normalized_correlation_id
           ) AS group_history_count
      FROM normalized
),
incident_groups AS (
    SELECT normalized_correlation_id,
           MAX(seq) AS last_seq,
           COALESCE(
               (ARRAY_AGG(lifecycle_state ORDER BY seq DESC)
                   FILTER (WHERE lifecycle_state IS NOT NULL))[1],
               CASE
                   WHEN BOOL_OR(LOWER(COALESCE(entry->>'outcome', '')) IN (
                       'resolved', 'remediated', 'mitigated',
                       'rollback_succeeded', 'rollback_completed'
                   )) THEN 'resolved'
                   WHEN COUNT(*) > 1 OR BOOL_OR(
                       LOWER(COALESCE(entry->>'pipeline_stage', entry->>'stage', ''))
                           IN ('verify', 'gate', 'execute', 'escalate', 'hil')
                       OR LOWER(COALESCE(entry->>'decision', entry->>'gate_decision', '')) = 'hil'
                   ) THEN 'in_progress'
                   ELSE 'open'
               END
           ) AS projected_state,
           COALESCE(
               (ARRAY_AGG(vertical_bucket ORDER BY seq DESC)
                   FILTER (WHERE vertical_bucket IS NOT NULL))[1],
               'unknown'
           ) AS projected_vertical
    FROM ranked
     WHERE normalized_correlation_id IS NOT NULL
       AND normalized_correlation_id <> ''
     GROUP BY normalized_correlation_id
),
selected AS (
    SELECT normalized_correlation_id, last_seq
      FROM incident_groups
    WHERE (
        CAST(%(before_seq)s AS BIGINT) IS NULL
        OR last_seq < CAST(%(before_seq)s AS BIGINT)
    )
         AND (
             CAST(%(correlation_id)s AS TEXT) IS NULL
             OR normalized_correlation_id = CAST(%(correlation_id)s AS TEXT)
         )
         AND (
             CAST(%(vertical)s AS TEXT) IS NULL
             OR projected_vertical = CAST(%(vertical)s AS TEXT)
         )
       AND (
           %(status)s = 'all'
           OR (%(status)s = 'resolved' AND projected_state IN ('resolved', 'closed'))
           OR (%(status)s = 'active' AND projected_state NOT IN ('resolved', 'closed'))
       )
     ORDER BY last_seq DESC
     LIMIT %(fetch)s
)
SELECT n.seq, n.event_id, n.correlation_id, n.actor, n.action_kind,
       n.mode, n.entry, n.previous_hash, n.entry_hash, n.created_at,
         n.normalized_correlation_id, s.last_seq AS group_last_seq,
         n.group_history_count, n.projection_severity, n.projection_category,
    (SELECT snapshot_seq FROM snapshot) AS snapshot_seq
  FROM selected AS s
  JOIN ranked AS n
    ON n.normalized_correlation_id = s.normalized_correlation_id
 WHERE n.recent_rank <= %(summary_history_limit)s
     OR n.oldest_rank = 1
     OR n.lifecycle_state IS NOT NULL
 ORDER BY s.last_seq DESC, n.seq ASC
"""

__all__ = ["INCIDENT_PAGE_SQL", "INCIDENT_SUMMARY_HISTORY_LIMIT"]

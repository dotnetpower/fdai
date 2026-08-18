"""Bounded parameterized SQL for Operator Service read projections."""

from typing import Final

AUDIT_PAGE_SQL: Final = """
SELECT seq, event_id, correlation_id, actor, action_kind, mode,
       entry, previous_hash, entry_hash, created_at
  FROM audit_log
 WHERE (%(cutoff)s::bigint IS NULL OR seq < %(cutoff)s::bigint)
   AND (%(correlation_id)s::text IS NULL OR correlation_id = %(correlation_id)s::text)
 ORDER BY seq DESC
 LIMIT %(fetch)s
"""

BROWSER_EVIDENCE_PAGE_SQL: Final = """
SELECT artifact_id, policy_id, policy_version,
       canonical_source_url, canonical_final_url,
       captured_at, expires_at,
       selector_count,
       screenshot_hash, text_hash, snapshot_hash,
       redaction_count,
       browser_version, chain_of_custody_audit_ref,
       prompt_injection_finding_count, isolation_verified,
       untrusted, legal_hold, legal_hold_ref, legal_hold_at
  FROM operator_browser_evidence_metadata
 ORDER BY captured_at DESC, artifact_id DESC
 LIMIT %(limit)s
"""

AGENT_INVENTORY_ACTIVITY_SQL: Final = """
SELECT s.id, s.status, s.source, s.observation_kind, s.started_at,
       s.completed_at, s.promoted_at, s.failure_code,
       (SELECT COUNT(*) FROM inventory_snapshot_resource r
         WHERE r.snapshot_id=s.id) AS resource_count,
       (SELECT COUNT(*) FROM inventory_snapshot_link l
         WHERE l.snapshot_id=s.id) AS link_count
  FROM inventory_snapshot s
 ORDER BY s.started_at DESC, s.id DESC
 LIMIT %(limit)s
"""

AGENT_ONTOLOGY_ACTIVITY_SQL: Final = """
SELECT value, updated_at
  FROM state_kv
 WHERE key = 'inventory-ontology:status'
 LIMIT 1
"""

AGENT_READ_ACTIVITY_SQL: Final = """
SELECT profile.key, profile.value->>'tool_id' AS tool_id,
       profile.value->>'transport' AS transport,
       profile.value->>'operation_class' AS operation_class,
       sample
  FROM state_kv profile
 CROSS JOIN LATERAL jsonb_array_elements(
       CASE WHEN jsonb_typeof(profile.value->'samples') = 'array'
            THEN profile.value->'samples' ELSE '[]'::jsonb END
 ) AS sample
 WHERE profile.key LIKE 'read-investigation-latency:%%'
   AND profile.value->>'tool_id' = 'get_resource_state'
   AND profile.value->>'operation_class' = 'resource_state'
  AND sample ? 'correlation_ref'
 ORDER BY sample->>'recorded_at' DESC, profile.key DESC
 LIMIT %(limit)s
"""

AGENT_OBSERVATION_ACTIVITY_SQL: Final = """
SELECT key, value, updated_at
  FROM state_kv
 WHERE key LIKE 'observation-campaign:source:%%'
 ORDER BY value->>'completed_at' DESC NULLS LAST, key DESC
 LIMIT %(limit)s
"""

KPI_SAMPLE_SQL: Final = """
SELECT seq, action_kind, mode, entry, created_at
  FROM audit_log
 ORDER BY seq DESC
 LIMIT %(limit)s
"""

LLM_USAGE_SUMMARIES_SQL: Final = """
WITH filtered AS (
    SELECT occurred_at, correlation_id, model_key, mode, usage_scope,
           prompt_tokens, completion_tokens
      FROM llm_invocation
     WHERE occurred_at >= %(range_start)s
       AND occurred_at < %(range_end)s
), summaries AS (
    SELECT 'total' AS group_kind, 'total' AS group_key,
           COUNT(*) AS invocations,
           COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
           COALESCE(SUM(completion_tokens), 0) AS completion_tokens
      FROM filtered
    UNION ALL
    SELECT 'chat', 'chat', COUNT(*),
           COALESCE(SUM(prompt_tokens), 0), COALESCE(SUM(completion_tokens), 0)
      FROM filtered WHERE usage_scope = 'operator_chat'
    UNION ALL
    SELECT 'scope', usage_scope, COUNT(*), SUM(prompt_tokens), SUM(completion_tokens)
      FROM filtered GROUP BY usage_scope
    UNION ALL
    SELECT 'model', model_key, COUNT(*), SUM(prompt_tokens), SUM(completion_tokens)
      FROM filtered GROUP BY model_key
    UNION ALL
    SELECT 'chat_model', model_key, COUNT(*), SUM(prompt_tokens), SUM(completion_tokens)
      FROM filtered WHERE usage_scope = 'operator_chat' GROUP BY model_key
    UNION ALL
    SELECT 'mode', mode, COUNT(*), SUM(prompt_tokens), SUM(completion_tokens)
      FROM filtered GROUP BY mode
    UNION ALL
    SELECT 'hour', TO_CHAR(
               DATE_TRUNC('hour', occurred_at AT TIME ZONE 'UTC'),
               'YYYY-MM-DD"T"HH24:MI:SS"Z"'
           ), COUNT(*), SUM(prompt_tokens), SUM(completion_tokens)
      FROM filtered GROUP BY DATE_TRUNC('hour', occurred_at AT TIME ZONE 'UTC')
    UNION ALL
    SELECT 'day', TO_CHAR(
               DATE_TRUNC('day', occurred_at AT TIME ZONE 'UTC'), 'YYYY-MM-DD'
           ), COUNT(*), SUM(prompt_tokens), SUM(completion_tokens)
      FROM filtered GROUP BY DATE_TRUNC('day', occurred_at AT TIME ZONE 'UTC')
    UNION ALL
    SELECT 'month', TO_CHAR(
               DATE_TRUNC('month', occurred_at AT TIME ZONE 'UTC'), 'YYYY-MM'
           ), COUNT(*), SUM(prompt_tokens), SUM(completion_tokens)
      FROM filtered GROUP BY DATE_TRUNC('month', occurred_at AT TIME ZONE 'UTC')
)
SELECT group_kind, group_key, invocations, prompt_tokens, completion_tokens
  FROM summaries
 ORDER BY group_kind, group_key
"""

LLM_USAGE_CONVERSATIONS_SQL: Final = """
WITH grouped AS (
    SELECT correlation_id AS group_key, COUNT(*) AS invocations,
           SUM(prompt_tokens) AS prompt_tokens,
           SUM(completion_tokens) AS completion_tokens
      FROM llm_invocation
     WHERE occurred_at >= %(range_start)s
       AND occurred_at < %(range_end)s
     GROUP BY correlation_id
), counted AS (
    SELECT grouped.*, COUNT(*) OVER() AS conversation_count FROM grouped
)
SELECT group_key, invocations, prompt_tokens, completion_tokens, conversation_count
  FROM counted
 ORDER BY group_key
 LIMIT %(fetch)s
"""

LLM_USAGE_RECORDS_SQL: Final = """
SELECT occurred_at, correlation_id, capability_id, model_key, tier, mode,
       usage_scope, prompt_tokens, completion_tokens,
       COUNT(*) OVER() AS record_count
  FROM llm_invocation
 WHERE occurred_at >= %(range_start)s
   AND occurred_at < %(range_end)s
 ORDER BY occurred_at DESC, invocation_id DESC
 LIMIT %(fetch)s
"""

HIL_COUNT_SQL: Final = """
SELECT COUNT(*) AS total_count,
       COUNT(*) FILTER (WHERE NOT (
            jsonb_typeof(value->'approval_id') = 'string'
        AND TRIM(value->>'approval_id') <> ''
        AND jsonb_typeof(value->'parked_at') = 'string'
        AND TRIM(value->>'parked_at') <> ''
        AND jsonb_typeof(value#>'{action,event_id}') = 'string'
        AND TRIM(value#>>'{action,event_id}') <> ''
        AND (
             (jsonb_typeof(value->'idempotency_key') = 'string'
              AND TRIM(value->>'idempotency_key') <> '')
          OR (jsonb_typeof(value#>'{action,idempotency_key}') = 'string'
              AND TRIM(value#>>'{action,idempotency_key}') <> '')
        )
       )) AS unprojectable_count
  FROM state_kv
 WHERE key LIKE %(key_pattern)s
   AND value->>'status' = 'pending'
   AND (value#>>'{approval_context,expires_at}' IS NULL
       OR CASE
        WHEN value#>>'{approval_context,expires_at}' ~
          '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
        THEN (value#>>'{approval_context,expires_at}')::timestamptz
          > CURRENT_TIMESTAMP
        ELSE FALSE
       END)
"""

HIL_PAGE_SQL: Final = """
SELECT value, updated_at, COUNT(*) OVER() AS total_count
  FROM state_kv
 WHERE key LIKE %(key_pattern)s
   AND value->>'status' = 'pending'
   AND (value#>>'{approval_context,expires_at}' IS NULL
       OR CASE
        WHEN value#>>'{approval_context,expires_at}' ~
          '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
        THEN (value#>>'{approval_context,expires_at}')::timestamptz
          > CURRENT_TIMESTAMP
        ELSE FALSE
       END)
   AND (%(search)s::text IS NULL OR CONCAT_WS(
       ' ', value->>'approval_id', value->>'correlation_id',
       value->>'idempotency_key', value->>'action_type', value->>'rule_id',
       value#>>'{action,action_type}', value#>>'{action,action_id}',
       value#>>'{action,idempotency_key}', value#>>'{action,event_id}',
       value#>>'{action,target_resource_ref}', value#>>'{approval_context,reasons}',
       value#>>'{action,citing_rules}'
   ) ILIKE %(search_pattern)s::text)
 ORDER BY CASE
     WHEN value->>'parked_at' ~
          '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
     THEN (value->>'parked_at')::timestamptz
     ELSE updated_at
 END DESC
 LIMIT %(limit)s
"""

INCIDENT_PAGE_SQL: Final = """
WITH snapshot AS (
    SELECT COALESCE(%(snapshot_seq)s::bigint, MAX(seq), 0) AS snapshot_seq
      FROM audit_log
),
selected AS (
  SELECT projection.*,
           COUNT(*) OVER () AS matched_groups
    FROM operator_incident_projection AS projection
   WHERE projection.valid_from_seq <= (SELECT snapshot_seq FROM snapshot)
     AND (projection.valid_to_seq IS NULL
      OR projection.valid_to_seq > (SELECT snapshot_seq FROM snapshot))
     AND projection.has_incident_activity
     AND (%(before_seq)s::bigint IS NULL
      OR projection.last_seq < %(before_seq)s::bigint)
       AND (%(correlation_id)s::text IS NULL
      OR projection.correlation_id = %(correlation_id)s::text)
       AND (%(search)s::text IS NULL OR NOT EXISTS (
           SELECT 1
               FROM REGEXP_SPLIT_TO_TABLE(%(search)s::text, '[[:space:]]+')
                 AS search_token(token)
      WHERE STRPOS(projection.search_document, LOWER(search_token.token)) = 0
       ))
     AND (%(vertical)s::text IS NULL
      OR projection.projected_vertical = %(vertical)s::text)
     AND (%(severity)s::text IS NULL
      OR projection.projected_severity = %(severity)s::text)
       AND (%(status)s = 'all'
      OR (%(status)s = 'resolved'
        AND projection.projected_state IN ('resolved', 'closed'))
      OR (%(status)s = 'active'
        AND projection.projected_state NOT IN ('resolved', 'closed')))
   ORDER BY projection.last_seq DESC
     LIMIT %(fetch)s
)
SELECT (history_row->>'seq')::bigint AS seq,
     history_row->>'event_id' AS event_id,
     history_row->>'correlation_id' AS correlation_id,
     history_row->>'actor' AS actor,
     history_row->>'action_kind' AS action_kind,
     history_row->>'mode' AS mode,
     history_row->'entry' AS entry,
     history_row->>'previous_hash' AS previous_hash,
     history_row->>'entry_hash' AS entry_hash,
     (history_row->>'created_at')::timestamptz AS created_at,
     selected.correlation_id AS normalized_correlation_id,
     selected.last_seq AS group_last_seq,
     selected.group_history_count,
       selected.matched_groups,
       (SELECT snapshot_seq FROM snapshot) AS snapshot_seq
  FROM selected
 CROSS JOIN LATERAL JSONB_ARRAY_ELEMENTS(selected.history) AS expanded(history_row)
 ORDER BY selected.last_seq DESC, (history_row->>'seq')::bigint ASC
"""

INCIDENT_SNAPSHOT_SQL: Final = "SELECT COALESCE(MAX(seq), 0) AS snapshot_seq FROM audit_log"


def statement_identity(statement: str) -> str:
    """Name a statement for a failure record without emitting the statement text."""
    for name, value in globals().items():
        if name.endswith("_SQL") and value is statement:
            return name
    return "unregistered_statement"


__all__ = [
    "AGENT_INVENTORY_ACTIVITY_SQL",
    "AGENT_OBSERVATION_ACTIVITY_SQL",
    "AGENT_ONTOLOGY_ACTIVITY_SQL",
    "AGENT_READ_ACTIVITY_SQL",
    "AUDIT_PAGE_SQL",
    "HIL_COUNT_SQL",
    "HIL_PAGE_SQL",
    "INCIDENT_PAGE_SQL",
    "INCIDENT_SNAPSHOT_SQL",
    "KPI_SAMPLE_SQL",
    "LLM_USAGE_CONVERSATIONS_SQL",
    "LLM_USAGE_RECORDS_SQL",
    "LLM_USAGE_SUMMARIES_SQL",
    "statement_identity",
]

"""Bounded parameterized SQL for Operator Service read projections."""

from typing import Final

AUDIT_PAGE_SQL: Final = """
SELECT seq, event_id,
       COALESCE(
           CASE
               WHEN LOWER(BTRIM(correlation_id)) IN ('', 'none', 'null') THEN NULL
               ELSE BTRIM(correlation_id)
           END,
           CASE
               WHEN LOWER(BTRIM(entry->>'correlation_id')) IN ('', 'none', 'null') THEN NULL
               ELSE BTRIM(entry->>'correlation_id')
           END,
           NULLIF(BTRIM(entry#>>'{payload,correlation_id}'), ''),
           CASE
               WHEN action_kind = 'observation-campaign.source-transition'
               THEN NULLIF(BTRIM(entry->>'campaign_id'), '')
           END
       ) AS correlation_id,
       actor, action_kind, mode,
       entry, previous_hash, entry_hash, created_at
  FROM audit_log
 WHERE (%(cutoff)s::bigint IS NULL OR seq < %(cutoff)s::bigint)
   AND (
       %(correlation_id)s::text IS NULL
       OR COALESCE(
           CASE
               WHEN LOWER(BTRIM(correlation_id)) IN ('', 'none', 'null') THEN NULL
               ELSE BTRIM(correlation_id)
           END,
           CASE
               WHEN LOWER(BTRIM(entry->>'correlation_id')) IN ('', 'none', 'null') THEN NULL
               ELSE BTRIM(entry->>'correlation_id')
           END,
           NULLIF(BTRIM(entry#>>'{payload,correlation_id}'), ''),
           CASE
               WHEN action_kind = 'observation-campaign.source-transition'
               THEN NULLIF(BTRIM(entry->>'campaign_id'), '')
           END
       ) = %(correlation_id)s::text
   )
   AND (%(mode)s::text IS NULL OR mode = %(mode)s::text)
   AND (%(tier)s::text IS NULL
        OR lower(COALESCE(entry->>'tier', entry#>>'{payload,tier}')) = %(tier)s::text)
   AND (%(action_kind)s::text IS NULL OR action_kind = %(action_kind)s::text)
   AND (%(outcome)s::text IS NULL
        OR COALESCE(
            entry->>'gate_route', entry->>'outcome', entry->>'decision', entry->>'status',
            entry#>>'{payload,gate_route}', entry#>>'{payload,outcome}',
            entry#>>'{payload,decision}', entry#>>'{payload,status}',
            entry#>>'{payload,risk_verdict}'
        ) = %(outcome)s::text)
   AND (%(vertical)s::text IS NULL
        OR COALESCE(
            entry->>'vertical', entry->>'category', entry->>'domain',
            entry#>>'{payload,vertical}', entry#>>'{payload,category}',
            entry#>>'{payload,domain}'
        )
           = %(vertical)s::text)
   AND (%(window_days)s::integer IS NULL
        OR created_at >= CURRENT_TIMESTAMP - %(window_days)s::integer * interval '1 day')
   AND (%(from_seq)s::bigint IS NULL OR seq >= %(from_seq)s::bigint)
   AND (%(through_seq)s::bigint IS NULL OR seq <= %(through_seq)s::bigint)
 ORDER BY seq DESC
 LIMIT %(fetch)s
"""

AUDIT_SUMMARY_SQL: Final = """
WITH matching AS (
    SELECT seq, action_kind, entry
      FROM audit_log
     WHERE (
         %(correlation_id)s::text IS NULL
         OR COALESCE(
             CASE
                 WHEN LOWER(BTRIM(correlation_id)) IN ('', 'none', 'null') THEN NULL
                 ELSE BTRIM(correlation_id)
             END,
             CASE
                 WHEN LOWER(BTRIM(entry->>'correlation_id')) IN ('', 'none', 'null') THEN NULL
                 ELSE BTRIM(entry->>'correlation_id')
             END,
             NULLIF(BTRIM(entry#>>'{payload,correlation_id}'), ''),
             CASE
                 WHEN action_kind = 'observation-campaign.source-transition'
                 THEN NULLIF(BTRIM(entry->>'campaign_id'), '')
             END
         ) = %(correlation_id)s::text
     )
       AND (%(mode)s::text IS NULL OR mode = %(mode)s::text)
       AND (%(tier)s::text IS NULL
            OR lower(COALESCE(entry->>'tier', entry#>>'{payload,tier}'))
               = %(tier)s::text)
       AND (%(action_kind)s::text IS NULL OR action_kind = %(action_kind)s::text)
       AND (%(outcome)s::text IS NULL
            OR COALESCE(
                entry->>'gate_route', entry->>'outcome', entry->>'decision', entry->>'status',
                entry#>>'{payload,gate_route}', entry#>>'{payload,outcome}',
                entry#>>'{payload,decision}', entry#>>'{payload,status}',
                entry#>>'{payload,risk_verdict}'
            ) = %(outcome)s::text)
       AND (%(vertical)s::text IS NULL
            OR COALESCE(
                entry->>'vertical', entry->>'category', entry->>'domain',
                entry#>>'{payload,vertical}', entry#>>'{payload,category}',
                entry#>>'{payload,domain}'
            )
               = %(vertical)s::text)
       AND (%(window_days)s::integer IS NULL
            OR created_at >= CURRENT_TIMESTAMP - %(window_days)s::integer * interval '1 day')
       AND (%(from_seq)s::bigint IS NULL OR seq >= %(from_seq)s::bigint)
       AND (%(through_seq)s::bigint IS NULL OR seq <= %(through_seq)s::bigint)
),
scope_summary AS (
    SELECT COUNT(*) AS matching_record_count,
           COUNT(*) FILTER (
               WHERE LOWER(COALESCE(entry->>'stage', entry->>'phase', ''))
                         IN ('close', 'audit')
                  OR LOWER(COALESCE(entry->>'status', ''))
                         IN ('completed', 'succeeded', 'failed', 'cancelled',
                             'timed_out', 'closed', 'resolved')
                  OR LOWER(COALESCE(entry->>'outcome', ''))
                         IN ('completed', 'succeeded', 'failed', 'cancelled',
                             'timed_out', 'closed', 'resolved', 'rolled_back')
                  OR LOWER(COALESCE(entry#>>'{payload,status}', ''))
                         IN ('completed', 'succeeded', 'failed', 'cancelled',
                             'timed_out', 'closed', 'resolved')
                  OR LOWER(COALESCE(entry#>>'{payload,outcome}', ''))
                         IN ('completed', 'succeeded', 'failed', 'cancelled',
                             'timed_out', 'closed', 'resolved', 'rolled_back')
           ) AS terminal_record_count,
           COUNT(*) FILTER (
               WHERE action_kind LIKE 'hil.%%'
                  OR LOWER(COALESCE(
                      entry->>'gate_route', entry->>'decision', entry->>'outcome',
                      entry#>>'{payload,gate_route}', entry#>>'{payload,decision}',
                      entry#>>'{payload,outcome}', entry#>>'{payload,risk_verdict}', ''
                  )) = 'hil'
                  OR NULLIF(BTRIM(entry->>'approval_id'), '') IS NOT NULL
                  OR NULLIF(BTRIM(entry#>>'{payload,approval_id}'), '') IS NOT NULL
           ) AS human_review_record_count,
           COUNT(*) FILTER (
               WHERE NULLIF(BTRIM(entry->>'rollback_reference'), '') IS NOT NULL
                  OR NULLIF(BTRIM(entry#>>'{payload,rollback_reference}'), '') IS NOT NULL
                  OR LOWER(COALESCE(entry->>'outcome', '')) IN ('rollback', 'rolled_back')
                  OR LOWER(COALESCE(entry#>>'{payload,outcome}', ''))
                     IN ('rollback', 'rolled_back')
                  OR LOWER(COALESCE(entry->>'stage', entry->>'phase', '')) = 'rollback'
                  OR LOWER(action_kind) LIKE '%%rollback%%'
           ) AS rollback_record_count
      FROM matching
),
linked AS (
    SELECT seq, previous_hash, LAG(entry_hash) OVER (ORDER BY seq) AS prior_hash
      FROM audit_log
),
link_summary AS (
    SELECT COUNT(*) AS current_record_count,
           COUNT(*) FILTER (
               WHERE prior_hash IS NOT NULL
                 AND previous_hash IS DISTINCT FROM prior_hash
           ) AS current_link_gap_count
      FROM linked
),
readiness AS (
    SELECT value
      FROM state_kv
     WHERE key = 'runtime:startup-readiness:latest'
     LIMIT 1
)
SELECT CURRENT_TIMESTAMP AS observed_at,
       scope_summary.matching_record_count,
       scope_summary.terminal_record_count,
       scope_summary.human_review_record_count,
       scope_summary.rollback_record_count,
       link_summary.current_record_count,
       link_summary.current_link_gap_count,
       readiness.value AS readiness
  FROM scope_summary
 CROSS JOIN link_summary
  LEFT JOIN readiness ON TRUE
"""

AUDIT_TRACE_SQL: Final = """
WITH correlated_events AS (
    SELECT DISTINCT event_id
      FROM audit_log
     WHERE COALESCE(
               CASE
                   WHEN LOWER(BTRIM(correlation_id)) IN ('', 'none', 'null') THEN NULL
                   ELSE BTRIM(correlation_id)
               END,
               CASE
                   WHEN LOWER(BTRIM(entry->>'correlation_id')) IN ('', 'none', 'null') THEN NULL
                   ELSE BTRIM(entry->>'correlation_id')
               END,
               NULLIF(BTRIM(entry#>>'{payload,correlation_id}'), ''),
               CASE
                   WHEN action_kind = 'observation-campaign.source-transition'
                   THEN NULLIF(BTRIM(entry->>'campaign_id'), '')
               END
           ) = %(correlation_id)s::text
       AND event_id IS NOT NULL
),
bounded AS (
    SELECT seq, event_id,
           COALESCE(
               CASE
                   WHEN LOWER(BTRIM(correlation_id)) IN ('', 'none', 'null') THEN NULL
                   ELSE BTRIM(correlation_id)
               END,
               CASE
                   WHEN LOWER(BTRIM(entry->>'correlation_id')) IN ('', 'none', 'null') THEN NULL
                   ELSE BTRIM(entry->>'correlation_id')
               END,
               NULLIF(BTRIM(entry#>>'{payload,correlation_id}'), ''),
               CASE
                   WHEN action_kind = 'observation-campaign.source-transition'
                   THEN NULLIF(BTRIM(entry->>'campaign_id'), '')
               END
           ) AS correlation_id,
           actor, action_kind, mode,
           entry, previous_hash, entry_hash, created_at
      FROM audit_log
     WHERE COALESCE(
               CASE
                   WHEN LOWER(BTRIM(correlation_id)) IN ('', 'none', 'null') THEN NULL
                   ELSE BTRIM(correlation_id)
               END,
               CASE
                   WHEN LOWER(BTRIM(entry->>'correlation_id')) IN ('', 'none', 'null') THEN NULL
                   ELSE BTRIM(entry->>'correlation_id')
               END,
               NULLIF(BTRIM(entry#>>'{payload,correlation_id}'), ''),
               CASE
                   WHEN action_kind = 'observation-campaign.source-transition'
                   THEN NULLIF(BTRIM(entry->>'campaign_id'), '')
               END
           ) = %(correlation_id)s::text
        OR event_id IN (SELECT event_id FROM correlated_events)
     ORDER BY seq DESC
     LIMIT %(fetch)s
)
SELECT *
  FROM bounded
 ORDER BY seq ASC
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

BROWSER_EVIDENCE_WORKSPACE_SQL: Final = """
 WITH observation AS (
     SELECT CURRENT_TIMESTAMP AS observed_at
 ),
 classified AS (
     SELECT workspace.*,
            CASE
                WHEN workspace.legal_hold THEN 'held'
                WHEN workspace.expires_at <= observation.observed_at
                    THEN 'expired_pending_purge'
                WHEN workspace.expires_at
                     <= observation.observed_at + INTERVAL '168 hours'
                    THEN 'expiring'
                ELSE 'retained'
            END AS retention_state
       FROM operator_browser_evidence_workspace AS workspace
       CROSS JOIN observation
 ),
 filtered AS (
     SELECT classified.*,
            CASE
                WHEN prompt_injection_finding_count > 0 THEN 0
                WHEN retention_state = 'expired_pending_purge' THEN 1
                WHEN retention_state = 'expiring' THEN 2
                WHEN retention_state = 'held' THEN 3
                ELSE 4
            END AS attention_rank
       FROM classified
      WHERE (%(artifact_id)s::text IS NULL
             OR artifact_id = %(artifact_id)s::text)
        AND (
            %(host)s::text IS NULL
            OR (%(host_scope)s::text = 'requested'
                AND source_host = %(host)s::text)
            OR (%(host_scope)s::text = 'final'
                AND final_host = %(host)s::text)
            OR (%(host_scope)s::text = 'either'
                AND (source_host = %(host)s::text
                     OR final_host = %(host)s::text))
        )
        AND (%(policy_id)s::text IS NULL
             OR policy_id = %(policy_id)s::text)
        AND (%(policy_version)s::integer IS NULL
             OR policy_version = %(policy_version)s::integer)
        AND (%(captured_from)s::timestamptz IS NULL
             OR captured_at >= %(captured_from)s::timestamptz)
        AND (%(captured_before)s::timestamptz IS NULL
             OR captured_at < %(captured_before)s::timestamptz)
        AND (%(retention)s::text IS NULL
             OR retention_state = %(retention)s::text)
        AND (
            %(finding)s::text IS NULL
            OR (%(finding)s::text = 'present'
                AND prompt_injection_finding_count > 0)
            OR (%(finding)s::text = 'clear'
                AND prompt_injection_finding_count = 0)
        )
        AND (%(custody_ref)s::text IS NULL
             OR chain_of_custody_audit_ref = %(custody_ref)s::text)
 ),
 matching AS (
     SELECT COUNT(*)::BIGINT AS matching_admitted_count,
            COALESCE(SUM(prompt_injection_finding_count), 0)::BIGINT
                AS security_finding_count,
            COUNT(*) FILTER (WHERE retention_state = 'held')::BIGINT
                AS legal_hold_count,
            COUNT(*) FILTER (WHERE retention_state = 'expiring')::BIGINT
                AS expiring_count,
            COUNT(*) FILTER (
                WHERE retention_state = 'expired_pending_purge'
            )::BIGINT AS expired_pending_purge_count,
            COUNT(*) FILTER (WHERE retention_state = 'retained')::BIGINT
                AS retained_count
       FROM filtered
 ),
 page AS (
     SELECT *
       FROM filtered
      WHERE (
          %(cursor_captured_at)s::timestamptz IS NULL
          OR (
              %(sort)s::text = 'attention'
              AND (
                  attention_rank > %(cursor_attention_rank)s::integer
                  OR (
                      attention_rank = %(cursor_attention_rank)s::integer
                      AND (
                          captured_at < %(cursor_captured_at)s::timestamptz
                          OR (
                              captured_at = %(cursor_captured_at)s::timestamptz
                              AND artifact_id < %(cursor_artifact_id)s::text
                          )
                      )
                  )
              )
          )
          OR (
              %(sort)s::text = 'newest'
              AND (
                  captured_at < %(cursor_captured_at)s::timestamptz
                  OR (
                      captured_at = %(cursor_captured_at)s::timestamptz
                      AND artifact_id < %(cursor_artifact_id)s::text
                  )
              )
          )
      )
      ORDER BY
          CASE WHEN %(sort)s::text = 'attention' THEN attention_rank ELSE 0 END,
          captured_at DESC,
          artifact_id DESC
      LIMIT %(fetch)s
 )
 SELECT observation.observed_at,
        summary.source_observed_at,
        summary.snapshot_total_count,
        summary.snapshot_admitted_count,
        (
            summary.withheld_invalid_metadata_count
            + summary.withheld_trust_invalid_count
            + summary.withheld_isolation_unverified_count
        )::BIGINT AS snapshot_withheld_count,
        summary.withheld_invalid_metadata_count,
        summary.withheld_trust_invalid_count,
        summary.withheld_isolation_unverified_count,
        matching.matching_admitted_count,
        matching.security_finding_count,
        matching.legal_hold_count,
        matching.expiring_count,
        matching.expired_pending_purge_count,
        matching.retained_count,
        page.artifact_id,
        page.policy_id,
        page.policy_version,
        page.source_host,
        page.final_host,
        page.captured_at,
        page.expires_at,
        page.selector_count,
        page.has_screenshot_digest,
        page.has_text_digest,
        page.has_snapshot_digest,
        page.redaction_count,
        page.browser_version,
        page.chain_of_custody_audit_ref,
        page.prompt_injection_finding_count,
        page.legal_hold,
        page.legal_hold_ref,
        page.legal_hold_at,
        page.retention_state,
        page.attention_rank,
        CASE
            WHEN page.custody_audit_uuid IS NULL
                THEN 'malformed'
            WHEN audit_match.match_count = 0 THEN 'missing'
            WHEN audit_match.match_count > 1 THEN 'ambiguous'
            WHEN audit_match.audit_sequence > 9007199254740991
                THEN 'unsupported_sequence'
            ELSE 'exact'
        END AS audit_link_state,
        CASE
            WHEN audit_match.match_count = 1
                 AND audit_match.audit_sequence <= 9007199254740991
                THEN audit_match.audit_sequence::TEXT
            ELSE NULL
        END AS audit_sequence,
        CASE
            WHEN audit_match.match_count = 1
                 AND audit_match.audit_sequence <= 9007199254740991
                 AND audit_match.correlation_id IS NOT NULL
                 AND length(audit_match.correlation_id) BETWEEN 1 AND 256
                 AND audit_match.correlation_id = BTRIM(audit_match.correlation_id)
                 AND audit_match.correlation_id !~ '[[:cntrl:]]'
                 AND OCTET_LENGTH(audit_match.correlation_id)
                     = length(audit_match.correlation_id)
                THEN audit_match.correlation_id
            ELSE NULL
        END AS audit_correlation_id
   FROM observation
   CROSS JOIN operator_browser_evidence_workspace_summary AS summary
   CROSS JOIN matching
   LEFT JOIN page ON TRUE
   LEFT JOIN LATERAL (
       SELECT COUNT(*)::INTEGER AS match_count,
              MIN(audit.seq) AS audit_sequence,
              MIN(audit.correlation_id) AS correlation_id
         FROM audit_log AS audit
        WHERE page.artifact_id IS NOT NULL
           AND audit.event_id = page.custody_audit_uuid
          AND audit.actor = 'fdai.browser_evidence'
          AND audit.action_kind = 'browser_evidence.capture'
          AND audit.entry->>'content_digest'
              = SUBSTRING(page.artifact_id FROM 8)
          AND audit.entry->>'untrusted' = 'true'
          AND audit.entry->>'can_authorize_action' = 'false'
   ) AS audit_match ON TRUE
  ORDER BY
      CASE WHEN %(sort)s::text = 'attention' THEN page.attention_rank ELSE 0 END,
      page.captured_at DESC,
      page.artifact_id DESC
"""

AGENT_INVENTORY_ACTIVITY_SQL: Final = """
WITH recent AS MATERIALIZED (
    SELECT id, status, source, observation_kind, started_at,
           completed_at, promoted_at, failure_code,
           resource_count, link_count
      FROM inventory_snapshot
     ORDER BY started_at DESC, id DESC
     LIMIT %(limit)s
),
resource_counts AS (
    SELECT resource.snapshot_id, COUNT(resource.resource_type) AS resource_count
      FROM inventory_snapshot_resource AS resource
      JOIN recent ON recent.id = resource.snapshot_id
       AND recent.status IN ('active', 'superseded')
       AND recent.resource_count IS NULL
     GROUP BY resource.snapshot_id
),
link_counts AS (
    SELECT link.snapshot_id, COUNT(*) AS link_count
      FROM inventory_snapshot_link AS link
      JOIN recent ON recent.id = link.snapshot_id
       AND recent.status IN ('active', 'superseded')
       AND recent.link_count IS NULL
     GROUP BY link.snapshot_id
)
SELECT recent.id, recent.status, recent.source, recent.observation_kind,
       recent.started_at, recent.completed_at, recent.promoted_at,
       recent.failure_code,
       COALESCE(recent.resource_count, resource_counts.resource_count, 0) AS resource_count,
       COALESCE(recent.link_count, link_counts.link_count, 0) AS link_count
  FROM recent
  LEFT JOIN resource_counts ON resource_counts.snapshot_id = recent.id
  LEFT JOIN link_counts ON link_counts.snapshot_id = recent.id
 ORDER BY recent.started_at DESC, recent.id DESC
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

ROUTING_SAMPLE_SQL: Final = """
SELECT seq, action_kind, mode, entry, created_at
  FROM audit_log
 WHERE action_kind = 'measurement.control_loop.v1'
   AND seq <= %(cutoff_seq)s
   AND created_at >= CURRENT_TIMESTAMP - interval '30 days'
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

_HIL_DECISIONABLE_SQL: Final = """
   AND jsonb_typeof(value->'submitter_oid') = 'string'
   AND TRIM(value->>'submitter_oid') <> ''
   AND jsonb_typeof(value->'request_fingerprint') = 'string'
   AND TRIM(value->>'request_fingerprint') <> ''
   AND jsonb_typeof(value#>'{approval_context,expires_at}') = 'string'
   AND CASE
       WHEN value#>>'{approval_context,expires_at}' ~
         '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
       THEN (value#>>'{approval_context,expires_at}')::timestamptz
         > CURRENT_TIMESTAMP
       ELSE FALSE
   END
   AND (
       NOT (value ? 'metadata')
       OR (
           jsonb_typeof(value->'metadata') = 'object'
           AND value#>>'{metadata,decision_route}' IN ('action', 'workflow')
           AND (
               value#>>'{metadata,decision_route}' <> 'workflow'
               OR (
                   jsonb_typeof(value#>'{metadata,required_role}') = 'string'
                   AND TRIM(value#>>'{metadata,required_role}') <> ''
               )
           )
       )
   )
"""

HIL_COUNT_SQL: Final = """
SELECT COUNT(*) AS total_count,
       COUNT(*) FILTER (WHERE NOT COALESCE((
            jsonb_typeof(park.approval_id) = 'string'
        AND TRIM(park.approval_id #>> '{}') <> ''
        AND jsonb_typeof(park.parked_at) = 'string'
        AND TRIM(park.parked_at #>> '{}') <> ''
        AND jsonb_typeof(park.action->'event_id') = 'string'
        AND TRIM(park.action->>'event_id') <> ''
        AND (
             (jsonb_typeof(park.idempotency_key) = 'string'
              AND TRIM(park.idempotency_key #>> '{}') <> '')
          OR (jsonb_typeof(park.action->'idempotency_key') = 'string'
              AND TRIM(park.action->>'idempotency_key') <> '')
        )
       ), FALSE)) AS unprojectable_count
  FROM state_kv
 CROSS JOIN LATERAL jsonb_to_record(
      CASE WHEN jsonb_typeof(state_kv.value) = 'object'
           THEN state_kv.value ELSE '{}'::jsonb END
 ) AS park(
      approval_id jsonb,
      parked_at jsonb,
      idempotency_key jsonb,
      status jsonb,
      submitter_oid jsonb,
      request_fingerprint jsonb,
      approval_context jsonb,
      action jsonb,
      metadata jsonb
 )
 WHERE state_kv.key LIKE %(key_pattern)s ESCAPE E'\\\\'
   AND park.status #>> '{}' = 'pending'
   AND NOT EXISTS (
       SELECT 1
         FROM state_kv AS decision
        WHERE decision.key = 'operator-hil-decision:' || (park.approval_id #>> '{}')
   )
   AND jsonb_typeof(park.submitter_oid) = 'string'
   AND TRIM(park.submitter_oid #>> '{}') <> ''
   AND jsonb_typeof(park.request_fingerprint) = 'string'
   AND TRIM(park.request_fingerprint #>> '{}') <> ''
   AND jsonb_typeof(park.approval_context->'expires_at') = 'string'
   AND CASE
       WHEN park.approval_context->>'expires_at' ~
         '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
       THEN (park.approval_context->>'expires_at')::timestamptz
         > CURRENT_TIMESTAMP
       ELSE FALSE
   END
   AND (
       NOT (state_kv.value ? 'metadata')
       OR (
           jsonb_typeof(park.metadata) = 'object'
           AND park.metadata->>'decision_route' IN ('action', 'workflow')
           AND (
               park.metadata->>'decision_route' <> 'workflow'
               OR (
                   jsonb_typeof(park.metadata->'required_role') = 'string'
                   AND TRIM(park.metadata->>'required_role') <> ''
               )
           )
       )
   )
"""

_HIL_PAGE_SQL_PREFIX: Final = """
SELECT value, updated_at,
       EXISTS (
           SELECT 1
             FROM operator_incident_projection AS incident
            WHERE incident.valid_to_seq IS NULL
              AND incident.has_incident_activity
              AND incident.has_canonical_incident
              AND incident.correlation_id =
                  NULLIF(BTRIM(state_kv.value->>'correlation_id'), '')
       ) AS incident_available,
       COUNT(*) OVER() AS total_count
  FROM state_kv
 WHERE key LIKE %(key_pattern)s ESCAPE E'\\\\'
   AND value->>'status' = 'pending'
   AND NOT EXISTS (
       SELECT 1
         FROM state_kv AS decision
        WHERE decision.key = 'operator-hil-decision:' || (state_kv.value->>'approval_id')
   )
"""
_HIL_PAGE_SQL_SUFFIX: Final = """
  AND (%(search)s::text IS NULL OR CONCAT_WS(
       ' ', value->>'approval_id', value->>'correlation_id',
       value->>'idempotency_key', value->>'action_type', value->>'rule_id',
       value#>>'{action,action_type}', value#>>'{action,action_id}',
       value#>>'{action,idempotency_key}', value#>>'{action,event_id}',
       value#>>'{action,target_resource_ref}', value#>>'{approval_context,reasons}',
       value#>>'{action,citing_rules}'
  ) ILIKE %(search_pattern)s::text ESCAPE E'\\\\')
 ORDER BY CASE
     WHEN value->>'parked_at' ~
          '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
     THEN (value->>'parked_at')::timestamptz
     ELSE updated_at
 END DESC
 LIMIT %(limit)s
"""

# These statements compose only static module literals; runtime values remain bound parameters.
HIL_PAGE_SQL: Final = (  # noqa: S608
    _HIL_PAGE_SQL_PREFIX + _HIL_DECISIONABLE_SQL + _HIL_PAGE_SQL_SUFFIX
)

INCIDENT_PAGE_SQL: Final = """
WITH snapshot AS (
    SELECT COALESCE(%(snapshot_seq)s::bigint, MAX(seq), 0) AS snapshot_seq
      FROM audit_log
),
selected AS (
  SELECT projection.*,
           canonical_open.correlation_keys AS canonical_correlation_keys,
           COUNT(*) OVER () AS matched_groups
    FROM operator_incident_projection AS projection
    LEFT JOIN LATERAL (
        SELECT opened.entry->'correlation_keys' AS correlation_keys
          FROM audit_log AS opened
         WHERE opened.seq <= (SELECT snapshot_seq FROM snapshot)
           AND opened.entry->>'kind' = 'incident.open'
            AND NULLIF(BTRIM(opened.entry->>'incident_id'), '')
                = projection.canonical_incident_id
           AND COALESCE(
               NULLIF(BTRIM(opened.correlation_id), ''),
               NULLIF(BTRIM(opened.entry->>'correlation_id'), '')
           ) = projection.correlation_id
         ORDER BY opened.seq DESC
         LIMIT 1
    ) AS canonical_open ON TRUE
   WHERE projection.valid_from_seq <= (SELECT snapshot_seq FROM snapshot)
     AND (projection.valid_to_seq IS NULL
      OR projection.valid_to_seq > (SELECT snapshot_seq FROM snapshot))
     AND projection.has_incident_activity
    AND projection.has_canonical_incident
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
    selected.canonical_incident_id,
    selected.canonical_incident_number,
    selected.canonical_ticket_id,
    selected.canonical_opened_at,
    selected.canonical_correlation_keys,
    selected.projected_state AS canonical_lifecycle_state,
     selected.last_seq AS group_last_seq,
     selected.group_history_count,
       selected.matched_groups,
       (SELECT snapshot_seq FROM snapshot) AS snapshot_seq
  FROM selected
 CROSS JOIN LATERAL JSONB_ARRAY_ELEMENTS(selected.history) AS expanded(history_row)
 ORDER BY selected.last_seq DESC, (history_row->>'seq')::bigint ASC
"""

INCIDENT_CURRENT_PAGE_SQL: Final = INCIDENT_PAGE_SQL.replace(
    "projection.valid_from_seq <= (SELECT snapshot_seq FROM snapshot)\n"
    "     AND (projection.valid_to_seq IS NULL\n"
    "      OR projection.valid_to_seq > (SELECT snapshot_seq FROM snapshot))",
    "projection.valid_to_seq IS NULL",
)

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
    "AUDIT_SUMMARY_SQL",
    "AUDIT_TRACE_SQL",
    "HIL_COUNT_SQL",
    "HIL_PAGE_SQL",
    "INCIDENT_CURRENT_PAGE_SQL",
    "INCIDENT_PAGE_SQL",
    "INCIDENT_SNAPSHOT_SQL",
    "KPI_SAMPLE_SQL",
    "LLM_USAGE_CONVERSATIONS_SQL",
    "LLM_USAGE_RECORDS_SQL",
    "LLM_USAGE_SUMMARIES_SQL",
    "statement_identity",
]

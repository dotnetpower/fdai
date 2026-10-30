"""Principal-scoped conversation list over legacy rows and the semantic-turn journal.

A chat turn is journaled as an ``operator.semantic_turn`` request keyed by its session. The
history list names each session once, so a conversation stays discoverable after the browser
cache is gone. A session that also has a legacy conversation record keeps that record.
"""

from __future__ import annotations

_LEGACY = (
    "SELECT record.conversation_id, record.channel_id, record.started_at,"
    " record.last_active, record.status,"
    " (SELECT turn.turn_id FROM conversation_turn AS turn"
    "   WHERE turn.principal_id = record.principal_id"
    "     AND turn.conversation_id = record.conversation_id"
    "     AND turn.role = 'operator'"
    "   ORDER BY turn.turn_index DESC LIMIT 1) AS latest_operator_turn_id,"
    " (SELECT turn.content FROM conversation_turn AS turn"
    "   WHERE turn.principal_id = record.principal_id"
    "     AND turn.conversation_id = record.conversation_id"
    "     AND turn.role = 'operator'"
    "   ORDER BY turn.turn_index LIMIT 1) AS first_operator_question"
    " FROM conversation_record AS record"
    " WHERE record.principal_id = %(principal_id)s"
)

_SEMANTIC_CTES = """
WITH semantic_requests AS MATERIALIZED (
    SELECT key, value #>> '{envelope,semantic_turn,session_id}' AS session_id,
           (value ->> 'accepted_at')::timestamptz AS accepted_at
      FROM state_kv
     WHERE value ->> 'kind' = 'operator.semantic_turn'
       AND value ->> 'principal_id' = %(principal_id)s
), semantic_bounds AS (
    SELECT session_id, MIN(accepted_at) AS started_at, MAX(accepted_at) AS last_active
      FROM semantic_requests WHERE session_id IS NOT NULL GROUP BY session_id
), semantic_first AS (
    SELECT DISTINCT ON (session_id) session_id, key
      FROM semantic_requests WHERE session_id IS NOT NULL
     ORDER BY session_id, accepted_at, key
), semantic_last AS (
    SELECT DISTINCT ON (session_id) session_id, key
      FROM semantic_requests WHERE session_id IS NOT NULL
     ORDER BY session_id, accepted_at DESC, key DESC
)
"""
_SEMANTIC = """
SELECT bounds.session_id AS conversation_id, %(principal_id)s::text AS channel_id,
       bounds.started_at, bounds.last_active, 'active'::text AS status,
       last_body.value #>> '{envelope,semantic_turn,turn_id}' AS latest_operator_turn_id,
       first_body.value #>> '{envelope,semantic_turn,utterance}' AS first_operator_question
  FROM semantic_bounds AS bounds
  JOIN semantic_first AS first_request USING (session_id)
  JOIN semantic_last AS last_request USING (session_id)
  JOIN state_kv AS first_body ON first_body.key = first_request.key
  JOIN state_kv AS last_body ON last_body.key = last_request.key
 WHERE NOT EXISTS (
    SELECT 1 FROM conversation_record AS existing
     WHERE existing.principal_id = %(principal_id)s
       AND existing.conversation_id = bounds.session_id
 )
"""

_CURSOR = (
    " WHERE (merged.last_active, merged.conversation_id)"
    " < (%(before_last_active)s, %(before_conversation_id)s)"
)


def conversation_summary_sql(*, with_cursor: bool) -> str:
    """Return the newest-first page query; every value is a bound parameter."""

    # Fragments are module constants and every value is a bound parameter.
    parts = (
        _SEMANTIC_CTES,
        "SELECT * FROM (",
        _LEGACY,
        " UNION ALL ",
        _SEMANTIC,
        ") AS merged",
        _CURSOR if with_cursor else "",
        " ORDER BY merged.last_active DESC, merged.conversation_id DESC LIMIT %(limit)s",
    )
    return "".join(parts)


__all__ = ["conversation_summary_sql"]

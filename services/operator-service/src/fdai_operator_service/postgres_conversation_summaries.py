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

_SEMANTIC = (
    "SELECT journal.session_id AS conversation_id, journal.principal_id AS channel_id,"
    " MIN(journal.accepted_at) AS started_at, MAX(journal.accepted_at) AS last_active,"
    " 'active'::text AS status,"
    " (ARRAY_AGG(journal.turn_id ORDER BY journal.accepted_at DESC))[1]"
    "   AS latest_operator_turn_id,"
    " (ARRAY_AGG(journal.utterance ORDER BY journal.accepted_at))[1]"
    "   AS first_operator_question"
    " FROM ("
    "   SELECT request.value #>> '{envelope,semantic_turn,session_id}' AS session_id,"
    "          request.value ->> 'principal_id' AS principal_id,"
    "          (request.value ->> 'accepted_at')::timestamptz AS accepted_at,"
    "          request.value #>> '{envelope,semantic_turn,turn_id}' AS turn_id,"
    "          request.value #>> '{envelope,semantic_turn,utterance}' AS utterance"
    "     FROM state_kv AS request"
    "    WHERE request.value ->> 'kind' = 'operator.semantic_turn'"
    "      AND request.value ->> 'principal_id' = %(principal_id)s"
    " ) AS journal"
    " WHERE journal.session_id IS NOT NULL"
    "   AND NOT EXISTS (SELECT 1 FROM conversation_record AS existing"
    "     WHERE existing.principal_id = journal.principal_id"
    "       AND existing.conversation_id = journal.session_id)"
    " GROUP BY journal.session_id, journal.principal_id"
)

_CURSOR = (
    " WHERE (merged.last_active, merged.conversation_id)"
    " < (%(before_last_active)s, %(before_conversation_id)s)"
)


def conversation_summary_sql(*, with_cursor: bool) -> str:
    """Return the newest-first page query; every value is a bound parameter."""

    # Fragments are module constants and every value is a bound parameter.
    parts = (
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

"""PostgreSQL adapter for access-scoped conversation search."""

# ruff: noqa: S608 - predicates are module-controlled; all external values are bound parameters.

from __future__ import annotations

import json
import re
from time import perf_counter
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.persistence.postgres_user_context import PostgresUserContextStoreConfig
from fdai.shared.providers.conversation_search import (
    ConversationLineage,
    ConversationSearchContext,
    ConversationSearchHit,
    ConversationSearchMode,
    ConversationSearchPage,
    ConversationSearchQuery,
    ConversationSearchScope,
)
from fdai.shared.providers.conversation_search_text import (
    build_conversation_snippet,
    match_conversation_text,
    normalize_search_text,
    search_tokens,
)
from fdai.shared.providers.user_context import ConversationTurnRole

_RESULT_PREFIX = "conversation-search:"
_TURN_COLUMNS = (
    "turn.principal_id, turn.conversation_id, turn.turn_id, turn.turn_index, "
    "turn.role, turn.content, turn.recorded_at, turn.metadata, record.channel_id"
)


class PostgresConversationSearch:
    def __init__(self, *, config: PostgresUserContextStoreConfig) -> None:
        self._config = config

    async def search(
        self,
        *,
        scope: ConversationSearchScope,
        query: ConversationSearchQuery,
    ) -> ConversationSearchPage:
        started = perf_counter()
        clauses, params = _scope_clauses(scope)
        _append_query_filters(clauses, params, query)
        _append_match(clauses, params, query)
        candidate_limit = min(200, max(50, query.limit * 4))
        statement_params = (
            normalize_search_text(query.text),
            *params,
            candidate_limit,
        )
        statement = (
            f"SELECT {_TURN_COLUMNS}, "
            "GREATEST(similarity(turn.search_text, %s), 0) AS sql_rank "
            "FROM conversation_turn AS turn "
            "JOIN conversation_record AS record "
            "ON record.principal_id = turn.principal_id "
            "AND record.conversation_id = turn.conversation_id "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY sql_rank DESC, turn.recorded_at DESC, turn.turn_id "
            "LIMIT %s"
        )
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(statement, statement_params)  # noqa: S608
            rows = await cursor.fetchall()
            index_rows, index_bytes = await self._measure_scope(connection, scope, query)
        hits: list[ConversationSearchHit] = []
        for row in rows:
            match = match_conversation_text(str(row["content"]), query.text, query.mode)
            if match is None:
                continue
            hits.append(_row_hit(row, rank=match.rank, ranges=match.ranges))
        hits.sort(
            key=lambda item: (
                -item.rank,
                -item.recorded_at.timestamp(),
                item.conversation_id,
                item.turn_id,
            )
        )
        return ConversationSearchPage(
            hits=tuple(hits[: query.limit]),
            result_cap=query.limit,
            query_ms=(perf_counter() - started) * 1_000,
            index_rows=index_rows,
            index_bytes=index_bytes,
        )

    async def context(
        self,
        *,
        scope: ConversationSearchScope,
        result_id: str,
        before: int = 1,
        after: int = 1,
    ) -> ConversationSearchContext | None:
        _neighbor_cap(before, "before")
        _neighbor_cap(after, "after")
        clauses, params = _scope_clauses(scope)
        clauses.append("turn.turn_id = %s")
        params.append(_turn_id(result_id))
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_TURN_COLUMNS} FROM conversation_turn AS turn "
                "JOIN conversation_record AS record "
                "ON record.principal_id = turn.principal_id "
                "AND record.conversation_id = turn.conversation_id "
                f"WHERE {' AND '.join(clauses)}",  # noqa: S608
                tuple(params),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            before_rows = await self._neighbors(
                connection,
                scope=scope,
                conversation_id=str(row["conversation_id"]),
                turn_index=int(row["turn_index"]),
                direction="before",
                limit=before,
            )
            after_rows = await self._neighbors(
                connection,
                scope=scope,
                conversation_id=str(row["conversation_id"]),
                turn_index=int(row["turn_index"]),
                direction="after",
                limit=after,
            )
        return ConversationSearchContext(
            hit=_row_hit(row, rank=1.0),
            before=tuple(_row_hit(item, rank=0.0) for item in before_rows),
            after=tuple(_row_hit(item, rank=0.0) for item in after_rows),
        )

    async def lineage(
        self,
        *,
        scope: ConversationSearchScope,
        conversation_id: str,
    ) -> ConversationLineage | None:
        clauses, params = _record_scope_clauses(scope)
        clauses.append("record.conversation_id = %s")
        params.append(conversation_id)
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                "SELECT record.conversation_id, record.channel_id, record.started_at, "
                "record.last_active FROM conversation_record AS record "
                f"WHERE {' AND '.join(clauses)}",  # noqa: S608
                tuple(params),
            )
            record = await cursor.fetchone()
            if record is None:
                return None
            turns = await connection.execute(
                "SELECT turn_id FROM conversation_turn "
                "WHERE principal_id = %s AND conversation_id = %s "
                "ORDER BY turn_index LIMIT 1000",
                (scope.principal_id, conversation_id),
            )
            turn_ids = tuple(str(row["turn_id"]) for row in await turns.fetchall())
        return ConversationLineage(
            conversation_id=str(record["conversation_id"]),
            channel_id=str(record["channel_id"]),
            started_at=record["started_at"],
            last_active=record["last_active"],
            turn_ids=turn_ids,
        )

    async def rebuild_projection(self) -> dict[str, int | float]:
        """Rebuild the derived trigram index without rewriting source turns."""
        started = perf_counter()
        connection = await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
            autocommit=True,
        )
        try:
            await connection.execute("REINDEX INDEX CONCURRENTLY ix_conversation_turn_search_trgm")
            await connection.execute("ANALYZE conversation_turn")
            cursor = await connection.execute(
                "SELECT COUNT(*) AS row_count, "
                "COALESCE(SUM(octet_length(content)), 0) AS byte_count "
                "FROM conversation_turn"
            )
            row = await cursor.fetchone()
        finally:
            await connection.close()
        return {
            "index_rows": int(row["row_count"]) if row else 0,
            "index_bytes": int(row["byte_count"]) if row else 0,
            "duration_ms": (perf_counter() - started) * 1_000,
        }

    async def _neighbors(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        scope: ConversationSearchScope,
        conversation_id: str,
        turn_index: int,
        direction: str,
        limit: int,
    ) -> tuple[dict[str, Any], ...]:
        if limit == 0:
            return ()
        clauses, params = _scope_clauses(scope)
        clauses.append("turn.conversation_id = %s")
        params.append(conversation_id)
        if direction == "before":
            clauses.append("turn.turn_index < %s")
            ordering = "turn.turn_index DESC"
        else:
            clauses.append("turn.turn_index > %s")
            ordering = "turn.turn_index ASC"
        params.extend((turn_index, limit))
        cursor = await connection.execute(
            f"SELECT {_TURN_COLUMNS} FROM conversation_turn AS turn "
            "JOIN conversation_record AS record "
            "ON record.principal_id = turn.principal_id "
            "AND record.conversation_id = turn.conversation_id "
            f"WHERE {' AND '.join(clauses)} ORDER BY {ordering} LIMIT %s",  # noqa: S608
            tuple(params),
        )
        rows = list(await cursor.fetchall())
        if direction == "before":
            rows.reverse()
        return tuple(rows)

    async def _measure_scope(
        self,
        connection: psycopg.AsyncConnection[Any],
        scope: ConversationSearchScope,
        query: ConversationSearchQuery,
    ) -> tuple[int, int]:
        clauses, params = _scope_clauses(scope)
        if query.channels:
            clauses.append("record.channel_id = ANY(%s)")
            params.append(list(query.channels))
        if query.conversation_id:
            clauses.append("turn.conversation_id = %s")
            params.append(query.conversation_id)
        cursor = await connection.execute(
            "SELECT COUNT(*) AS row_count, "
            "COALESCE(SUM(octet_length(turn.content)), 0) AS byte_count "
            "FROM conversation_turn AS turn "
            "JOIN conversation_record AS record "
            "ON record.principal_id = turn.principal_id "
            "AND record.conversation_id = turn.conversation_id "
            f"WHERE {' AND '.join(clauses)}",  # noqa: S608
            tuple(params),
        )
        row = await cursor.fetchone()
        return (int(row["row_count"]), int(row["byte_count"])) if row else (0, 0)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _scope_clauses(scope: ConversationSearchScope) -> tuple[list[str], list[Any]]:
    clauses = ["turn.principal_id = %s"]
    params: list[Any] = [scope.principal_id]
    if scope.allowed_channels:
        clauses.append("record.channel_id = ANY(%s)")
        params.append(sorted(scope.allowed_channels))
    if scope.allowed_conversation_ids:
        clauses.append("turn.conversation_id = ANY(%s)")
        params.append(sorted(scope.allowed_conversation_ids))
    return clauses, params


def _record_scope_clauses(scope: ConversationSearchScope) -> tuple[list[str], list[Any]]:
    clauses = ["record.principal_id = %s"]
    params: list[Any] = [scope.principal_id]
    if scope.allowed_channels:
        clauses.append("record.channel_id = ANY(%s)")
        params.append(sorted(scope.allowed_channels))
    if scope.allowed_conversation_ids:
        clauses.append("record.conversation_id = ANY(%s)")
        params.append(sorted(scope.allowed_conversation_ids))
    return clauses, params


def _append_query_filters(
    clauses: list[str],
    params: list[Any],
    query: ConversationSearchQuery,
) -> None:
    if query.channels:
        clauses.append("record.channel_id = ANY(%s)")
        params.append(list(query.channels))
    if query.roles:
        clauses.append("turn.role = ANY(%s)")
        params.append([role.value for role in query.roles])
    for clause, value in (
        ("turn.conversation_id = %s", query.conversation_id),
        ("turn.metadata ->> 'incident_id' = %s", query.incident_id),
        ("turn.metadata ->> 'correlation_id' = %s", query.correlation_id),
        ("turn.recorded_at > %s", query.recorded_after),
        ("turn.recorded_at < %s", query.recorded_before),
    ):
        if value is not None:
            clauses.append(clause)
            params.append(value)


def _append_match(
    clauses: list[str],
    params: list[Any],
    query: ConversationSearchQuery,
) -> None:
    normalized = normalize_search_text(query.text)
    if query.mode is ConversationSearchMode.PHRASE:
        clauses.append("turn.search_text LIKE %s ESCAPE '\\'")
        params.append(f"%{_escape_like(normalized)}%")
        return
    for token in search_tokens(normalized):
        if query.mode is ConversationSearchMode.PREFIX:
            clauses.append("turn.search_text ~ %s")
            params.append(r"(^|[^[:alnum:]_])" + re.escape(token))
        else:
            clauses.append("turn.search_text LIKE %s ESCAPE '\\'")
            params.append(f"%{_escape_like(token)}%")


def _row_hit(
    row: dict[str, Any],
    *,
    rank: float,
    ranges: tuple[Any, ...] = (),
) -> ConversationSearchHit:
    metadata = _metadata(row["metadata"])
    return ConversationSearchHit(
        result_id=f"{_RESULT_PREFIX}{row['turn_id']}",
        turn_id=str(row["turn_id"]),
        conversation_id=str(row["conversation_id"]),
        channel_id=str(row["channel_id"]),
        role=ConversationTurnRole(str(row["role"])),
        snippet=build_conversation_snippet(str(row["content"]), ranges),
        recorded_at=row["recorded_at"],
        rank=rank,
        incident_id=_optional_metadata(metadata, "incident_id"),
        correlation_id=_optional_metadata(metadata, "correlation_id"),
        evidence_refs=_evidence_refs(metadata.get("evidence_refs")),
    )


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _optional_metadata(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return str(value) if isinstance(value, str) and value.strip() else None


def _evidence_refs(value: Any) -> tuple[str, ...]:
    decoded: Any = value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(str(item) for item in decoded[:64] if isinstance(item, str) and item.strip())


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _turn_id(result_id: str) -> str:
    if not result_id.startswith(_RESULT_PREFIX) or len(result_id) <= len(_RESULT_PREFIX):
        raise ValueError("conversation search result id is invalid")
    return result_id[len(_RESULT_PREFIX) :]


def _neighbor_cap(value: int, name: str) -> None:
    if not 0 <= value <= 3:
        raise ValueError(f"{name} MUST be in [0, 3]")


__all__ = ["PostgresConversationSearch"]

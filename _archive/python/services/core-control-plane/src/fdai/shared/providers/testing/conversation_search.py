"""Deterministic search adapter over an authorized conversation history store."""

from __future__ import annotations

import json
from collections.abc import Sequence
from time import perf_counter

from fdai.shared.providers.conversation_search import (
    ConversationLineage,
    ConversationSearchContext,
    ConversationSearchHit,
    ConversationSearchPage,
    ConversationSearchQuery,
    ConversationSearchScope,
    ConversationTextRange,
)
from fdai.shared.providers.conversation_search_text import (
    build_conversation_snippet,
    match_conversation_text,
)
from fdai.shared.providers.user_context import (
    ConversationHistoryStore,
    ConversationRecord,
    ConversationTurnRecord,
)

_RESULT_PREFIX = "conversation-search:"


class InMemoryConversationSearch:
    def __init__(self, *, history: ConversationHistoryStore) -> None:
        self._history = history

    async def search(
        self,
        *,
        scope: ConversationSearchScope,
        query: ConversationSearchQuery,
    ) -> ConversationSearchPage:
        started = perf_counter()
        records = await self._authorized_records(scope)
        hits: list[ConversationSearchHit] = []
        index_rows = 0
        index_bytes = 0
        for conversation in records:
            if not _conversation_matches_scope(conversation, scope):
                continue
            if query.channels and conversation.channel_id not in query.channels:
                continue
            if query.conversation_id and conversation.conversation_id != query.conversation_id:
                continue
            turns = await self._history.list_turns(
                principal_id=scope.principal_id,
                conversation_id=conversation.conversation_id,
                limit=1_000,
            )
            for turn in turns:
                index_rows += 1
                index_bytes += len(turn.content.encode("utf-8"))
                if not _turn_matches_filters(turn, query):
                    continue
                matched = match_conversation_text(turn.content, query.text, query.mode)
                if matched is None:
                    continue
                hits.append(_hit(conversation, turn, rank=matched.rank, ranges=matched.ranges))
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
        turn_id = _turn_id(result_id)
        for conversation in await self._authorized_records(scope):
            if not _conversation_matches_scope(conversation, scope):
                continue
            turns = tuple(
                await self._history.list_turns(
                    principal_id=scope.principal_id,
                    conversation_id=conversation.conversation_id,
                    limit=1_000,
                )
            )
            for index, turn in enumerate(turns):
                if turn.turn_id != turn_id:
                    continue
                return ConversationSearchContext(
                    hit=_hit(conversation, turn, rank=1.0),
                    before=tuple(
                        _hit(conversation, item, rank=0.0)
                        for item in turns[max(0, index - before) : index]
                    ),
                    after=tuple(
                        _hit(conversation, item, rank=0.0)
                        for item in turns[index + 1 : index + 1 + after]
                    ),
                )
        return None

    async def lineage(
        self,
        *,
        scope: ConversationSearchScope,
        conversation_id: str,
    ) -> ConversationLineage | None:
        conversation = await self._history.get_conversation(
            principal_id=scope.principal_id,
            conversation_id=conversation_id,
        )
        if conversation is None or not _conversation_matches_scope(conversation, scope):
            return None
        turns = await self._history.list_turns(
            principal_id=scope.principal_id,
            conversation_id=conversation_id,
            limit=1_000,
        )
        return ConversationLineage(
            conversation_id=conversation.conversation_id,
            channel_id=conversation.channel_id,
            started_at=conversation.started_at,
            last_active=conversation.last_active,
            turn_ids=tuple(turn.turn_id for turn in turns),
        )

    async def _authorized_records(
        self, scope: ConversationSearchScope
    ) -> Sequence[ConversationRecord]:
        return await self._history.list_conversations(
            principal_id=scope.principal_id,
            limit=1_000,
        )


def _conversation_matches_scope(
    conversation: ConversationRecord,
    scope: ConversationSearchScope,
) -> bool:
    if conversation.principal_id != scope.principal_id:
        return False
    if scope.allowed_channels and conversation.channel_id not in scope.allowed_channels:
        return False
    return not (
        scope.allowed_conversation_ids
        and conversation.conversation_id not in scope.allowed_conversation_ids
    )


def _turn_matches_filters(
    turn: ConversationTurnRecord,
    query: ConversationSearchQuery,
) -> bool:
    if query.roles and turn.role not in query.roles:
        return False
    if query.recorded_after and turn.recorded_at <= query.recorded_after:
        return False
    if query.recorded_before and turn.recorded_at >= query.recorded_before:
        return False
    if query.incident_id and turn.metadata.get("incident_id") != query.incident_id:
        return False
    return not (
        query.correlation_id and turn.metadata.get("correlation_id") != query.correlation_id
    )


def _hit(
    conversation: ConversationRecord,
    turn: ConversationTurnRecord,
    *,
    rank: float,
    ranges: tuple[ConversationTextRange, ...] = (),
) -> ConversationSearchHit:
    return ConversationSearchHit(
        result_id=f"{_RESULT_PREFIX}{turn.turn_id}",
        turn_id=turn.turn_id,
        conversation_id=turn.conversation_id,
        channel_id=conversation.channel_id,
        role=turn.role,
        snippet=build_conversation_snippet(turn.content, ranges),
        recorded_at=turn.recorded_at,
        rank=rank,
        incident_id=turn.metadata.get("incident_id"),
        correlation_id=turn.metadata.get("correlation_id"),
        evidence_refs=_evidence_refs(turn.metadata.get("evidence_refs")),
    )


def _evidence_refs(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(str(item) for item in decoded[:64] if isinstance(item, str) and item.strip())


def _turn_id(result_id: str) -> str:
    if not result_id.startswith(_RESULT_PREFIX) or len(result_id) <= len(_RESULT_PREFIX):
        raise ValueError("conversation search result id is invalid")
    return result_id[len(_RESULT_PREFIX) :]


def _neighbor_cap(value: int, name: str) -> None:
    if not 0 <= value <= 3:
        raise ValueError(f"{name} MUST be in [0, 3]")


__all__ = ["InMemoryConversationSearch"]

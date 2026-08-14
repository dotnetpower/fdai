"""Materialize principal-scoped conversation-search HTTP projections."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, cast

from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationQuery,
    ConversationResponse,
    JsonObject,
    JsonValue,
)

_SEARCH_OPERATION = "user.conversations.search"
_CONTEXT_OPERATION = "user.conversations.search_context"
_LINEAGE_OPERATION = "user.conversations.lineage"
_OPERATIONS = frozenset({_SEARCH_OPERATION, _CONTEXT_OPERATION, _LINEAGE_OPERATION})
_SEARCH_KEYS = frozenset(
    {
        "q",
        "mode",
        "limit",
        "channel",
        "role",
        "conversation_id",
        "incident_id",
        "correlation_id",
        "after",
        "before",
    }
)
_CONTEXT_KEYS = frozenset({"before", "after"})
_ROLES = frozenset({"operator", "assistant", "tool", "system"})
_MODES = frozenset({"terms", "phrase", "prefix"})
_RESULT_PREFIX = "conversation-search:"
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


class ConversationSearchProjectionStore(Protocol):
    """Read raw rows from the authoritative conversation tables."""

    async def search_conversation_turns(
        self,
        *,
        principal_id: str,
        normalized_text: str,
        mode: str,
        tokens: tuple[str, ...],
        channels: tuple[str, ...],
        roles: tuple[str, ...],
        conversation_id: str | None,
        incident_id: str | None,
        correlation_id: str | None,
        recorded_after: datetime | None,
        recorded_before: datetime | None,
        candidate_limit: int,
    ) -> list[dict[str, Any]]: ...

    async def measure_conversation_turns(
        self,
        *,
        principal_id: str,
        channels: tuple[str, ...],
        conversation_id: str | None,
    ) -> dict[str, int]: ...

    async def read_conversation_search_context(
        self,
        *,
        principal_id: str,
        turn_id: str,
        before: int,
        after: int,
    ) -> list[dict[str, Any]]: ...

    async def read_conversation_lineage(
        self,
        *,
        principal_id: str,
        conversation_id: str,
    ) -> dict[str, Any] | None: ...


async def materialize_conversation_search(
    query: ConversationQuery,
    *,
    store: ConversationSearchProjectionStore,
) -> ConversationResponse | None:
    """Return one bounded search projection or ``None`` for another operation."""

    if query.operation not in _OPERATIONS:
        return None
    if query.operation == _SEARCH_OPERATION:
        return await _search(query, store=store)
    if query.operation == _CONTEXT_OPERATION:
        return await _context(query, store=store)
    return await _lineage(query, store=store)


async def _search(
    query: ConversationQuery,
    *,
    store: ConversationSearchProjectionStore,
) -> ConversationResponse:
    _only_keys(query.query, _SEARCH_KEYS)
    if query.path_params:
        raise _invalid("conversation search path parameters are not supported")
    text = _text(query.query, "q", maximum=256)
    normalized = _normalize(text)
    tokens = _tokens(normalized)
    if not tokens:
        raise _invalid("q MUST contain a letter or digit")
    mode = _choice(query.query, "mode", _MODES, default="terms")
    limit = _integer(query.query, "limit", default=20, minimum=1, maximum=50)
    channels = _text_values(query.query, "channel", maximum_count=16, maximum_chars=128)
    roles = _text_values(query.query, "role", maximum_count=4, maximum_chars=32)
    if any(role not in _ROLES for role in roles):
        raise _invalid("role is invalid")
    conversation_id = _optional_text(query.query, "conversation_id")
    incident_id = _optional_text(query.query, "incident_id")
    correlation_id = _optional_text(query.query, "correlation_id")
    recorded_after = _optional_datetime(query.query, "after")
    recorded_before = _optional_datetime(query.query, "before")
    if recorded_after is not None and recorded_before is not None:
        if recorded_after >= recorded_before:
            raise _invalid("after MUST be earlier than before")

    rows = await store.search_conversation_turns(
        principal_id=query.scope.subject_id,
        normalized_text=normalized,
        mode=mode,
        tokens=tokens,
        channels=channels,
        roles=roles,
        conversation_id=conversation_id,
        incident_id=incident_id,
        correlation_id=correlation_id,
        recorded_after=recorded_after,
        recorded_before=recorded_before,
        candidate_limit=min(200, max(50, limit * 4)),
    )
    hits: list[JsonObject] = []
    for row in rows:
        matched = _match(str(row.get("content", "")), normalized, mode, tokens)
        if matched is None:
            continue
        rank, ranges = matched
        hits.append(_hit(row, rank=rank, ranges=ranges))
    hits.sort(
        key=lambda item: (
            -_json_number(item, "rank"),
            -datetime.fromisoformat(str(item["recorded_at"])).timestamp(),
            str(item["conversation_id"]),
            str(item["turn_id"]),
        )
    )
    measurement = await store.measure_conversation_turns(
        principal_id=query.scope.subject_id,
        channels=channels,
        conversation_id=conversation_id,
    )
    body: JsonObject = {
        "hits": cast(list[JsonValue], hits[:limit]),
        "result_cap": limit,
        "index_rows": _non_negative_measurement(measurement, "index_rows"),
        "index_bytes": _non_negative_measurement(measurement, "index_bytes"),
    }
    return ConversationResponse(body=body)


async def _context(
    query: ConversationQuery,
    *,
    store: ConversationSearchProjectionStore,
) -> ConversationResponse:
    _only_keys(query.query, _CONTEXT_KEYS)
    result_id = _path_text(query, "result_id")
    if not result_id.startswith(_RESULT_PREFIX) or len(result_id) <= len(_RESULT_PREFIX):
        raise _invalid("conversation search result id is invalid")
    before = _integer(query.query, "before", default=1, minimum=0, maximum=3)
    after = _integer(query.query, "after", default=1, minimum=0, maximum=3)
    rows = await store.read_conversation_search_context(
        principal_id=query.scope.subject_id,
        turn_id=result_id[len(_RESULT_PREFIX) :],
        before=before,
        after=after,
    )
    target = next((row for row in rows if row.get("section") == "hit"), None)
    if target is None:
        raise _not_found()
    return ConversationResponse(
        body={
            "hit": _hit(target, rank=1.0),
            "before": [_hit(row, rank=0.0) for row in rows if row.get("section") == "before"],
            "after": [_hit(row, rank=0.0) for row in rows if row.get("section") == "after"],
        }
    )


async def _lineage(
    query: ConversationQuery,
    *,
    store: ConversationSearchProjectionStore,
) -> ConversationResponse:
    if query.query:
        raise _invalid("conversation lineage query parameters are not supported")
    conversation_id = _path_text(query, "conversation_id")
    row = await store.read_conversation_lineage(
        principal_id=query.scope.subject_id,
        conversation_id=conversation_id,
    )
    if row is None:
        raise _not_found()
    turn_ids = row.get("turn_ids")
    if not isinstance(turn_ids, Sequence) or isinstance(turn_ids, str | bytes):
        raise RuntimeError("conversation lineage turn ids are malformed")
    if len(turn_ids) > 1_000 or not all(isinstance(item, str) for item in turn_ids):
        raise RuntimeError("conversation lineage turn ids are malformed")
    return ConversationResponse(
        body={
            "conversation_id": _row_text(row, "conversation_id"),
            "channel_id": _row_text(row, "channel_id"),
            "started_at": _row_datetime(row, "started_at").isoformat(),
            "last_active": _row_datetime(row, "last_active").isoformat(),
            "turn_ids": list(turn_ids),
        }
    )


def _hit(
    row: Mapping[str, object],
    *,
    rank: float,
    ranges: tuple[tuple[int, int], ...] = (),
) -> JsonObject:
    content = _row_text(row, "content")
    snippet, highlights = _snippet(content, ranges)
    metadata = _metadata(row.get("metadata"))
    turn_id = _row_text(row, "turn_id")
    role = _row_text(row, "role")
    if role not in _ROLES:
        raise RuntimeError("conversation search role is malformed")
    evidence_refs = metadata.get("evidence_refs", [])
    if isinstance(evidence_refs, str):
        try:
            evidence_refs = json.loads(evidence_refs)
        except json.JSONDecodeError:
            evidence_refs = []
    if not isinstance(evidence_refs, list):
        evidence_refs = []
    return {
        "result_id": f"{_RESULT_PREFIX}{turn_id}",
        "turn_id": turn_id,
        "conversation_id": _row_text(row, "conversation_id"),
        "channel_id": _row_text(row, "channel_id"),
        "role": role,
        "snippet": {
            "text": snippet,
            "highlights": [{"start": start, "end": end} for start, end in highlights],
        },
        "recorded_at": _row_datetime(row, "recorded_at").isoformat(),
        "rank": rank,
        "incident_id": _metadata_text(metadata, "incident_id"),
        "correlation_id": _metadata_text(metadata, "correlation_id"),
        "evidence_refs": [
            item for item in evidence_refs[:64] if isinstance(item, str) and item.strip()
        ],
    }


def _match(
    content: str,
    normalized_query: str,
    mode: str,
    query_tokens: tuple[str, ...],
) -> tuple[float, tuple[tuple[int, int], ...]] | None:
    normalized_content = _normalize(content)
    content_tokens = _tokens(normalized_content)
    needles: tuple[str, ...]
    if mode == "phrase":
        matched = normalized_query in normalized_content
        needles = (normalized_query,)
    elif mode == "prefix":
        matched = all(
            any(token.startswith(prefix) for token in content_tokens) for prefix in query_tokens
        )
        needles = query_tokens
    else:
        matched = all(token in normalized_content for token in query_tokens)
        needles = query_tokens
    if not matched:
        return None
    ranges = _ranges(normalized_content, needles) if len(normalized_content) == len(content) else ()
    return min(1.0, len(ranges) / max(1, len(query_tokens))), ranges


def _snippet(
    content: str,
    ranges: tuple[tuple[int, int], ...],
) -> tuple[str, tuple[tuple[int, int], ...]]:
    if len(content) <= 500:
        return content, ranges
    center = ranges[0][0] if ranges else 0
    start = max(0, center - 150)
    end = min(len(content), start + 500)
    start = max(0, end - 500)
    return content[start:end], tuple(
        (max(item_start, start) - start, min(item_end, end) - start)
        for item_start, item_end in ranges
        if item_end > start and item_start < end
    )


def _ranges(content: str, needles: tuple[str, ...]) -> tuple[tuple[int, int], ...]:
    found = sorted(
        (start, start + len(needle)) for needle in needles if (start := content.find(needle)) >= 0
    )
    result: list[tuple[int, int]] = []
    for item in found:
        if result and item[0] < result[-1][1]:
            continue
        result.append(item)
    return tuple(result[:32])


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN.findall(value))


def _only_keys(value: Mapping[str, object], allowed: frozenset[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _invalid(f"unsupported query parameter: {unknown[0]}")


def _text(value: Mapping[str, object], key: str, *, maximum: int = 256) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip() or len(item) > maximum:
        raise _invalid(f"{key} MUST be bounded text")
    if any(ord(character) < 32 for character in item):
        raise _invalid(f"{key} MUST be bounded text")
    return item


def _optional_text(value: Mapping[str, object], key: str) -> str | None:
    return _text(value, key) if key in value else None


def _text_values(
    value: Mapping[str, object],
    key: str,
    *,
    maximum_count: int,
    maximum_chars: int,
) -> tuple[str, ...]:
    raw = value.get(key)
    if raw is None:
        return ()
    items = raw if isinstance(raw, list) else [raw]
    if not 1 <= len(items) <= maximum_count:
        raise _invalid(f"{key} contains too many values")
    result = tuple(_text({key: item}, key, maximum=maximum_chars) for item in items)
    if len(set(result)) != len(result):
        raise _invalid(f"{key} values MUST be unique")
    return result


def _choice(
    value: Mapping[str, object],
    key: str,
    allowed: frozenset[str],
    *,
    default: str,
) -> str:
    if key not in value:
        return default
    item = _text(value, key, maximum=32)
    if item not in allowed:
        raise _invalid(f"{key} is invalid")
    return item


def _integer(
    value: Mapping[str, object],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = value.get(key, str(default))
    if not isinstance(raw, str) or not raw.isascii() or not raw.isdigit():
        raise _invalid(f"{key} MUST be an integer")
    item = int(raw)
    if not minimum <= item <= maximum:
        raise _invalid(f"{key} MUST be in [{minimum}, {maximum}]")
    return item


def _optional_datetime(value: Mapping[str, object], key: str) -> datetime | None:
    if key not in value:
        return None
    raw = _text(value, key, maximum=64)
    try:
        result = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise _invalid(f"{key} MUST be an ISO 8601 timestamp") from exc
    if result.tzinfo is None:
        raise _invalid(f"{key} MUST include timezone")
    return result


def _path_text(query: ConversationQuery, key: str) -> str:
    if set(query.path_params) != {key}:
        raise _invalid(f"{key} path parameter is required")
    return _text(query.path_params, key)


def _metadata(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, dict):
            return {str(key): item for key, item in decoded.items()}
    return {}


def _metadata_text(value: Mapping[str, object], key: str) -> str | None:
    item = value.get(key)
    return item if isinstance(item, str) and item.strip() and len(item) <= 256 else None


def _row_text(row: Mapping[str, object], key: str) -> str:
    item = row.get(key)
    if not isinstance(item, str) or not item or len(item) > 600:
        raise RuntimeError(f"conversation search {key} is malformed")
    return item


def _row_datetime(row: Mapping[str, object], key: str) -> datetime:
    item = row.get(key)
    if not isinstance(item, datetime) or item.tzinfo is None:
        raise RuntimeError(f"conversation search {key} is malformed")
    return item


def _non_negative_measurement(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise RuntimeError(f"conversation search {key} is malformed")
    return item


def _json_number(value: Mapping[str, JsonValue], key: str) -> float:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int | float):
        raise RuntimeError(f"conversation search {key} is malformed")
    return float(item)


def _invalid(message: str) -> ConversationBoundaryError:
    return ConversationBoundaryError(400, "invalid_request", message)


def _not_found() -> ConversationBoundaryError:
    return ConversationBoundaryError(
        404,
        "not_found",
        "conversation search resource is unavailable",
    )


__all__ = ["ConversationSearchProjectionStore", "materialize_conversation_search"]

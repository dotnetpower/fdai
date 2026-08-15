"""Materialize principal-scoped user-context HTTP projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationQuery,
    ConversationResponse,
    JsonObject,
    JsonValue,
)

_CONTEXT_OPERATION = "user.context"
_PAGE_OPERATION = "user.conversations"
_OPERATIONS = frozenset({_CONTEXT_OPERATION, _PAGE_OPERATION})
_PAGE_KEYS = frozenset({"before_last_active", "before_conversation_id"})
_PAGE_SIZE = 50
_LIST_LIMIT = 200


class UserContextProjectionStore(Protocol):
    """Read raw rows from the authoritative user-context tables."""

    async def read_conversation_summaries(
        self,
        *,
        principal_id: str,
        before_last_active: datetime | None,
        before_conversation_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]: ...

    async def read_user_context_records(
        self,
        *,
        principal_id: str,
        limit: int,
    ) -> dict[str, list[dict[str, Any]]]: ...


async def materialize_user_context(
    query: ConversationQuery,
    *,
    store: UserContextProjectionStore,
) -> ConversationResponse | None:
    """Return one principal-scoped user-context projection or ``None`` for another operation."""

    if query.operation not in _OPERATIONS:
        return None
    if query.path_params:
        raise _invalid("user context path parameters are not supported")
    if query.operation == _PAGE_OPERATION:
        return ConversationResponse(body=await _page(query, store=store))
    _only_keys(query.query, frozenset())
    records = await store.read_user_context_records(
        principal_id=query.scope.subject_id,
        limit=_LIST_LIMIT,
    )
    page = await _page(query, store=store)
    body: JsonObject = {
        "preference": _preference(records["preference"]),
        "memories": [_memory(row) for row in records["memories"]],
        "policies": [_policy(row) for row in records["policies"]],
        "subscriptions": [_subscription(row) for row in records["subscriptions"]],
        "briefing_runs": [_briefing_run(row) for row in records["briefing_runs"]],
        "scheduled_continuations": [
            _continuation(row) for row in records["scheduled_continuations"]
        ],
        "conversations": page["conversations"],
        "conversation_page": {
            "has_more": page["has_more"],
            "next_cursor": page["next_cursor"],
        },
    }
    return ConversationResponse(body=body)


async def _page(
    query: ConversationQuery,
    *,
    store: UserContextProjectionStore,
) -> dict[str, JsonValue]:
    if query.operation == _PAGE_OPERATION:
        _only_keys(query.query, _PAGE_KEYS)
        last_active = _optional_text(query.query, "before_last_active")
        conversation_id = _optional_text(query.query, "before_conversation_id")
    else:
        last_active = None
        conversation_id = None
    if (last_active is None) != (conversation_id is None):
        raise _invalid("conversation cursor MUST be complete")
    rows = await store.read_conversation_summaries(
        principal_id=query.scope.subject_id,
        before_last_active=None if last_active is None else _timestamp(last_active),
        before_conversation_id=conversation_id,
        limit=_PAGE_SIZE + 1,
    )
    has_more = len(rows) > _PAGE_SIZE
    visible = rows[:_PAGE_SIZE]
    summaries = [_conversation(row) for row in visible]
    cursor: JsonValue = None
    if has_more and summaries:
        newest = summaries[-1]
        cursor = {
            "last_active": newest["last_active"],
            "conversation_id": newest["conversation_id"],
        }
    return {
        "conversations": cast(list[JsonValue], summaries),
        "has_more": has_more,
        "next_cursor": cursor,
    }


def _conversation(row: Mapping[str, Any]) -> dict[str, JsonValue]:
    return {
        "conversation_id": _text(row, "conversation_id"),
        "channel_id": _text(row, "channel_id"),
        "started_at": _moment(row, "started_at"),
        "last_active": _moment(row, "last_active"),
        "status": _text(row, "status"),
        "latest_operator_turn_id": _optional_row_text(row, "latest_operator_turn_id"),
        "first_operator_question": _optional_row_text(row, "first_operator_question"),
    }


def _preference(rows: Sequence[Mapping[str, Any]]) -> JsonValue:
    if not rows:
        return None
    row = rows[0]
    return {
        "principal_id": _text(row, "principal_id"),
        "locale": _text(row, "locale"),
        "verbosity": _text(row, "verbosity"),
        "answer_detail": _text(row, "answer_detail"),
        "answer_format": _text(row, "answer_format"),
        "answer_preferences_enabled": _flag(row, "answer_preferences_enabled"),
        "answer_intent_detail": _text_mapping(row, "answer_intent_detail"),
        "answer_intent_format": _text_mapping(row, "answer_intent_format"),
        "timezone": _optional_row_text(row, "timezone"),
        "share_with_learner": _flag(row, "share_with_learner"),
        "revision": _count(row, "revision"),
    }


def _memory(row: Mapping[str, Any]) -> dict[str, JsonValue]:
    expires_at = row.get("expires_at")
    return {
        "memory_id": _text(row, "memory_id"),
        "category": _text(row, "category"),
        "body": _text(row, "body"),
        "source_turn_id": _text(row, "source_turn_id"),
        "created_at": _moment(row, "created_at"),
        "expires_at": None if expires_at is None else _moment(row, "expires_at"),
    }


def _policy(row: Mapping[str, Any]) -> dict[str, JsonValue]:
    briefing_spec = row.get("briefing_spec")
    return {
        "policy_id": _text(row, "policy_id"),
        "kind": _text(row, "kind"),
        "enabled": _flag(row, "enabled"),
        "revision": _count(row, "revision"),
        "source_turn_id": _text(row, "source_turn_id"),
        "briefing_spec": None if briefing_spec is None else _mapping(row, "briefing_spec"),
        "response_defaults": _text_mapping(row, "response_defaults"),
    }


def _subscription(row: Mapping[str, Any]) -> dict[str, JsonValue]:
    return {
        "subscription_id": _text(row, "subscription_id"),
        "name": _text(row, "name"),
        "cron_expression": _text(row, "cron_expression"),
        "timezone": _text(row, "timezone"),
        "enabled": _flag(row, "enabled"),
        "next_run_at": _moment(row, "next_run_at"),
        "spec": _mapping(row, "spec"),
        "revision": _count(row, "revision"),
    }


def _briefing_run(row: Mapping[str, Any]) -> dict[str, JsonValue]:
    return {
        "run_id": _text(row, "run_id"),
        "title": _text(row, "title"),
        "body_markdown": _text(row, "body_markdown"),
        "status": _text(row, "status"),
        "item_count": _count(row, "item_count"),
        "evidence_refs": _text_list(row, "evidence_refs"),
        "source_errors": _text_list(row, "source_errors"),
    }


def _continuation(row: Mapping[str, Any]) -> dict[str, JsonValue]:
    return {
        "anchor_id": _text(row, "anchor_id"),
        "task_id": _text(row, "task_id"),
        "run_id": _text(row, "run_id"),
        "owner_principal_id": _text(row, "owner_principal_id"),
        "scope_ref": _text(row, "scope_ref"),
        "mode": _text(row, "mode"),
        "origin": _mapping(row, "origin"),
        "result_digest": _text(row, "result_digest"),
        "result_summary": _text(row, "result_summary"),
        "evidence_refs": _text_list(row, "evidence_refs"),
        "observation_started_at": _moment(row, "observation_started_at"),
        "observation_ended_at": _moment(row, "observation_ended_at"),
        "created_at": _moment(row, "created_at"),
        "expires_at": _moment(row, "expires_at"),
        "state": _text(row, "state"),
    }


def _text(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise _malformed(field)
    return value


def _optional_row_text(row: Mapping[str, Any], field: str) -> JsonValue:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _malformed(field)
    return value


def _flag(row: Mapping[str, Any], field: str) -> bool:
    value = row.get(field)
    if not isinstance(value, bool):
        raise _malformed(field)
    return value


def _count(row: Mapping[str, Any], field: str) -> int:
    value = row.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _malformed(field)
    return value


def _moment(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, datetime):
        raise _malformed(field)
    return value.astimezone(UTC).isoformat()


def _mapping(row: Mapping[str, Any], field: str) -> JsonObject:
    value = row.get(field)
    if not isinstance(value, Mapping):
        raise _malformed(field)
    return {str(key): cast(JsonValue, item) for key, item in value.items()}


def _text_mapping(row: Mapping[str, Any], field: str) -> JsonObject:
    value = row.get(field)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise _malformed(field)
    entries: JsonObject = {}
    for key, item in value.items():
        if not isinstance(item, str):
            raise _malformed(field)
        entries[str(key)] = item
    return entries


def _text_list(row: Mapping[str, Any], field: str) -> list[JsonValue]:
    value = row.get(field)
    if value is None:
        return []
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise _malformed(field)
    items: list[JsonValue] = []
    for item in value:
        if not isinstance(item, str):
            raise _malformed(field)
        items.append(item)
    return items


def _only_keys(query: Mapping[str, JsonValue], allowed: frozenset[str]) -> None:
    unknown = sorted(set(query) - allowed)
    if unknown:
        raise _invalid(f"unsupported query parameter: {unknown[0]}")


def _optional_text(query: Mapping[str, JsonValue], key: str) -> str | None:
    value = query.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid(f"{key} is invalid")
    trimmed = value.strip()
    if not trimmed or len(trimmed) > 256:
        raise _invalid(f"{key} is invalid")
    return trimmed


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _invalid("before_last_active MUST be an ISO-8601 timestamp") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _invalid(message: str) -> ConversationBoundaryError:
    return ConversationBoundaryError(400, "invalid_request", message)


def _malformed(field: str) -> ConversationBoundaryError:
    return ConversationBoundaryError(
        503,
        "unavailable",
        f"authoritative user context record is malformed: {field}",
    )


__all__ = ["UserContextProjectionStore", "materialize_user_context"]

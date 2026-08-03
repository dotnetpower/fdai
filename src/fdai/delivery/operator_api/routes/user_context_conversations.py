"""Bounded principal-scoped conversation history pages."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from starlette.exceptions import HTTPException
from starlette.requests import Request

from fdai.shared.providers.user_context import ConversationHistoryStore

CONVERSATION_PAGE_SIZE = 100
_QUESTION_LIMIT = 512


@dataclass(frozen=True, slots=True)
class ConversationPage:
    conversations: tuple[dict[str, Any], ...]
    has_more: bool
    next_cursor: dict[str, str] | None


async def load_conversation_page(
    *,
    store: ConversationHistoryStore,
    principal_id: str,
    before_last_active: datetime | None = None,
    before_conversation_id: str | None = None,
) -> ConversationPage:
    records = await store.list_conversations(
        principal_id=principal_id,
        limit=CONVERSATION_PAGE_SIZE + 1,
        before_last_active=before_last_active,
        before_conversation_id=before_conversation_id,
    )
    retained = tuple(records[:CONVERSATION_PAGE_SIZE])
    conversation_ids = tuple(record.conversation_id for record in retained)
    latest_turn_ids = await store.latest_operator_turn_ids(
        principal_id=principal_id,
        conversation_ids=conversation_ids,
    )
    first_questions = await store.first_operator_questions(
        principal_id=principal_id,
        conversation_ids=conversation_ids,
        max_chars=_QUESTION_LIMIT,
    )
    conversations = tuple(
        {
            **_json(record),
            "latest_operator_turn_id": latest_turn_ids.get(record.conversation_id),
            "first_operator_question": first_questions.get(record.conversation_id),
        }
        for record in retained
    )
    has_more = len(records) > CONVERSATION_PAGE_SIZE
    last = retained[-1] if has_more and retained else None
    return ConversationPage(
        conversations=conversations,
        has_more=has_more,
        next_cursor={
            "last_active": last.last_active.isoformat(),
            "conversation_id": last.conversation_id,
        }
        if last is not None
        else None,
    )


def conversation_cursor(request: Request) -> tuple[datetime | None, str | None]:
    raw_time = request.query_params.get("before_last_active")
    conversation_id = request.query_params.get("before_conversation_id")
    if raw_time is None and conversation_id is None:
        return None, None
    if raw_time is None or not conversation_id:
        raise HTTPException(status_code=400, detail="conversation cursor is incomplete")
    try:
        observed_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="conversation cursor time is invalid") from exc
    if observed_at.tzinfo is None:
        raise HTTPException(
            status_code=400,
            detail="conversation cursor time MUST include timezone",
        )
    return observed_at, conversation_id


def page_json(page: ConversationPage) -> dict[str, Any]:
    return {
        "conversations": list(page.conversations),
        "has_more": page.has_more,
        "next_cursor": page.next_cursor,
    }


def _json(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json(item) for key, item in asdict(value).items()}
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value

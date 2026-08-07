"""Request boundary parsing for the chat SSE route."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Final

from starlette.exceptions import HTTPException
from starlette.requests import Request

from fdai.delivery.operator_api.application.conversation.request_preparation import (
    DEFAULT_CHAT_HISTORY_POLICY,
    AnswerPreferenceResolver,
    ChatContentRejectedError,
    ChatDocumentAccessDeniedError,
    ChatDocumentEvidenceResolver,
    ChatDocumentEvidenceUnavailableError,
    ChatHistoryCompressor,
    ChatHistoryPolicy,
    ChatRequestConflictError,
    ChatRequestPreparationInput,
    ContentPolicyReplayRequest,
    InvalidChatRequestError,
    ModelPreferenceResolver,
    PreparedChatStreamRequest,
    prepare_chat_request,
)
from fdai.shared.providers.user_context import ConversationHistoryStore

DEFAULT_MAX_CHAT_BODY_BYTES: Final[int] = 26 * 1024 * 1024
AuthorizeFn = Callable[[Request], Awaitable[str]]


async def read_chat_stream_body(
    request: Request,
    *,
    max_body_bytes: int,
) -> dict[str, Any]:
    declared_len = request.headers.get("content-length")
    if declared_len is not None:
        try:
            if int(declared_len) > max_body_bytes:
                raise HTTPException(status_code=413, detail="chat body too large")
        except ValueError:
            pass
    body_bytes = await request.body()
    if len(body_bytes) > max_body_bytes:
        raise HTTPException(status_code=413, detail="chat body too large")
    try:
        body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="chat body MUST be JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="chat body MUST be a JSON object")
    return body


async def prepare_chat_stream_request(
    request: Request,
    *,
    authorize: AuthorizeFn,
    model_preference_resolver: ModelPreferenceResolver | None,
    answer_preference_resolver: AnswerPreferenceResolver | None,
    document_evidence_resolver: ChatDocumentEvidenceResolver | None,
    conversation_history_store: ConversationHistoryStore | None,
    history_compressor: ChatHistoryCompressor,
    history_policy: ChatHistoryPolicy = DEFAULT_CHAT_HISTORY_POLICY,
    max_body_bytes: int,
) -> PreparedChatStreamRequest | ContentPolicyReplayRequest:
    """Authorize and parse HTTP before delegating application preparation."""

    user_id = await authorize(request)
    body = await read_chat_stream_body(request, max_body_bytes=max_body_bytes)
    try:
        return await prepare_chat_request(
            ChatRequestPreparationInput(principal_id=user_id, body=body),
            model_preference_resolver=model_preference_resolver,
            answer_preference_resolver=answer_preference_resolver,
            document_evidence_resolver=document_evidence_resolver,
            conversation_history_store=conversation_history_store,
            history_compressor=history_compressor,
            history_policy=history_policy,
        )
    except InvalidChatRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ChatContentRejectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ChatRequestConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChatDocumentAccessDeniedError as exc:
        raise HTTPException(status_code=403, detail="document reference access denied") from exc
    except ChatDocumentEvidenceUnavailableError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


__all__ = [
    "AuthorizeFn",
    "ContentPolicyReplayRequest",
    "DEFAULT_MAX_CHAT_BODY_BYTES",
    "prepare_chat_stream_request",
    "read_chat_stream_body",
]

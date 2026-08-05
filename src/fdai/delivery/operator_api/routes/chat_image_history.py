"""Persist validated chat images and serialize content-free turn metadata."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.delivery.conversation_images import (
    DEFAULT_CONVERSATION_IMAGE_RETENTION_DAYS,
    PENDING_CONVERSATION_IMAGE_RETENTION_MINUTES,
    ConversationImage,
    ConversationImageStore,
)
from fdai.delivery.operator_api.routes.chat_history import (
    append_operator_turn,
    ensure_conversation,
)
from fdai.delivery.operator_api.routes.chat_vision_evidence import VisionAttachment
from fdai.shared.providers.user_context import ConversationHistoryStore, ConversationTurnRecord

_LOG = logging.getLogger(__name__)


def image_turn_metadata(attachments: list[VisionAttachment]) -> dict[str, str]:
    if not attachments:
        return {}
    return {
        "attachments": json.dumps(
            [
                {
                    "id": attachment.attachment_id,
                    "name": attachment.name,
                    "media_type": attachment.media_type,
                }
                for attachment in attachments
            ],
            separators=(",", ":"),
        )
    }


async def persist_conversation_images(
    *,
    store: ConversationImageStore,
    attachments: list[VisionAttachment],
    principal_id: str,
    conversation_id: str,
    request_id: str,
    created_at: datetime,
) -> tuple[str, ...]:
    result = await store.put_many(
        tuple(
            ConversationImage.create(
                image_id=attachment.attachment_id,
                principal_id=principal_id,
                conversation_id=conversation_id,
                request_id=request_id,
                name=attachment.name,
                media_type=attachment.media_type,
                content=attachment.content,
                created_at=created_at,
                expires_at=created_at
                + timedelta(minutes=PENDING_CONVERSATION_IMAGE_RETENTION_MINUTES),
            )
            for attachment in attachments
        )
    )
    return result.created_image_ids


async def persist_operator_turn_with_images(
    *,
    history_store: ConversationHistoryStore,
    image_store: ConversationImageStore | None,
    attachments: list[VisionAttachment],
    principal_id: str,
    conversation_id: str,
    request_id: str,
    content: str,
    recorded_at: datetime,
    metadata: dict[str, Any],
    ontology_projector: UserContextOntologyProjector | None,
) -> ConversationTurnRecord:
    await ensure_conversation(
        store=history_store,
        principal_id=principal_id,
        conversation_id=conversation_id,
        recorded_at=recorded_at,
    )
    created_image_ids: tuple[str, ...] = ()
    if image_store is not None:
        created_image_ids = await persist_conversation_images(
            store=image_store,
            attachments=attachments,
            principal_id=principal_id,
            conversation_id=conversation_id,
            request_id=request_id,
            created_at=recorded_at,
        )
    try:
        turn = await append_operator_turn(
            store=history_store,
            principal_id=principal_id,
            conversation_id=conversation_id,
            request_id=request_id,
            content=content,
            recorded_at=recorded_at,
            metadata=metadata,
            ontology_projector=ontology_projector,
        )
    except Exception:  # noqa: BLE001 - compensate only rows created by this attempt
        if image_store is not None and created_image_ids:
            try:
                await image_store.delete_many(
                    principal_id=principal_id,
                    conversation_id=conversation_id,
                    image_ids=created_image_ids,
                )
            except Exception as cleanup_error:  # noqa: BLE001 - retain original failure
                _LOG.warning(
                    "conversation image compensation failed: %s",
                    type(cleanup_error).__name__,
                    extra={"request_id": request_id},
                )
        raise
    if image_store is not None and attachments:
        await image_store.finalize_many(
            principal_id=principal_id,
            conversation_id=conversation_id,
            request_id=request_id,
            image_ids=tuple(attachment.attachment_id for attachment in attachments),
            expires_at=turn.recorded_at + timedelta(days=DEFAULT_CONVERSATION_IMAGE_RETENTION_DAYS),
        )
    return turn


__all__ = [
    "image_turn_metadata",
    "persist_conversation_images",
    "persist_operator_turn_with_images",
]

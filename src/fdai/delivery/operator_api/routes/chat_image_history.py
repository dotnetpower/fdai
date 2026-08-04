"""Persist validated chat images and serialize content-free turn metadata."""

from __future__ import annotations

import json
from datetime import datetime

from fdai.delivery.conversation_images import ConversationImage, ConversationImageStore
from fdai.delivery.operator_api.routes.chat_vision_evidence import VisionAttachment


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
) -> None:
    for attachment in attachments:
        await store.put(
            ConversationImage.create(
                image_id=attachment.attachment_id,
                principal_id=principal_id,
                conversation_id=conversation_id,
                request_id=request_id,
                name=attachment.name,
                media_type=attachment.media_type,
                content=attachment.content,
                created_at=created_at,
            )
        )


__all__ = ["image_turn_metadata", "persist_conversation_images"]

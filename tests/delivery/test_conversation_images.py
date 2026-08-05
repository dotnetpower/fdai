from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fdai.delivery.conversation_images import (
    ConversationImage,
    ConversationImageConflictError,
    InMemoryConversationImageStore,
)


def _image(*, principal_id: str = "principal-a", content: bytes = b"png") -> ConversationImage:
    return ConversationImage.create(
        image_id="att-image-1",
        principal_id=principal_id,
        conversation_id="conversation-1",
        request_id="request-1",
        name="screenshot.png",
        media_type="image/png",
        content=content,
        created_at=datetime(2026, 8, 5, tzinfo=UTC),
    )


async def test_image_store_is_idempotent_and_principal_scoped() -> None:
    store = InMemoryConversationImageStore()
    image = _image()

    assert await store.put(image) == image
    assert await store.put(image) == image
    assert (
        await store.get(
            principal_id="principal-a",
            conversation_id="conversation-1",
            image_id="att-image-1",
        )
        == image
    )
    assert (
        await store.get(
            principal_id="principal-b",
            conversation_id="conversation-1",
            image_id="att-image-1",
        )
        is None
    )


async def test_image_store_retry_ignores_new_attempt_timestamp() -> None:
    store = InMemoryConversationImageStore()
    image = _image()
    retry = replace(image, created_at=image.created_at + timedelta(seconds=1))

    assert await store.put(image) == image
    assert await store.put(retry) == image


async def test_image_store_rejects_id_reuse_with_different_bytes() -> None:
    store = InMemoryConversationImageStore()
    await store.put(_image())

    with pytest.raises(ConversationImageConflictError):
        await store.put(_image(content=b"other"))

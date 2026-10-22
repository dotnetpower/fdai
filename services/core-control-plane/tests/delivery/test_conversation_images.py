from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.conversation_images import (
    ConversationImage,
    ConversationImageConflictError,
    ConversationImageDetail,
    ConversationImageQuotaError,
    ConversationImageTokenDescriptor,
    InMemoryConversationImageStore,
    reserve_conversation_image_tokens,
)

# Fixture images are created on 2026-08-05 and expire 90 days later, so each store reads them at
# one fixed time instead of the wall clock, which passes that expiry on 2026-11-03.
_READ_AT = datetime(2026, 8, 6, tzinfo=UTC)


def test_image_token_reservation_uses_server_dimensions_and_detail() -> None:
    receipt = reserve_conversation_image_tokens(
        (
            ConversationImageTokenDescriptor("att-low", 2048, 2048, ConversationImageDetail.LOW),
            ConversationImageTokenDescriptor("att-high", 1024, 512, ConversationImageDetail.HIGH),
        )
    )

    assert receipt.reserved_tokens == 85 + 85 + 2 * 170
    assert receipt.detail_counts == (("high", 1), ("low", 1))
    assert receipt.execution_authority is False


def test_image_token_reservation_rejects_unbounded_high_detail() -> None:
    with pytest.raises(ValueError, match="turn budget"):
        reserve_conversation_image_tokens(
            (
                ConversationImageTokenDescriptor(
                    "att-huge", 8192, 8192, ConversationImageDetail.HIGH
                ),
            )
        )


def test_image_token_descriptor_rejects_untyped_detail() -> None:
    with pytest.raises(TypeError, match="ConversationImageDetail"):
        ConversationImageTokenDescriptor("att-untyped", 512, 512, "low")  # type: ignore[arg-type]


def _read_clock() -> datetime:
    return _READ_AT


def _image(
    *,
    image_id: str = "att-image-1",
    principal_id: str = "principal-a",
    content: bytes = b"png",
) -> ConversationImage:
    return ConversationImage.create(
        image_id=image_id,
        principal_id=principal_id,
        conversation_id="conversation-1",
        request_id="request-1",
        name="screenshot.png",
        media_type="image/png",
        content=content,
        created_at=datetime(2026, 8, 5, tzinfo=UTC),
    )


async def test_image_store_is_idempotent_and_principal_scoped() -> None:
    store = InMemoryConversationImageStore(clock=_read_clock)
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
    store = InMemoryConversationImageStore(clock=_read_clock)
    image = _image()
    retry = replace(image, created_at=image.created_at + timedelta(seconds=1))

    assert await store.put(image) == image
    assert await store.put(retry) == image


async def test_image_store_rejects_id_reuse_with_different_bytes() -> None:
    store = InMemoryConversationImageStore(clock=_read_clock)
    await store.put(_image())

    with pytest.raises(ConversationImageConflictError):
        await store.put(_image(content=b"other"))


async def test_image_store_batch_conflict_is_atomic() -> None:
    store = InMemoryConversationImageStore(clock=_read_clock)
    await store.put(_image(image_id="att-existing"))

    with pytest.raises(ConversationImageConflictError):
        await store.put_many(
            (
                _image(image_id="att-new"),
                _image(image_id="att-existing", content=b"other"),
            )
        )

    assert (
        await store.get(
            principal_id="principal-a",
            conversation_id="conversation-1",
            image_id="att-new",
        )
        is None
    )


async def test_image_store_enforces_principal_count_quota_atomically() -> None:
    store = InMemoryConversationImageStore(max_images_per_principal=1, clock=_read_clock)
    await store.put(_image(image_id="att-first"))

    with pytest.raises(ConversationImageQuotaError, match="count quota"):
        await store.put(_image(image_id="att-second"))

    assert (
        await store.get(
            principal_id="principal-a",
            conversation_id="conversation-1",
            image_id="att-second",
        )
        is None
    )


async def test_image_store_enforces_principal_byte_quota() -> None:
    store = InMemoryConversationImageStore(max_bytes_per_principal=5, clock=_read_clock)
    await store.put(_image(image_id="att-first", content=b"123"))

    with pytest.raises(ConversationImageQuotaError, match="byte quota"):
        await store.put(_image(image_id="att-second", content=b"456"))


async def test_image_store_removes_expired_images_from_reads_and_quota() -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    clock = [now]
    store = InMemoryConversationImageStore(
        max_images_per_principal=1,
        clock=lambda: clock[0],
    )
    image = replace(_image(), expires_at=now + timedelta(seconds=1))
    await store.put(image)

    clock[0] = now + timedelta(seconds=2)
    assert (
        await store.get(
            principal_id="principal-a",
            conversation_id="conversation-1",
            image_id=image.image_id,
        )
        is None
    )
    await store.put(_image(image_id="att-replacement"))

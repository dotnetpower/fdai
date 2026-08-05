from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from fdai.delivery.conversation_images import (
    ConversationImage,
    ConversationImageConflictError,
    ConversationImageQuotaError,
)
from fdai.delivery.persistence.postgres_conversation_images import (
    PostgresConversationImageStore,
)
from fdai.delivery.persistence.postgres_user_context import (
    PostgresConversationHistoryStore,
    PostgresUserContextStoreConfig,
)
from fdai.delivery.persistence.postgres_user_context_retention import (
    PostgresUserContextRetention,
)
from fdai.shared.providers.user_context import ConversationRecord

pytestmark = pytest.mark.skipif(
    not os.environ.get("FDAI_DATABASE_URL"),
    reason="FDAI_DATABASE_URL is unset",
)


def _dsn() -> str:
    return os.environ["FDAI_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)


def _image(
    *,
    principal_id: str,
    conversation_id: str,
    image_id: str,
    content: bytes = b"image",
    created_at: datetime,
) -> ConversationImage:
    return ConversationImage.create(
        image_id=image_id,
        principal_id=principal_id,
        conversation_id=conversation_id,
        request_id="request-1",
        name="screenshot.png",
        media_type="image/png",
        content=content,
        created_at=created_at,
    )


async def test_postgres_image_repository_contract_and_retention() -> None:
    dsn = _dsn()
    config = PostgresUserContextStoreConfig(dsn=dsn)
    history = PostgresConversationHistoryStore(config=config)
    store = PostgresConversationImageStore(config=config)
    suffix = uuid4().hex
    principal_id = f"image-principal-{suffix}"
    conversation_id = f"image-conversation-{suffix}"
    now = datetime.now(tz=UTC)
    old = now - timedelta(days=100)
    await history.create_conversation(
        ConversationRecord(conversation_id, principal_id, "web", old, old)
    )
    image = _image(
        principal_id=principal_id,
        conversation_id=conversation_id,
        image_id="att-primary",
        created_at=old,
    )

    try:
        assert await store.put(image) == image
        assert await store.put(replace(image, created_at=old + timedelta(seconds=1))) == image
        assert (
            await store.get(
                principal_id="other-principal",
                conversation_id=conversation_id,
                image_id=image.image_id,
            )
            is None
        )

        with pytest.raises(ConversationImageConflictError):
            await store.put_many(
                (
                    _image(
                        principal_id=principal_id,
                        conversation_id=conversation_id,
                        image_id="att-new",
                        created_at=old,
                    ),
                    replace(
                        image,
                        content=b"other",
                        content_sha256=hashlib.sha256(b"other").hexdigest(),
                    ),
                )
            )
        assert (
            await store.get(
                principal_id=principal_id,
                conversation_id=conversation_id,
                image_id="att-new",
            )
            is None
        )

        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(
                "UPDATE conversation_image SET content_sha256 = %s "
                "WHERE principal_id = %s AND conversation_id = %s AND image_id = %s",
                ("0" * 64, principal_id, conversation_id, image.image_id),
            )
        with pytest.raises(ValueError, match="digest does not match"):
            await store.get(
                principal_id=principal_id,
                conversation_id=conversation_id,
                image_id=image.image_id,
            )

        report = await PostgresUserContextRetention(config=config).purge(
            now=now,
            conversation_before=now - timedelta(days=90),
            briefing_before=now - timedelta(days=90),
        )
        assert report.conversations >= 1
        assert (
            await store.get(
                principal_id=principal_id,
                conversation_id=conversation_id,
                image_id=image.image_id,
            )
            is None
        )
    finally:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(
                "DELETE FROM conversation_record WHERE principal_id = %s",
                (principal_id,),
            )


async def test_postgres_image_quota_and_schema_constraints() -> None:
    dsn = _dsn()
    config = PostgresUserContextStoreConfig(dsn=dsn)
    history = PostgresConversationHistoryStore(config=config)
    store = PostgresConversationImageStore(config=config, max_images_per_principal=1)
    suffix = uuid4().hex
    principal_id = f"quota-principal-{suffix}"
    conversation_id = f"quota-conversation-{suffix}"
    now = datetime.now(tz=UTC)
    await history.create_conversation(
        ConversationRecord(conversation_id, principal_id, "web", now, now)
    )

    try:
        await store.put(
            _image(
                principal_id=principal_id,
                conversation_id=conversation_id,
                image_id="att-first",
                created_at=now,
            )
        )
        with pytest.raises(ConversationImageQuotaError, match="count quota"):
            await store.put(
                _image(
                    principal_id=principal_id,
                    conversation_id=conversation_id,
                    image_id="att-second",
                    created_at=now,
                )
            )
        assert (
            await store.get(
                principal_id=principal_id,
                conversation_id=conversation_id,
                image_id="att-second",
            )
            is None
        )

        with pytest.raises(psycopg.errors.CheckViolation):
            async with await psycopg.AsyncConnection.connect(dsn) as connection:
                await connection.execute(
                    "INSERT INTO conversation_image "
                    "(principal_id, image_id, conversation_id, request_id, name, media_type, "
                    "content, content_sha256, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        principal_id,
                        "invalid-id",
                        conversation_id,
                        "request-2",
                        "bad.png",
                        "image/png",
                        b"bad",
                        hashlib.sha256(b"bad").hexdigest(),
                        now,
                    ),
                )
    finally:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute(
                "DELETE FROM conversation_record WHERE principal_id = %s",
                (principal_id,),
            )

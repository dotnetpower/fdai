"""PostgreSQL binary repository for principal-scoped conversation images."""

from __future__ import annotations

from typing import Any

from fdai.delivery.conversation_images import (
    ConversationImage,
    ConversationImageConflictError,
)
from fdai.delivery.persistence.postgres_user_context import (
    PostgresUserContextStoreConfig,
    _PostgresBase,
)


class PostgresConversationImageStore(_PostgresBase):
    def __init__(self, *, config: PostgresUserContextStoreConfig) -> None:
        super().__init__(config=config)

    async def put(self, image: ConversationImage) -> ConversationImage:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            cursor = await connection.execute(
                "INSERT INTO conversation_image "
                "(principal_id, image_id, conversation_id, request_id, name, media_type, "
                "content, content_sha256, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (principal_id, conversation_id, image_id) "
                "DO NOTHING RETURNING image_id",
                (
                    image.principal_id,
                    image.image_id,
                    image.conversation_id,
                    image.request_id,
                    image.name,
                    image.media_type,
                    image.content,
                    image.content_sha256,
                    image.created_at,
                ),
            )
            if await cursor.fetchone() is not None:
                return image
            existing = await self._get(
                connection,
                principal_id=image.principal_id,
                conversation_id=image.conversation_id,
                image_id=image.image_id,
            )
            if existing != image:
                raise ConversationImageConflictError(
                    "conversation image id conflicts with existing content"
                )
            return existing

    async def get(
        self,
        *,
        principal_id: str,
        conversation_id: str,
        image_id: str,
    ) -> ConversationImage | None:
        async with await self._connect() as connection:
            await self._timeout(connection)
            return await self._get(
                connection,
                principal_id=principal_id,
                conversation_id=conversation_id,
                image_id=image_id,
            )

    async def _get(
        self,
        connection: Any,
        *,
        principal_id: str,
        conversation_id: str,
        image_id: str,
    ) -> ConversationImage | None:
        cursor = await connection.execute(
            "SELECT principal_id, image_id, conversation_id, request_id, name, media_type, "
            "content, content_sha256, created_at FROM conversation_image "
            "WHERE principal_id = %s AND conversation_id = %s AND image_id = %s",
            (principal_id, conversation_id, image_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return ConversationImage(
            image_id=str(row["image_id"]),
            principal_id=str(row["principal_id"]),
            conversation_id=str(row["conversation_id"]),
            request_id=str(row["request_id"]),
            name=str(row["name"]),
            media_type=str(row["media_type"]),
            content=bytes(row["content"]),
            content_sha256=str(row["content_sha256"]),
            created_at=row["created_at"],
        )


__all__ = ["PostgresConversationImageStore"]

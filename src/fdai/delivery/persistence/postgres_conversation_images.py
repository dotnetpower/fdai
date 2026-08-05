"""PostgreSQL binary repository for principal-scoped conversation images."""

from __future__ import annotations

from typing import Any

from fdai.delivery.conversation_images import (
    DEFAULT_MAX_IMAGE_BYTES_PER_PRINCIPAL,
    DEFAULT_MAX_IMAGES_PER_PRINCIPAL,
    ConversationImage,
    ConversationImageConflictError,
    ConversationImageQuotaError,
)
from fdai.delivery.persistence.postgres_user_context import (
    PostgresUserContextStoreConfig,
    _PostgresBase,
)


class PostgresConversationImageStore(_PostgresBase):
    def __init__(
        self,
        *,
        config: PostgresUserContextStoreConfig,
        max_images_per_principal: int = DEFAULT_MAX_IMAGES_PER_PRINCIPAL,
        max_bytes_per_principal: int = DEFAULT_MAX_IMAGE_BYTES_PER_PRINCIPAL,
    ) -> None:
        super().__init__(config=config)
        if max_images_per_principal < 1 or max_bytes_per_principal < 1:
            raise ValueError("conversation image quotas MUST be positive")
        self._max_images_per_principal = max_images_per_principal
        self._max_bytes_per_principal = max_bytes_per_principal

    async def put(self, image: ConversationImage) -> ConversationImage:
        return (await self.put_many((image,)))[0]

    async def put_many(
        self, images: tuple[ConversationImage, ...]
    ) -> tuple[ConversationImage, ...]:
        async with await self._connect() as connection, connection.transaction():
            await self._timeout(connection)
            if not images:
                return ()
            principals = {image.principal_id for image in images}
            if len(principals) != 1:
                raise ValueError("conversation image batch MUST have one principal")
            principal_id = images[0].principal_id
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 7046029254386353131))",
                (principal_id,),
            )
            existing: dict[tuple[str, str], ConversationImage] = {}
            pending: dict[tuple[str, str], ConversationImage] = {}
            for image in images:
                key = (image.conversation_id, image.image_id)
                prior = (
                    existing.get(key)
                    or pending.get(key)
                    or await self._get(
                        connection,
                        principal_id=principal_id,
                        conversation_id=image.conversation_id,
                        image_id=image.image_id,
                    )
                )
                if prior is not None:
                    if not prior.has_same_intent(image):
                        raise ConversationImageConflictError(
                            "conversation image id conflicts with existing content"
                        )
                    existing[key] = prior
                else:
                    pending[key] = image
            usage = await connection.execute(
                "SELECT COUNT(*) AS image_count, COALESCE(SUM(octet_length(content)), 0) "
                "AS image_bytes FROM conversation_image WHERE principal_id = %s",
                (principal_id,),
            )
            row = await usage.fetchone()
            image_count = int(row["image_count"]) if row is not None else 0
            image_bytes = int(row["image_bytes"]) if row is not None else 0
            if image_count + len(pending) > self._max_images_per_principal:
                raise ConversationImageQuotaError("conversation image count quota exceeded")
            if (
                image_bytes + sum(len(image.content) for image in pending.values())
                > self._max_bytes_per_principal
            ):
                raise ConversationImageQuotaError("conversation image byte quota exceeded")
            for key, image in pending.items():
                existing[key] = await self._put(connection, image)
            return tuple(existing[(image.conversation_id, image.image_id)] for image in images)

    async def _put(self, connection: Any, image: ConversationImage) -> ConversationImage:
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
        if existing is None or not existing.has_same_intent(image):
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

"""Principal-scoped binary storage contract for web conversation images."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, runtime_checkable

MAX_CONVERSATION_IMAGE_BYTES: Final[int] = 4 * 1024 * 1024
DEFAULT_MAX_IMAGES_PER_PRINCIPAL: Final[int] = 1000
DEFAULT_MAX_IMAGE_BYTES_PER_PRINCIPAL: Final[int] = 256 * 1024 * 1024
_ALLOWED_MEDIA_TYPES: Final = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
_IMAGE_ID: Final = re.compile(r"att-[A-Za-z0-9-]{1,124}")


class ConversationImageConflictError(RuntimeError):
    """An image id was reused with different immutable content."""


class ConversationImageQuotaError(RuntimeError):
    """A principal's bounded conversation-image repository is full."""


@dataclass(frozen=True, slots=True)
class ConversationImage:
    image_id: str
    principal_id: str
    conversation_id: str
    request_id: str
    name: str
    media_type: str
    content: bytes
    content_sha256: str
    created_at: datetime

    def __post_init__(self) -> None:
        if _IMAGE_ID.fullmatch(self.image_id) is None:
            raise ValueError("conversation image id is invalid")
        if not self.principal_id or not self.conversation_id or not self.request_id:
            raise ValueError("conversation image ownership fields MUST be non-empty")
        if not self.name or len(self.name) > 128:
            raise ValueError("conversation image name MUST contain at most 128 characters")
        if self.media_type not in _ALLOWED_MEDIA_TYPES:
            raise ValueError("conversation image media type is unsupported")
        if not 1 <= len(self.content) <= MAX_CONVERSATION_IMAGE_BYTES:
            raise ValueError("conversation image content exceeds the byte limit")
        if hashlib.sha256(self.content).hexdigest() != self.content_sha256:
            raise ValueError("conversation image digest does not match content")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("conversation image created_at MUST be timezone-aware")

    @classmethod
    def create(
        cls,
        *,
        image_id: str,
        principal_id: str,
        conversation_id: str,
        request_id: str,
        name: str,
        media_type: str,
        content: bytes,
        created_at: datetime,
    ) -> ConversationImage:
        return cls(
            image_id=image_id,
            principal_id=principal_id,
            conversation_id=conversation_id,
            request_id=request_id,
            name=name,
            media_type=media_type,
            content=content,
            content_sha256=hashlib.sha256(content).hexdigest(),
            created_at=created_at,
        )

    def has_same_intent(self, other: ConversationImage) -> bool:
        return (
            self.image_id == other.image_id
            and self.principal_id == other.principal_id
            and self.conversation_id == other.conversation_id
            and self.request_id == other.request_id
            and self.name == other.name
            and self.media_type == other.media_type
            and self.content_sha256 == other.content_sha256
            and self.content == other.content
        )


@runtime_checkable
class ConversationImageStore(Protocol):
    async def put(self, image: ConversationImage) -> ConversationImage: ...

    async def put_many(
        self, images: tuple[ConversationImage, ...]
    ) -> tuple[ConversationImage, ...]: ...

    async def get(
        self,
        *,
        principal_id: str,
        conversation_id: str,
        image_id: str,
    ) -> ConversationImage | None: ...


class InMemoryConversationImageStore:
    def __init__(
        self,
        *,
        max_images_per_principal: int = DEFAULT_MAX_IMAGES_PER_PRINCIPAL,
        max_bytes_per_principal: int = DEFAULT_MAX_IMAGE_BYTES_PER_PRINCIPAL,
    ) -> None:
        if max_images_per_principal < 1 or max_bytes_per_principal < 1:
            raise ValueError("conversation image quotas MUST be positive")
        self._images: dict[tuple[str, str, str], ConversationImage] = {}
        self._max_images_per_principal = max_images_per_principal
        self._max_bytes_per_principal = max_bytes_per_principal

    async def put(self, image: ConversationImage) -> ConversationImage:
        return (await self.put_many((image,)))[0]

    async def put_many(
        self, images: tuple[ConversationImage, ...]
    ) -> tuple[ConversationImage, ...]:
        stored: list[ConversationImage] = []
        pending: dict[tuple[str, str, str], ConversationImage] = {}
        for image in images:
            key = (image.principal_id, image.conversation_id, image.image_id)
            existing = self._images.get(key) or pending.get(key)
            if existing is not None:
                if not existing.has_same_intent(image):
                    raise ConversationImageConflictError(
                        "conversation image id conflicts with existing content"
                    )
                stored.append(existing)
                continue
            pending[key] = image
            stored.append(image)
        principals = {image.principal_id for image in images}
        for principal_id in principals:
            current = [
                image for image in self._images.values() if image.principal_id == principal_id
            ]
            added = [image for image in pending.values() if image.principal_id == principal_id]
            if len(current) + len(added) > self._max_images_per_principal:
                raise ConversationImageQuotaError("conversation image count quota exceeded")
            if sum(len(image.content) for image in current + added) > self._max_bytes_per_principal:
                raise ConversationImageQuotaError("conversation image byte quota exceeded")
        self._images.update(pending)
        return tuple(stored)

    async def get(
        self,
        *,
        principal_id: str,
        conversation_id: str,
        image_id: str,
    ) -> ConversationImage | None:
        return self._images.get((principal_id, conversation_id, image_id))


__all__ = [
    "ConversationImage",
    "ConversationImageConflictError",
    "ConversationImageQuotaError",
    "ConversationImageStore",
    "DEFAULT_MAX_IMAGE_BYTES_PER_PRINCIPAL",
    "DEFAULT_MAX_IMAGES_PER_PRINCIPAL",
    "InMemoryConversationImageStore",
    "MAX_CONVERSATION_IMAGE_BYTES",
]

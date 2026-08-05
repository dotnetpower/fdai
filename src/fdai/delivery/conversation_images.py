"""Principal-scoped binary storage contract for web conversation images."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol, runtime_checkable

MAX_CONVERSATION_IMAGE_BYTES: Final[int] = 4 * 1024 * 1024
DEFAULT_MAX_IMAGES_PER_PRINCIPAL: Final[int] = 1000
DEFAULT_MAX_IMAGE_BYTES_PER_PRINCIPAL: Final[int] = 256 * 1024 * 1024
DEFAULT_CONVERSATION_IMAGE_RETENTION_DAYS: Final[int] = 90
_ALLOWED_MEDIA_TYPES: Final = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
_IMAGE_ID: Final = re.compile(r"att-[A-Za-z0-9-]{1,124}")


class ConversationImageConflictError(RuntimeError):
    """An image id was reused with different immutable content."""


class ConversationImageQuotaError(RuntimeError):
    """A principal's bounded conversation-image repository is full."""


@dataclass(frozen=True, slots=True)
class ConversationImageBatchResult:
    images: tuple[ConversationImage, ...]
    created_image_ids: tuple[str, ...]


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
    expires_at: datetime

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
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("conversation image expires_at MUST be timezone-aware")
        if self.expires_at <= self.created_at:
            raise ValueError("conversation image expires_at MUST be after created_at")

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
        expires_at: datetime | None = None,
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
            expires_at=expires_at
            or created_at + timedelta(days=DEFAULT_CONVERSATION_IMAGE_RETENTION_DAYS),
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
    ) -> ConversationImageBatchResult: ...

    async def delete_many(
        self,
        *,
        principal_id: str,
        conversation_id: str,
        image_ids: tuple[str, ...],
    ) -> None: ...

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
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        if max_images_per_principal < 1 or max_bytes_per_principal < 1:
            raise ValueError("conversation image quotas MUST be positive")
        self._images: dict[tuple[str, str, str], ConversationImage] = {}
        self._max_images_per_principal = max_images_per_principal
        self._max_bytes_per_principal = max_bytes_per_principal
        self._clock = clock

    async def put(self, image: ConversationImage) -> ConversationImage:
        return (await self.put_many((image,))).images[0]

    async def put_many(self, images: tuple[ConversationImage, ...]) -> ConversationImageBatchResult:
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
            self._delete_expired(principal_id)
            current = [
                image for image in self._images.values() if image.principal_id == principal_id
            ]
            added = [image for image in pending.values() if image.principal_id == principal_id]
            if len(current) + len(added) > self._max_images_per_principal:
                raise ConversationImageQuotaError("conversation image count quota exceeded")
            if sum(len(image.content) for image in current + added) > self._max_bytes_per_principal:
                raise ConversationImageQuotaError("conversation image byte quota exceeded")
        self._images.update(pending)
        return ConversationImageBatchResult(
            tuple(stored),
            tuple(image.image_id for image in pending.values()),
        )

    async def delete_many(
        self,
        *,
        principal_id: str,
        conversation_id: str,
        image_ids: tuple[str, ...],
    ) -> None:
        for image_id in image_ids:
            self._images.pop((principal_id, conversation_id, image_id), None)

    async def get(
        self,
        *,
        principal_id: str,
        conversation_id: str,
        image_id: str,
    ) -> ConversationImage | None:
        self._delete_expired(principal_id)
        return self._images.get((principal_id, conversation_id, image_id))

    def _delete_expired(self, principal_id: str) -> None:
        now = self._clock()
        expired = [
            key
            for key, image in self._images.items()
            if image.principal_id == principal_id and image.expires_at <= now
        ]
        for key in expired:
            self._images.pop(key, None)


__all__ = [
    "ConversationImage",
    "ConversationImageBatchResult",
    "ConversationImageConflictError",
    "ConversationImageQuotaError",
    "ConversationImageStore",
    "DEFAULT_CONVERSATION_IMAGE_RETENTION_DAYS",
    "DEFAULT_MAX_IMAGE_BYTES_PER_PRINCIPAL",
    "DEFAULT_MAX_IMAGES_PER_PRINCIPAL",
    "InMemoryConversationImageStore",
    "MAX_CONVERSATION_IMAGE_BYTES",
]

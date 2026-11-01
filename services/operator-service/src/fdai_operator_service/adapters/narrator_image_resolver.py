"""Server-owned conversation-image resolver for vision-capable narrator turns."""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from fdai_operator_service.families.conversation.contracts import ConversationBoundaryError

MAX_RESOLVED_IMAGES_PER_TURN = 4
MAX_RESOLVED_IMAGE_BYTES = 4 * 1024 * 1024
ALLOWED_IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
_IMAGE_ID_RE = re.compile(r"^att-[A-Za-z0-9-]{1,124}$")


@dataclass(frozen=True, slots=True)
class ResolvedNarratorImage:
    """Validated server-owned image payload for one vision turn."""

    image_id: str
    principal_id: str
    conversation_id: str
    media_type: str
    content: bytes
    content_sha256: str
    width: int = 512
    height: int = 512

    def __post_init__(self) -> None:
        if _IMAGE_ID_RE.fullmatch(self.image_id) is None:
            raise ValueError("resolved narrator image_id is invalid")
        if not self.principal_id.strip() or not self.conversation_id.strip():
            raise ValueError("resolved narrator image requires principal_id and conversation_id")
        if self.media_type not in ALLOWED_IMAGE_MEDIA_TYPES:
            raise ValueError("resolved narrator image media_type is unsupported")
        if not (1 <= len(self.content) <= MAX_RESOLVED_IMAGE_BYTES):
            raise ValueError("resolved narrator image content exceeds byte bounds")
        if hashlib.sha256(self.content).hexdigest() != self.content_sha256:
            raise ValueError("resolved narrator image content_sha256 mismatch")
        if not (1 <= self.width <= 16_384 and 1 <= self.height <= 16_384):
            raise ValueError("resolved narrator image dimensions are out of bounds")

    def to_data_url(self) -> str:
        encoded = base64.b64encode(self.content).decode("ascii")
        return f"data:{self.media_type};base64,{encoded}"


class NarratorImageResolver(Protocol):
    """Resolve server-owned conversation image references for a vision narrator turn."""

    async def resolve_for_turn(
        self,
        *,
        principal_id: str,
        conversation_id: str,
        image_ids: tuple[str, ...],
    ) -> tuple[ResolvedNarratorImage, ...]: ...


class InMemoryNarratorImageResolver:
    """Deterministic principal-and-conversation-scoped image resolver."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str, str], ResolvedNarratorImage] = {}

    def register(self, image: ResolvedNarratorImage) -> None:
        self._store[(image.principal_id, image.conversation_id, image.image_id)] = image

    async def resolve_for_turn(
        self,
        *,
        principal_id: str,
        conversation_id: str,
        image_ids: tuple[str, ...],
    ) -> tuple[ResolvedNarratorImage, ...]:
        principal = principal_id.strip()
        conversation = conversation_id.strip()
        if not principal or not conversation:
            raise ConversationBoundaryError(
                400,
                "invalid_image_scope",
                "image resolution requires principal_id and conversation_id",
            )
        if not (1 <= len(image_ids) <= MAX_RESOLVED_IMAGES_PER_TURN):
            raise ConversationBoundaryError(
                400,
                "invalid_image_count",
                f"image_ids must contain 1 to {MAX_RESOLVED_IMAGES_PER_TURN} entries",
            )
        if len(set(image_ids)) != len(image_ids):
            raise ConversationBoundaryError(
                400,
                "duplicate_image_ids",
                "image_ids must not contain duplicates",
            )
        resolved: list[ResolvedNarratorImage] = []
        for image_id in image_ids:
            if _IMAGE_ID_RE.fullmatch(image_id) is None:
                raise ConversationBoundaryError(
                    400,
                    "invalid_image_id",
                    "image_id must match att-<id>",
                )
            record = self._store.get((principal, conversation, image_id))
            if record is None:
                raise ConversationBoundaryError(
                    404,
                    "image_not_found",
                    "requested conversation image was not found in principal scope",
                )
            resolved.append(record)
        return tuple(resolved)


async def resolve_turn_images_from_body(
    body: Mapping[str, Any],
    *,
    resolver: NarratorImageResolver | None,
) -> tuple[ResolvedNarratorImage, ...]:
    """Validate and resolve server-owned `image_ids` from a turn request body."""
    if resolver is None:
        raise ConversationBoundaryError(
            503,
            "narrator_image_resolution_unavailable",
            "server-owned narrator image resolution is unavailable",
        )
    if body.get("images") or body.get("attachments"):
        raise ConversationBoundaryError(
            400,
            "raw_client_images_rejected",
            "raw client image payloads are rejected; pass server-owned image_ids only",
        )
    raw_ids = body.get("image_ids")
    if (
        not isinstance(raw_ids, (list, tuple))
        or not raw_ids
        or not all(isinstance(item, str) for item in raw_ids)
    ):
        raise ConversationBoundaryError(
            400,
            "invalid_image_ids",
            "image_ids must be a non-empty list of server-owned image identifiers",
        )
    principal_id = str(body.get("principal_id") or "local-operator").strip()
    conversation_id = str(
        body.get("conversation_id") or body.get("session_id") or "default"
    ).strip()
    requested = tuple(str(item) for item in raw_ids)
    resolved = await resolver.resolve_for_turn(
        principal_id=principal_id,
        conversation_id=conversation_id,
        image_ids=requested,
    )
    if tuple(img.image_id for img in resolved) != requested or any(
        img.principal_id != principal_id or img.conversation_id != conversation_id
        for img in resolved
    ):
        raise ConversationBoundaryError(
            403,
            "image_scope_mismatch",
            "resolved images did not match the requested principal, conversation, or image_ids",
        )
    max_turn_bytes = MAX_RESOLVED_IMAGES_PER_TURN * MAX_RESOLVED_IMAGE_BYTES
    if sum(len(img.content) for img in resolved) > max_turn_bytes:
        raise ConversationBoundaryError(
            400,
            "image_turn_bytes_exceeded",
            "resolved images exceed total per-turn byte limit",
        )
    return resolved


__all__ = [
    "ALLOWED_IMAGE_MEDIA_TYPES",
    "InMemoryNarratorImageResolver",
    "MAX_RESOLVED_IMAGES_PER_TURN",
    "MAX_RESOLVED_IMAGE_BYTES",
    "NarratorImageResolver",
    "ResolvedNarratorImage",
    "resolve_turn_images_from_body",
]

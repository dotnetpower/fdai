"""Focused tests for server-owned narrator image resolution and vision routing."""

from __future__ import annotations

import hashlib

import pytest
from fdai_operator_service.adapters.narrator_image_resolver import (
    InMemoryNarratorImageResolver,
    ResolvedNarratorImage,
    resolve_turn_images_from_body,
)
from fdai_operator_service.families.conversation.contracts import ConversationBoundaryError

PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
PNG_SHA = hashlib.sha256(PNG_BYTES).hexdigest()


def _sample_image(
    *,
    image_id: str = "att-img-1",
    principal_id: str = "principal-a",
    conversation_id: str = "conv-1",
) -> ResolvedNarratorImage:
    return ResolvedNarratorImage(
        image_id=image_id,
        principal_id=principal_id,
        conversation_id=conversation_id,
        media_type="image/png",
        content=PNG_BYTES,
        content_sha256=PNG_SHA,
    )


async def test_resolver_returns_validated_images_in_principal_and_conversation_scope() -> None:
    resolver = InMemoryNarratorImageResolver()
    resolver.register(_sample_image())
    resolved = await resolve_turn_images_from_body(
        {
            "principal_id": "principal-a",
            "conversation_id": "conv-1",
            "image_ids": ["att-img-1"],
        },
        resolver=resolver,
    )
    assert len(resolved) == 1
    assert resolved[0].image_id == "att-img-1"
    assert resolved[0].to_data_url().startswith("data:image/png;base64,")


async def test_resolver_denies_cross_principal_cross_conversation_and_raw_client_images() -> None:
    resolver = InMemoryNarratorImageResolver()
    resolver.register(_sample_image())

    with pytest.raises(ConversationBoundaryError) as foreign_info:
        await resolve_turn_images_from_body(
            {
                "principal_id": "principal-b",
                "conversation_id": "conv-1",
                "image_ids": ["att-img-1"],
            },
            resolver=resolver,
        )
    assert foreign_info.value.status_code == 404
    assert foreign_info.value.code == "image_not_found"

    with pytest.raises(ConversationBoundaryError) as raw_info:
        await resolve_turn_images_from_body(
            {
                "principal_id": "principal-a",
                "conversation_id": "conv-1",
                "images": ["data:image/png;base64,AAAA"],
            },
            resolver=resolver,
        )
    assert raw_info.value.status_code == 400
    assert raw_info.value.code == "raw_client_images_rejected"


async def test_resolver_none_fails_closed_with_503_unavailable() -> None:
    with pytest.raises(ConversationBoundaryError) as exc_info:
        await resolve_turn_images_from_body(
            {"image_ids": ["att-img-1"]},
            resolver=None,
        )
    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "narrator_image_resolution_unavailable"

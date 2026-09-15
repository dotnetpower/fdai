"""Refuse unsupported inline-image inputs before accepting a text-only chat turn."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_operator_service.families.conversation.contracts import ConversationBoundaryError


def inline_images_present(body: Mapping[str, object]) -> bool:
    """Validate image-field containers without decoding, retaining, or inspecting their bytes.

    Missing, null, and empty arrays preserve text-only compatibility. A malformed container
    fails with a content-free client error even when another image field is nonempty.
    """
    present = False
    for field in ("attachments", "images", "image_ids"):
        value = body.get(field)
        if value is None:
            continue
        if not isinstance(value, list):
            raise ConversationBoundaryError(
                400,
                "invalid_inline_images",
                "inline image fields MUST be arrays or null",
            )
        present = present or bool(value)
    return present


def require_inline_images_absent(body: Mapping[str, object]) -> None:
    """Hold an image-bearing turn until the server-owned image path is implemented.

    Call before document resolution, persistence, or semantic publication. This gate grants
    no image-storage or model capability and never removes fields to manufacture a text turn.
    """
    if inline_images_present(body):
        raise ConversationBoundaryError(
            501,
            "inline_images_unavailable",
            "inline images are unavailable; use governed document upload and document_refs",
        )

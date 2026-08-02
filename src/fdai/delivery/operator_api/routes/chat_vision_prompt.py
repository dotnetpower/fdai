"""Multimodal user-message construction for chat prompts."""

from __future__ import annotations

from typing import Any


def vision_user_content(text: str, attachments: Any) -> str | list[dict[str, Any]]:
    """Build plain text or validated OpenAI-style image content parts."""

    if not isinstance(attachments, list) or not attachments:
        return text
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        url = attachment.get("data_url")
        if isinstance(url, str) and url.startswith("data:image/"):
            parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts if len(parts) > 1 else text

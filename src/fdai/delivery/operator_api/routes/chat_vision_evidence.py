"""Bounded, read-only vision-evidence parsing for Command Deck chat.

An operator can attach an image to a chat turn as read-only evidence for the
narrator (Bragi) to ground a vision answer on. The console is read-only: an
attachment is never an action, only evidence. This module parses and validates
those inline attachments defensively before they reach the narrator:

- only a small raster allowlist (png / jpeg / gif / webp); SVG is refused
  because it can carry script;
- only ``data:`` URLs (never ``http(s)``) so the narrator model cannot be
  steered into fetching an attacker-controlled URL (SSRF);
- the declared media type MUST match the decoded magic bytes, so a spoofed
  ``image/png`` header cannot smuggle another payload;
- a per-image byte cap and a per-turn count cap bound cost and blast radius.

Pure and dependency-free so it is unit-testable; the chat routes call
``parse_vision_attachments`` and place the result under
``view_context["_attachments"]`` for the vision-capable narrator.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from typing import Any, Final

_ALLOWED_MEDIA_TYPES: Final = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

# Max decoded bytes per image (~4 MiB) and max images per turn. Together they
# bound the vision payload a single authenticated turn can carry.
DEFAULT_MAX_IMAGE_BYTES: Final[int] = 4 * 1024 * 1024
DEFAULT_MAX_IMAGES: Final[int] = 4
DEFAULT_MAX_IMAGE_EDGE: Final[int] = 2048
_MAX_NAME_LEN: Final[int] = 128

_DATA_URL: Final = re.compile(
    r"^data:(?P<media>image/[a-z0-9.+-]+);base64,(?P<b64>[A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE,
)
_CONTROL_CHARS: Final = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class VisionAttachment:
    """One validated inline image the narrator may ground a vision answer on."""

    name: str
    media_type: str
    data_url: str
    byte_size: int

    def to_view_dict(self) -> dict[str, Any]:
        """Render the view-context payload the vision narrator consumes."""

        return {
            "name": self.name,
            "media_type": self.media_type,
            "data_url": self.data_url,
            "byte_size": self.byte_size,
        }


def _magic_matches(media_type: str, data: bytes) -> bool:
    """Return whether decoded bytes carry the signature for ``media_type``."""

    if media_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if media_type == "image/gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if media_type == "image/webp":
        return len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def _image_dimensions(media_type: str, data: bytes) -> tuple[int, int] | None:
    if media_type == "image/png":
        if len(data) < 24 or data[8:12] != b"\x00\x00\x00\r" or data[12:16] != b"IHDR":
            return None
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if media_type == "image/gif":
        if len(data) < 10:
            return None
        return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    if media_type == "image/webp":
        if len(data) < 25:
            return None
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            return (
                1 + int.from_bytes(data[24:27], "little"),
                1 + int.from_bytes(data[27:30], "little"),
            )
        if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
            packed = int.from_bytes(data[21:25], "little")
            return 1 + (packed & 0x3FFF), 1 + ((packed >> 14) & 0x3FFF)
        if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
            return (
                int.from_bytes(data[26:28], "little") & 0x3FFF,
                int.from_bytes(data[28:30], "little") & 0x3FFF,
            )
        return None
    if media_type == "image/jpeg":
        return _jpeg_dimensions(data)
    return None


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    sof_markers = frozenset(
        {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    )
    offset = 2
    while offset < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            return None
        marker = data[offset]
        offset += 1
        if marker == 0xD9:
            return None
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            continue
        if offset + 2 > len(data):
            return None
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(data):
            return None
        if marker in sof_markers:
            if segment_length < 7:
                return None
            return (
                int.from_bytes(data[offset + 5 : offset + 7], "big"),
                int.from_bytes(data[offset + 3 : offset + 5], "big"),
            )
        offset += segment_length
    return None


def _clean_name(raw: Any, index: int) -> str:
    """Sanitize a display name; fall back to a positional label."""

    if isinstance(raw, str):
        stripped = _CONTROL_CHARS.sub("", raw).strip()
        if stripped:
            return stripped[:_MAX_NAME_LEN]
    return f"image-{index + 1}"


def parse_vision_attachments(
    body: dict[str, Any],
    *,
    max_images: int = DEFAULT_MAX_IMAGES,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    max_image_edge: int = DEFAULT_MAX_IMAGE_EDGE,
) -> list[VisionAttachment]:
    """Parse and validate the ``attachments`` field of a chat request body.

    Returns an empty list when no attachments are present. Raises
    :class:`ValueError` (mapped by the routes to ``400``) for any malformed,
    oversized, disallowed, or spoofed attachment so nothing unvalidated ever
    reaches the vision narrator.
    """

    raw = body.get("attachments")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("attachments MUST be a list")
    if len(raw) > max_images:
        raise ValueError(f"attachments exceed cap ({len(raw)} > {max_images})")

    parsed: list[VisionAttachment] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError("each attachment MUST be an object")
        data_url = item.get("data_url")
        if not isinstance(data_url, str):
            raise ValueError("attachment data_url MUST be a string")
        match = _DATA_URL.match(data_url.strip())
        if match is None:
            raise ValueError("attachment data_url MUST be a base64 image data URL")
        media_type = match.group("media").lower()
        if media_type not in _ALLOWED_MEDIA_TYPES:
            raise ValueError(f"unsupported attachment media type: {media_type}")
        b64 = re.sub(r"\s+", "", match.group("b64"))
        # Reject a clearly-oversized payload from its encoded length BEFORE
        # allocating the decode buffer, so a caller cannot force a large
        # transient allocation only to have it rejected after decoding. The
        # exact post-decode check below stays authoritative; this bound only
        # fires when the decoded size must exceed the cap regardless of padding.
        if (len(b64) // 4) * 3 > max_image_bytes + 3:
            raise ValueError(f"attachment exceeds size cap (>{max_image_bytes})")
        try:
            decoded = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("attachment data_url is not valid base64") from exc
        if not decoded:
            raise ValueError("attachment is empty")
        if len(decoded) > max_image_bytes:
            raise ValueError(f"attachment exceeds size cap ({len(decoded)} > {max_image_bytes})")
        if not _magic_matches(media_type, decoded):
            raise ValueError(f"attachment content does not match declared type {media_type}")
        dimensions = _image_dimensions(media_type, decoded)
        if dimensions is None or min(dimensions) < 1:
            raise ValueError(f"attachment {media_type} dimensions are malformed")
        if max(dimensions) > max_image_edge:
            raise ValueError(
                f"attachment exceeds pixel edge cap ({max(dimensions)} > {max_image_edge})"
            )
        parsed.append(
            VisionAttachment(
                name=_clean_name(item.get("name"), index),
                media_type=media_type,
                data_url=f"data:{media_type};base64,{b64}",
                byte_size=len(decoded),
            )
        )
    return parsed


def _format_bytes(size: int) -> str:
    """Render a compact human byte size for a status-frame detail line."""

    if size < 1024:
        return f"{size} B"
    kib = size / 1024
    if kib < 1024:
        return f"{round(kib)} KB"
    return f"{kib / 1024:.1f} MB"


def vision_source_previews(attachments: Any) -> list[dict[str, Any]]:
    """Render read-only source previews for the ``vision_*`` SSE status frames.

    Carries only the display metadata (name, media type, size) - never the
    base64 payload - so the console can show which attached images the narrator
    is grounding on, symmetric to the web-search source previews.
    """

    if not isinstance(attachments, list):
        return []
    previews: list[dict[str, Any]] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        name = attachment.get("name")
        if not isinstance(name, str) or not name:
            continue
        detail_bits: list[str] = []
        media = attachment.get("media_type")
        if isinstance(media, str) and media:
            detail_bits.append(media)
        size = attachment.get("byte_size")
        if isinstance(size, int) and size >= 0:
            detail_bits.append(_format_bytes(size))
        previews.append(
            {
                "kind": "image",
                "label": name,
                "detail": " \u00b7 ".join(detail_bits),
                "side_effect_class": "ground",
            }
        )
    return previews


__all__ = [
    "DEFAULT_MAX_IMAGE_EDGE",
    "DEFAULT_MAX_IMAGES",
    "DEFAULT_MAX_IMAGE_BYTES",
    "VisionAttachment",
    "parse_vision_attachments",
    "vision_source_previews",
]

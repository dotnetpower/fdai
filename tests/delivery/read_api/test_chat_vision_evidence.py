"""Tests for bounded, read-only vision-evidence parsing."""

from __future__ import annotations

import base64

import pytest

from fdai.delivery.read_api.routes.chat_vision_evidence import (
    VisionAttachment,
    parse_vision_attachments,
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
_GIF = b"GIF89a" + b"\x00" * 32
_WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 16


def _data_url(media: str, payload: bytes) -> str:
    return f"data:{media};base64,{base64.b64encode(payload).decode()}"


def _attachment(media: str, payload: bytes, name: str | None = None) -> dict[str, object]:
    item: dict[str, object] = {"data_url": _data_url(media, payload)}
    if name is not None:
        item["name"] = name
    return item


def test_no_attachments_returns_empty() -> None:
    assert parse_vision_attachments({}) == []
    assert parse_vision_attachments({"attachments": None}) == []


def test_parses_each_allowed_raster_type() -> None:
    body = {
        "attachments": [
            _attachment("image/png", _PNG, "shot.png"),
            _attachment("image/jpeg", _JPEG),
            _attachment("image/gif", _GIF),
            _attachment("image/webp", _WEBP),
        ]
    }
    parsed = parse_vision_attachments(body)
    assert [a.media_type for a in parsed] == [
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
    ]
    assert parsed[0].name == "shot.png"
    # A missing name falls back to a positional label.
    assert parsed[1].name == "image-2"
    assert isinstance(parsed[0], VisionAttachment)
    assert parsed[0].byte_size == len(_PNG)


def test_view_dict_shape() -> None:
    parsed = parse_vision_attachments({"attachments": [_attachment("image/png", _PNG)]})
    assert parsed[0].to_view_dict() == {
        "name": "image-1",
        "media_type": "image/png",
        "data_url": parsed[0].data_url,
        "byte_size": len(_PNG),
    }


def test_rejects_svg_and_other_media_types() -> None:
    body = {"attachments": [{"data_url": _data_url("image/svg+xml", b"<svg></svg>")}]}
    with pytest.raises(ValueError, match="unsupported attachment media type"):
        parse_vision_attachments(body)


def test_rejects_non_data_urls_ssrf_guard() -> None:
    body = {"attachments": [{"data_url": "https://evil.example/pixel.png"}]}
    with pytest.raises(ValueError, match="base64 image data URL"):
        parse_vision_attachments(body)


def test_rejects_media_type_magic_byte_spoof() -> None:
    # Declares png but carries jpeg bytes.
    body = {"attachments": [{"data_url": _data_url("image/png", _JPEG)}]}
    with pytest.raises(ValueError, match="does not match declared type"):
        parse_vision_attachments(body)


def test_rejects_invalid_base64() -> None:
    body = {"attachments": [{"data_url": "data:image/png;base64,not*valid*base64"}]}
    with pytest.raises(ValueError, match="base64 image data URL"):
        parse_vision_attachments(body)


def test_rejects_empty_payload() -> None:
    body = {"attachments": [{"data_url": "data:image/png;base64,"}]}
    with pytest.raises(ValueError, match="base64 image data URL"):
        parse_vision_attachments(body)


def test_enforces_size_cap() -> None:
    body = {"attachments": [_attachment("image/png", _PNG)]}
    with pytest.raises(ValueError, match="exceeds size cap"):
        parse_vision_attachments(body, max_image_bytes=8)


def test_enforces_count_cap() -> None:
    body = {"attachments": [_attachment("image/png", _PNG) for _ in range(3)]}
    with pytest.raises(ValueError, match="exceed cap"):
        parse_vision_attachments(body, max_images=2)


def test_rejects_non_list_attachments() -> None:
    with pytest.raises(ValueError, match="MUST be a list"):
        parse_vision_attachments({"attachments": {"data_url": _data_url("image/png", _PNG)}})


def test_rejects_non_object_item() -> None:
    with pytest.raises(ValueError, match="MUST be an object"):
        parse_vision_attachments({"attachments": ["not-an-object"]})


def test_sanitizes_control_characters_in_name() -> None:
    parsed = parse_vision_attachments(
        {"attachments": [_attachment("image/png", _PNG, "a\x00b\x1fc.png")]}
    )
    assert parsed[0].name == "abc.png"


def test_normalizes_whitespace_in_data_url() -> None:
    raw = base64.b64encode(_PNG).decode()
    spaced = f"data:image/png;base64,{raw[:8]}\n{raw[8:]}"
    parsed = parse_vision_attachments({"attachments": [{"data_url": spaced}]})
    # Normalized form carries no embedded whitespace.
    assert "\n" not in parsed[0].data_url
    assert parsed[0].byte_size == len(_PNG)

"""Tests for bounded, read-only vision-evidence parsing."""

from __future__ import annotations

import base64

import pytest

from fdai.delivery.operator_api.application.conversation.vision_evidence import (
    VisionAttachment,
    _clean_name,
    _format_bytes,
    _magic_matches,
    parse_vision_attachments,
    vision_evidence_refs,
    vision_source_previews,
)


def _png(width: int = 1, height: int = 1) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00\x00\x00\x00\x00"
    )


_PNG = _png()
_JPEG = b"\xff\xd8\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
_GIF = b"GIF89a\x01\x00\x01\x00" + b"\x00" * 28
_WEBP = b"RIFF\x16\x00\x00\x00WEBPVP8X\x0a\x00\x00\x00" + b"\x00" * 10


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


def test_synthesized_ids_are_scoped_to_the_normalized_request() -> None:
    body = {"attachments": [_attachment("image/png", _PNG)]}

    first = parse_vision_attachments(body, request_id="request-first")
    second = parse_vision_attachments(body, request_id="request-second")

    assert first[0].attachment_id != second[0].attachment_id


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
        "id": parsed[0].attachment_id,
        "name": "image-1",
        "media_type": "image/png",
        "data_url": parsed[0].data_url,
        "byte_size": len(_PNG),
    }
    assert vision_evidence_refs([parsed[0].to_view_dict()]) == (
        f"conversation-image:{parsed[0].attachment_id}",
    )


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


def test_rejects_oversized_before_decode() -> None:
    # A base64 string whose encoded length alone implies a decoded size above
    # the cap is rejected by the early length guard, before the decode buffer
    # is allocated and before magic-byte validation (the payload is not a real
    # PNG, yet it is refused on size, not on content).
    big_b64 = base64.b64encode(b"\x00" * 64).decode()
    body = {"attachments": [{"data_url": f"data:image/png;base64,{big_b64}"}]}
    with pytest.raises(ValueError, match=r"exceeds size cap \(>8\)"):
        parse_vision_attachments(body, max_image_bytes=8)


def test_enforces_count_cap() -> None:
    body = {"attachments": [_attachment("image/png", _PNG) for _ in range(3)]}
    with pytest.raises(ValueError, match="exceed cap"):
        parse_vision_attachments(body, max_images=2)


def test_rejects_duplicate_attachment_ids() -> None:
    body = {
        "attachments": [
            {"id": "att-duplicate", **_attachment("image/png", _PNG)},
            {"id": "att-duplicate", **_attachment("image/jpeg", _JPEG)},
        ]
    }

    with pytest.raises(ValueError, match="ids MUST be unique"):
        parse_vision_attachments(body)


def test_rejects_oversized_pixel_dimensions() -> None:
    body = {"attachments": [_attachment("image/png", _png(width=2049))]}
    with pytest.raises(ValueError, match="exceeds pixel edge cap"):
        parse_vision_attachments(body)


def test_rejects_truncated_dimension_header() -> None:
    body = {"attachments": [_attachment("image/png", b"\x89PNG\r\n\x1a\n")]}
    with pytest.raises(ValueError, match="dimensions are malformed"):
        parse_vision_attachments(body)


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


def test_disambiguates_names_that_collide_after_truncation() -> None:
    prefix = "a" * 128
    parsed = parse_vision_attachments(
        {
            "attachments": [
                _attachment("image/png", _PNG, f"{prefix}-one.png"),
                _attachment("image/png", _PNG, f"{prefix}-two.png"),
            ]
        }
    )

    assert parsed[0].name == prefix
    assert parsed[1].name.endswith(" (2)")
    assert len(parsed[1].name) <= 128


def test_normalizes_whitespace_in_data_url() -> None:
    raw = base64.b64encode(_PNG).decode()
    spaced = f"data:image/png;base64,{raw[:8]}\n{raw[8:]}"
    parsed = parse_vision_attachments({"attachments": [{"data_url": spaced}]})
    # Normalized form carries no embedded whitespace.
    assert "\n" not in parsed[0].data_url
    assert parsed[0].byte_size == len(_PNG)


def test_vision_source_previews_render_metadata_without_base64() -> None:
    parsed = parse_vision_attachments(
        {"attachments": [_attachment("image/png", _PNG, "diagram.png")]}
    )
    previews = vision_source_previews([a.to_view_dict() for a in parsed])
    assert len(previews) == 1
    assert previews[0]["kind"] == "image"
    assert previews[0]["label"] == "diagram.png"
    assert previews[0]["side_effect_class"] == "ground"
    assert previews[0]["detail"].startswith("image/png")
    # The base64 payload is never carried in a preview.
    assert "base64" not in previews[0]["detail"]


def test_vision_source_previews_tolerate_bad_input() -> None:
    assert vision_source_previews(None) == []
    assert vision_source_previews("nope") == []
    assert vision_source_previews([{"media_type": "image/png"}]) == []  # no name


def test_vision_source_previews_skip_and_partial_detail() -> None:
    previews = vision_source_previews(
        [
            "not-a-dict",  # skipped: non-dict item
            {"name": ""},  # skipped: empty name
            {"name": "only-name.png"},  # no media / size -> empty detail
            {"name": "typed.png", "media_type": 42, "byte_size": "big"},  # bad types -> empty
        ]
    )
    assert [p["label"] for p in previews] == ["only-name.png", "typed.png"]
    assert previews[0]["detail"] == ""
    assert previews[1]["detail"] == ""


def test_format_bytes_units() -> None:
    assert _format_bytes(512) == "512 B"
    assert _format_bytes(43008) == "42 KB"
    assert _format_bytes(1_887_437) == "1.8 MB"


def test_magic_matches_direct() -> None:
    assert _magic_matches("image/png", _PNG) is True
    assert _magic_matches("image/jpeg", _JPEG) is True
    assert _magic_matches("image/gif", b"GIF87a" + b"\x00" * 8) is True
    assert _magic_matches("image/webp", _WEBP) is True
    # A truncated WEBP header fails the length guard.
    assert _magic_matches("image/webp", b"RIFF") is False
    # An unknown media type has no signature handler.
    assert _magic_matches("image/tiff", b"II*\x00") is False


def test_clean_name_falls_back_when_only_control_chars() -> None:
    assert _clean_name("\x00\x01\x1f", 0) == "image-1"
    assert _clean_name(None, 3) == "image-4"
    assert _clean_name("  keep.png  ", 0) == "keep.png"


def test_rejects_non_string_data_url() -> None:
    with pytest.raises(ValueError, match="data_url MUST be a string"):
        parse_vision_attachments({"attachments": [{"data_url": 123}]})


def test_rejects_regex_passing_but_undecodable_base64() -> None:
    # "AAA" passes the data-URL character class but is not a valid base64 length,
    # so it reaches and fails the decode step (not the pre-filter).
    with pytest.raises(ValueError, match="not valid base64"):
        parse_vision_attachments({"attachments": [{"data_url": "data:image/png;base64,AAA"}]})


def test_borderline_over_cap_is_rejected_before_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"attachments": [_attachment("image/png", _PNG)]}
    cap = len(_PNG) - 1
    monkeypatch.setattr(
        "fdai.delivery.operator_api.application.conversation.vision_evidence.base64.b64decode",
        lambda *_args, **_kwargs: pytest.fail("oversized payload reached base64 decode"),
    )
    with pytest.raises(ValueError, match=rf"exceeds size cap \(>{cap}\)"):
        parse_vision_attachments(body, max_image_bytes=cap)

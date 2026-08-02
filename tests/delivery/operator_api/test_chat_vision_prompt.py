"""Vision-attachment prompt-assembly tests for the console chat backend.

Exercise the multimodal user-turn build and the vision directive WITHOUT
calling a live model, and lock in the invariant that the inline base64 payload
never leaks into the system snapshot.
"""

from __future__ import annotations

import base64
from typing import Any

from fdai.delivery.operator_api.routes.chat_prompt import (
    _build_messages,
    _vision_user_content,
)
from fdai.delivery.operator_api.routes.chat_prompt_content import _VISION_EVIDENCE_DIRECTIVE

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_DATA_URL = f"data:image/png;base64,{base64.b64encode(_PNG).decode()}"


def _attachment_context() -> dict[str, Any]:
    return {
        "routeId": "live",
        "_attachments": [
            {
                "name": "shot.png",
                "media_type": "image/png",
                "data_url": _DATA_URL,
                "byte_size": len(_PNG),
            }
        ],
    }


def _system_text(messages: list[dict[str, Any]]) -> str:
    return "\n".join(
        m["content"] for m in messages if m["role"] == "system" and isinstance(m["content"], str)
    )


def test_vision_user_content_plain_text_without_attachments() -> None:
    assert _vision_user_content("hello", None) == "hello"
    assert _vision_user_content("hello", []) == "hello"


def test_vision_user_content_builds_image_parts() -> None:
    content = _vision_user_content("how many people?", [{"data_url": _DATA_URL}])
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "how many people?"}
    assert content[1] == {"type": "image_url", "image_url": {"url": _DATA_URL}}


def test_vision_user_content_ignores_non_data_urls() -> None:
    # An http(s) URL never becomes an image part (defense in depth vs SSRF).
    content = _vision_user_content("x", [{"data_url": "https://evil.example/p.png"}])
    assert content == "x"


def test_vision_user_content_skips_non_dict_items() -> None:
    # A non-dict entry in the list is skipped; a valid image alongside it still
    # produces an image part.
    content = _vision_user_content("q", ["not-a-dict", {"data_url": _DATA_URL}])
    assert isinstance(content, list)
    assert content[1] == {"type": "image_url", "image_url": {"url": _DATA_URL}}


def test_vision_user_content_non_list_returns_text() -> None:
    assert _vision_user_content("q", "not-a-list") == "q"


def test_build_messages_attaches_image_and_directive() -> None:
    messages = _build_messages("how many people are in this photo?", _attachment_context(), [])
    # Vision directive is present as a system message.
    assert any(
        m["role"] == "system" and m["content"] == _VISION_EVIDENCE_DIRECTIVE for m in messages
    )
    # The user turn is multimodal with an image part.
    user = [m for m in messages if m["role"] == "user"][-1]
    assert isinstance(user["content"], list)
    kinds = [part["type"] for part in user["content"]]
    assert kinds == ["text", "image_url"]
    assert user["content"][1]["image_url"]["url"] == _DATA_URL


def test_build_messages_never_leaks_base64_into_system_snapshot() -> None:
    messages = _build_messages("describe it", _attachment_context(), [])
    system = _system_text(messages)
    b64_body = _DATA_URL.split(",", 1)[1]
    assert b64_body not in system
    assert "_attachments" not in system


def test_build_messages_without_attachments_stays_plain_text() -> None:
    messages = _build_messages("what is HIL?", {"routeId": "live"}, [])
    assert not any(
        m["role"] == "system" and m["content"] == _VISION_EVIDENCE_DIRECTIVE for m in messages
    )
    user = [m for m in messages if m["role"] == "user"][-1]
    assert user["content"] == "what is HIL?"

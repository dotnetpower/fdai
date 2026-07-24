"""Localized prose-quality contract for the Bragi web narrator prompt."""

from __future__ import annotations

from fdai.delivery.read_api.routes.chat_prompt import _build_messages


def _system_text(prompt: str, view_context: dict[str, object]) -> str:
    return "\n".join(
        message["content"]
        for message in _build_messages(prompt, view_context, [])
        if message["role"] == "system"
    )


def test_base_prompt_requires_proofread_standard_prose() -> None:
    system = _system_text("Explain this screen", {"routeId": "dashboard"})

    assert "Proofread only narrator prose" in system
    assert "Fix spelling" in system
    assert "stray characters" in system
    assert "language mixing" in system
    assert "Never alter quoted evidence values" in system


def test_korean_locale_directive_proofreads_without_rewriting_evidence() -> None:
    system = _system_text(
        "이 화면을 설명해줘",
        {"routeId": "dashboard", "_locale": "ko"},
    )

    assert "L3 rendering" in system
    assert "silently proofread only narrator-authored prose" in system
    assert "accidental language mixing" in system
    assert "Keep every evidence value, id, number, tool output, code fragment" in system
    assert "verbatim in English" not in system

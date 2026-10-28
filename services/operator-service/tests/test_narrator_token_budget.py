"""Boundary tests for token-aware narrator text fitting."""

from __future__ import annotations

import json

import pytest
import tiktoken
from fdai_operator_service.adapters.narrator_token_budget import (
    bounded_json,
    fit_text,
    text_tokens,
)

_REPLACEMENT = "\ufffd"
_KNOWN_MODELS = ("gpt-5", "gpt-4o")
_ALL_MODELS = (*_KNOWN_MODELS, "unknown-model")
_REPRESENTATIVE_TEXTS = {
    "repro": "고혈압·당뇨병·고지혈증",
    "korean_sentence": "오늘 서비스 지연의 원인은 배포 직후 DB 연결 포화로 확인되었습니다.",
    "korean_digits": "2026년 3월 14일 오전 9시 30분에 오류율이 12.5%에서 87%로 상승했습니다.",
    "emoji_leading": "🚀 배포가 시작되었습니다. 상태를 확인하세요.",
    "emoji_middle": "배포 완료 ✅ 후 지연 시간이 👍 정상으로 돌아왔습니다.",
    "emoji_trailing": "장애가 복구되었습니다 🎉🔥",
    "combining": "e\u0301a\u0300 한\u3099글 \u0915\u094d\u0937 👨\u200d👩\u200d👧\u200d👦 🇰🇷",
    "ascii": "The quick brown fox jumps over the lazy dog 0123456789.",
}


def _assert_fit(text: str, result: str, *, model: str, token_budget: int) -> None:
    assert text.startswith(result)
    assert _REPLACEMENT not in result
    assert text_tokens(result, model=model) <= token_budget


def test_reproduction_text_breaks_a_raw_token_prefix_decode() -> None:
    text = _REPRESENTATIVE_TEXTS["repro"]
    encoding = tiktoken.get_encoding("o200k_base")
    tokens = encoding.encode(text)

    raw_prefixes = [encoding.decode(tokens[:budget]) for budget in range(1, len(tokens))]

    assert any(_REPLACEMENT in prefix for prefix in raw_prefixes)


@pytest.mark.parametrize("model", _ALL_MODELS)
@pytest.mark.parametrize("name", sorted(_REPRESENTATIVE_TEXTS))
def test_fit_text_returns_safe_prefix_for_every_budget(name: str, model: str) -> None:
    text = _REPRESENTATIVE_TEXTS[name]
    total = text_tokens(text, model=model)

    for token_budget in range(1, total + 2):
        result, shortened = fit_text(text, model=model, token_budget=token_budget)

        _assert_fit(text, result, model=model, token_budget=token_budget)
        assert shortened is (token_budget < total)
        if not shortened:
            assert result == text


@pytest.mark.parametrize("model", _KNOWN_MODELS)
@pytest.mark.parametrize("name", sorted(_REPRESENTATIVE_TEXTS))
def test_fit_text_prefix_is_longest_for_known_encodings(name: str, model: str) -> None:
    text = _REPRESENTATIVE_TEXTS[name]
    total = text_tokens(text, model=model)

    for token_budget in range(1, total):
        result, _ = fit_text(text, model=model, token_budget=token_budget)
        longer = text[: len(result) + 1]
        # One more whole character either fits only by exceeding the budget or is the whole text.
        assert text_tokens(longer, model=model) > token_budget or longer == result


@pytest.mark.parametrize("model", _ALL_MODELS)
def test_fit_text_keeps_the_zero_budget_contract(model: str) -> None:
    assert fit_text("고혈압", model=model, token_budget=0) == ("", True)
    assert fit_text("고혈압", model=model, token_budget=-3) == ("", True)
    assert fit_text("", model=model, token_budget=0) == ("", False)


@pytest.mark.parametrize("model", _ALL_MODELS)
def test_fit_text_handles_empty_text_and_single_token_budget(model: str) -> None:
    assert fit_text("", model=model, token_budget=1) == ("", False)

    result, shortened = fit_text("고혈압", model=model, token_budget=1)

    assert shortened is True
    _assert_fit("고혈압", result, model=model, token_budget=1)


@pytest.mark.parametrize("model", _ALL_MODELS)
def test_fit_text_returns_exact_fit_unchanged(model: str) -> None:
    text = _REPRESENTATIVE_TEXTS["korean_sentence"]
    total = text_tokens(text, model=model)

    assert fit_text(text, model=model, token_budget=total) == (text, False)
    assert fit_text(text, model=model, token_budget=total + 100) == (text, False)

    result, shortened = fit_text(text, model=model, token_budget=total - 1)
    assert shortened is True
    assert len(result) < len(text)


def test_unknown_model_fallback_budgets_utf8_bytes_on_character_boundaries() -> None:
    text = "한글🚀ab"

    assert fit_text(text, model="unknown-model", token_budget=2) == ("", True)
    assert fit_text(text, model="unknown-model", token_budget=3) == ("한", True)
    assert fit_text(text, model="unknown-model", token_budget=6) == ("한글", True)
    assert fit_text(text, model="unknown-model", token_budget=10) == ("한글🚀", True)
    assert fit_text(text, model="unknown-model", token_budget=12) == (text, False)


@pytest.mark.parametrize("model", _KNOWN_MODELS)
def test_bounded_json_stays_valid_unicode_within_budget(model: str) -> None:
    value = {"질환": ["고혈압", "당뇨병", "고지혈증"], "상태": "🚀"}
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    total = text_tokens(encoded, model=model)

    for token_budget in range(1, total + 1):
        result, shortened = bounded_json(value, model=model, token_budget=token_budget)

        _assert_fit(encoded, result, model=model, token_budget=token_budget)
        assert shortened is (token_budget < total)

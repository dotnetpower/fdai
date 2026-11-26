"""Conservative prompt request-budget tests."""

from __future__ import annotations

from fdai.core.prompts import (
    estimate_chat_request_tokens,
    estimate_prompt_tokens,
    fit_prompt_to_token_budget,
)


def test_chat_request_estimate_counts_envelope_multibyte_text_and_output() -> None:
    messages = (
        {"role": "system", "content": "시스템"},
        {"role": "user", "content": "질문"},
    )

    estimate = estimate_chat_request_tokens(
        messages=messages,
        response_format={"type": "json_object"},
        reserved_output_tokens=128,
    )

    bare_text = estimate_prompt_tokens("시스템질문")
    assert estimate > bare_text + 128


def test_model_aware_estimate_uses_model_tokenizer_for_multibyte_text() -> None:
    text = "컨테이너 앱 상태를 확인해 주세요."

    assert estimate_prompt_tokens(text, model="gpt-5-mini") < estimate_prompt_tokens(text)


def test_unknown_model_family_keeps_conservative_byte_upper_bound() -> None:
    text = "알 수 없는 배포 이름"

    assert estimate_prompt_tokens(text, model="custom-deployment") == len(text.encode())


def test_fit_prompt_to_token_budget_preserves_longest_model_token_prefix() -> None:
    text = "alpha beta gamma delta"

    fitted, shortened = fit_prompt_to_token_budget(
        text,
        token_budget=3,
        model="gpt-5-mini",
    )

    assert shortened is True
    assert fitted
    assert estimate_prompt_tokens(fitted, model="gpt-5-mini") <= 3
    assert estimate_prompt_tokens(text[: len(fitted) + 1], model="gpt-5-mini") > 3

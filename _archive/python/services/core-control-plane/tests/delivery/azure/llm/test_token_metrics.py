"""Conversation request token metric helper tests."""

import pytest
from fdai.core.prompts import estimate_chat_request_tokens
from fdai.delivery.azure.llm.token_metrics import estimate_and_record_request_tokens


def test_estimate_and_record_uses_strictest_candidate() -> None:
    messages = [{"role": "user", "content": "확인할 리소스"}]
    response_format = {"type": "json_schema", "name": "answer"}
    models = ("gpt-4o", "unknown-deployment")
    expected = max(
        estimate_chat_request_tokens(
            messages=messages,
            response_format=response_format,
            reserved_output_tokens=128,
            model=model,
        )
        for model in models
    )

    estimate, exceeded = estimate_and_record_request_tokens(
        call_kind="test",
        messages=messages,
        response_format=response_format,
        reserved_output_tokens=128,
        models=models,
        budget=expected - 1,
    )

    assert estimate == expected
    assert exceeded is True


def test_estimate_and_record_rejects_empty_candidates() -> None:
    with pytest.raises(ValueError, match="at least one model"):
        estimate_and_record_request_tokens(
            call_kind="test",
            messages=(),
            response_format={},
            reserved_output_tokens=1,
            models=(),
            budget=None,
        )

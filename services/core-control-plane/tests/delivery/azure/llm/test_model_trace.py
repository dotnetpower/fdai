"""Bounded semantic model-trace redaction tests."""

from __future__ import annotations

import httpx
from fdai.delivery.azure.llm.model_trace import complete_model_trace, start_model_trace
from fdai.delivery.azure.llm.semantic_judgment import _response_mapping


def test_model_trace_redacts_sensitive_request_and_response_content() -> None:
    messages = (
        {
            "role": "user",
            "content": (
                "Read Bearer example-sensitive-token from "
                "https://private.example.com/path and /subscriptions/"
                "00000000-0000-0000-0000-000000000000/"
                "resourceGroups/example/providers/example/type/name"
            ),
        },
    )

    trace = complete_model_trace(
        start_model_trace(messages),
        call_id="semantic-judgment-1",
        kind="semantic-judgment",
        model="semantic-test",
        response_content=(
            "Reply to user@example.com about 10.0.0.1 with api_key=example-sensitive-value"
        ),
        usage={"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
    )

    rendered = str(trace)
    assert "example-sensitive" not in rendered
    assert "private.example.com" not in rendered
    assert "00000000-0000-0000-0000-000000000000" not in rendered
    assert "user@example.com" not in rendered
    assert "10.0.0.1" not in rendered
    assert trace["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "total_tokens": 15,
    }
    assert trace["status"] == "completed"


def test_response_mapping_preserves_only_measured_provider_usage() -> None:
    response = httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"primary_intent":"greeting"}'}}],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "total_tokens": 150,
                "estimated_tokens": 999,
            },
        },
    )

    proposal, content, usage = _response_mapping(response)

    assert proposal == {"primary_intent": "greeting"}
    assert content == '{"primary_intent":"greeting"}'
    assert usage is not None
    assert usage["prompt_tokens"] == 120

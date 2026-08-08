"""Tests for :func:`fdai.delivery.azure.llm.usage.extract_usage`."""

from __future__ import annotations

import pytest
from fdai.core.metering.usage import TokenUsage
from fdai.delivery.azure.llm.usage import extract_usage


def test_extracts_prompt_and_completion() -> None:
    envelope = {"usage": {"prompt_tokens": 120, "completion_tokens": 30}}
    assert extract_usage(envelope) == TokenUsage(prompt_tokens=120, completion_tokens=30)


def test_absent_completion_defaults_to_zero() -> None:
    # Embedding responses report prompt_tokens with no completion count.
    envelope = {"usage": {"prompt_tokens": 50}}
    assert extract_usage(envelope) == TokenUsage(prompt_tokens=50, completion_tokens=0)


@pytest.mark.parametrize(
    "envelope",
    [
        "not-a-mapping",
        {},
        {"usage": "nope"},
        {"usage": {"completion_tokens": 5}},  # no prompt_tokens
        {"usage": {"prompt_tokens": -1, "completion_tokens": 5}},
        {"usage": {"prompt_tokens": 5, "completion_tokens": -1}},
        {"usage": {"prompt_tokens": True, "completion_tokens": 5}},
        {"usage": {"prompt_tokens": 5, "completion_tokens": "x"}},
        {"usage": {"prompt_tokens": 1.5, "completion_tokens": 2}},
    ],
)
def test_malformed_usage_returns_none(envelope: object) -> None:
    assert extract_usage(envelope) is None

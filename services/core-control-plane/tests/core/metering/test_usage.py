"""Tests for :class:`fdai.core.metering.usage.TokenUsage`."""

from __future__ import annotations

import pytest
from fdai.core.metering.usage import TokenUsage


def test_total_tokens_is_derived() -> None:
    usage = TokenUsage(prompt_tokens=120, completion_tokens=30)
    assert usage.total_tokens == 150


def test_zero_is_additive_identity() -> None:
    usage = TokenUsage(prompt_tokens=5, completion_tokens=7)
    assert usage + TokenUsage.zero() == usage
    assert TokenUsage.zero().total_tokens == 0


def test_add_is_componentwise() -> None:
    a = TokenUsage(prompt_tokens=10, completion_tokens=2)
    b = TokenUsage(prompt_tokens=3, completion_tokens=4)
    assert a + b == TokenUsage(prompt_tokens=13, completion_tokens=6)


def test_sum_rollup_over_many() -> None:
    parts = [TokenUsage(prompt_tokens=i, completion_tokens=1) for i in range(4)]
    rolled = sum(parts, TokenUsage.zero())
    assert rolled == TokenUsage(prompt_tokens=6, completion_tokens=4)


def test_add_wrong_type_returns_notimplemented() -> None:
    assert TokenUsage(prompt_tokens=1, completion_tokens=1).__add__(42) is NotImplemented


@pytest.mark.parametrize(("prompt", "completion"), [(-1, 0), (0, -1)])
def test_negative_tokens_rejected(prompt: int, completion: int) -> None:
    with pytest.raises(ValueError, match="MUST be >= 0"):
        TokenUsage(prompt_tokens=prompt, completion_tokens=completion)

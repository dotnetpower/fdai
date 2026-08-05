"""Model-family-specific completion body tests."""

from __future__ import annotations

import pytest

from fdai.delivery.azure.llm.completion_body import completion_body_params


@pytest.mark.parametrize(
    "model",
    ["gpt-5", "gpt-5.4-mini", "primary-gpt-5.4-mini", "o1", "o3-mini", "o4-mini"],
)
def test_reasoning_families_use_completion_tokens(model: str) -> None:
    assert completion_body_params(model, temperature=0.2, max_tokens=800) == {
        "max_completion_tokens": 800
    }


@pytest.mark.parametrize("model", ["gpt-4o", "gpt-4.1-mini", "example-deployment"])
def test_classic_families_keep_temperature_and_max_tokens(model: str) -> None:
    assert completion_body_params(model, temperature=0.2, max_tokens=800) == {
        "temperature": 0.2,
        "max_tokens": 800,
    }

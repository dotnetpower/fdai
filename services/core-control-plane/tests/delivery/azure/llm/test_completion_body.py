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


def test_a_capability_named_target_chooses_its_token_field_by_family() -> None:
    from fdai.delivery.azure.llm.completion_body import target_body_params
    from fdai.delivery.azure.llm.request_target import ModelRequestTarget

    def target(deployment: str, family: str | None) -> ModelRequestTarget:
        return ModelRequestTarget(
            endpoint="https://example.com",
            deployment=deployment,
            api_version="2024-06-01",
            model_family=family,
        )

    named_by_capability = target("t2.reasoner.primary", "gpt-5.4")
    assert target_body_params(named_by_capability, temperature=0.0, max_tokens=64) == {
        "max_completion_tokens": 64
    }
    # Without a family the deployment name decides, as before.
    assert target_body_params(target("gpt-4o", None), temperature=0.0, max_tokens=64) == {
        "temperature": 0.0,
        "max_tokens": 64,
    }


def test_a_reasoning_effort_bounds_only_the_families_that_reason() -> None:
    assert completion_body_params(
        "gpt-5.4", temperature=0.0, max_tokens=64, reasoning_effort="low"
    ) == {"max_completion_tokens": 64, "reasoning_effort": "low"}
    assert completion_body_params(
        "gpt-4.1-mini", temperature=0.0, max_tokens=64, reasoning_effort="low"
    ) == {"temperature": 0.0, "max_tokens": 64}

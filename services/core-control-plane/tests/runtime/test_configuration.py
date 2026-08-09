"""Runtime model endpoint reference resolution tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.runtime.configuration import _catalog_root_candidates, _direct_model_endpoint_resolver


def test_catalog_candidates_prefer_complete_container_payload() -> None:
    candidates = _catalog_root_candidates(
        Path("/app/.venv/lib/python3.13/site-packages/fdai/runtime/configuration.py"),
        Path("/app"),
    )

    assert candidates[0] == Path("/app/rule-catalog")
    assert candidates.index(Path("/app/rule-catalog")) < candidates.index(
        Path("/app/.venv/rule-catalog")
    )


def test_direct_model_endpoint_resolver_accepts_only_matching_account_ref() -> None:
    endpoint = "https://oai-example.openai.azure.com/"
    resolve = _direct_model_endpoint_resolver(endpoint)

    assert resolve("azure-openai:oai-example") == endpoint
    with pytest.raises(ValueError, match="does not match"):
        resolve("azure-openai:other")


@pytest.mark.parametrize(
    "endpoint",
    (
        "http://oai-example.openai.azure.com",
        "https://models.example.com",
        "https://user@example.openai.azure.com",
        "https://oai-example.openai.azure.com/openai?api-version=1",
    ),
)
def test_direct_model_endpoint_resolver_rejects_invalid_endpoint(endpoint: str) -> None:
    with pytest.raises(ValueError, match="Azure OpenAI|identify|origin"):
        _direct_model_endpoint_resolver(endpoint)

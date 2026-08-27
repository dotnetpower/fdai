"""Runtime model endpoint reference resolution tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.runtime.configuration import (
    _catalog_root_candidates,
    _direct_model_endpoint_resolver,
    _model_endpoint_resolver,
)


def test_catalog_candidates_prefer_complete_container_payload() -> None:
    candidates = _catalog_root_candidates(
        Path("/app/.venv/lib/python3.13/site-packages/fdai/runtime/configuration.py"),
        Path("/app"),
    )

    assert candidates[0] == Path("/app/rule-catalog")
    assert candidates.index(Path("/app/rule-catalog")) < candidates.index(
        Path("/app/.venv/rule-catalog")
    )


def test_bootstrap_binds_symptom_index_to_resolved_catalog() -> None:
    bootstrap = Path("services/core-control-plane/src/fdai/runtime/bootstrap_core.py").read_text(
        encoding="utf-8"
    )

    assert 'build_from_promoted(_resolve_catalog_root() / "chaos-scenarios")' in bootstrap


def test_semantic_bootstrap_uses_account_qualified_endpoint_map() -> None:
    bootstrap = Path(
        "services/core-control-plane/src/fdai/runtime/bootstrap_semantics.py"
    ).read_text(encoding="utf-8")

    assert "_model_endpoint_resolver(" in bootstrap
    assert 'environment.get("FDAI_MODEL_ENDPOINTS_JSON")' in bootstrap
    assert "_direct_model_endpoint_resolver(" not in bootstrap


def test_direct_model_endpoint_resolver_accepts_only_matching_account_ref() -> None:
    endpoint = "https://oai-example.openai.azure.com/"
    resolve = _direct_model_endpoint_resolver(endpoint)

    assert resolve("azure-openai:oai-example") == endpoint
    with pytest.raises(ValueError, match="does not match"):
        resolve("azure-openai:other")


def test_model_endpoint_resolver_accepts_exact_foundry_account_map() -> None:
    primary = "https://oai-example.openai.azure.com/"
    foundry = "https://aif-example.services.ai.azure.com/"
    resolve = _model_endpoint_resolver(
        primary,
        '{"azure-foundry:aif-example":"https://aif-example.services.ai.azure.com/"}',
    )

    assert resolve("azure-openai:oai-example") == primary
    assert resolve("azure-foundry:aif-example") == foundry


@pytest.mark.parametrize(
    "mapping",
    [
        "not-json",
        "{}",
        '{"azure-foundry:wrong":"https://aif-example.services.ai.azure.com/"}',
        '{"azure-openai:aif-example":"https://aif-example.services.ai.azure.com/"}',
    ],
)
def test_model_endpoint_resolver_rejects_invalid_maps(mapping: str) -> None:
    with pytest.raises(ValueError):
        _model_endpoint_resolver(
            "https://oai-example.openai.azure.com/",
            mapping,
        )


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

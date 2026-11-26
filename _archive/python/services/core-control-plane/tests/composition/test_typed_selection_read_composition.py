"""Governed typed-selection composition binds only the reviewed exact model pin."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fdai.composition import typed_selection_read as module
from fdai.composition.semantic_query_model_targets import ModelRequestTarget
from fdai.composition.typed_selection_read import (
    GOVERNED_READ_CONFIG_RELATIVE_PATH,
    GovernedTypedSelectionModelPin,
    compose_typed_selection_read,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_ROOT = Path(__file__).resolve().parents[4]
_CONFIG = _ROOT / GOVERNED_READ_CONFIG_RELATIVE_PATH
_TARGET = ModelRequestTarget(
    endpoint="https://example.invalid",
    deployment="t2.ontology.council.alpha",
    api_version="2024-10-21",
    model_family="gpt-5.6-sol",
)


class _Identity:
    async def get_token(self, audience: str) -> Any:
        raise AssertionError("composition does not authenticate")


def _container() -> Any:
    return SimpleNamespace(
        decision_evidence_admission_provider=None,
        held_model_capabilities=frozenset(),
    )


async def test_governed_read_composes_only_the_exact_reviewed_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = GovernedTypedSelectionModelPin.load(_CONFIG)
    capability = SimpleNamespace(family=pin.model_family, version=pin.model_version)
    monkeypatch.setattr(module, "resolved_models_for_binding", lambda _container: object())
    monkeypatch.setattr(module, "_capability", lambda *_args, **_kwargs: capability)

    def target_for_capability(
        _resolved: object, capability_id: str, **_kwargs: object
    ) -> ModelRequestTarget:
        assert capability_id == "t2.ontology.council.alpha"
        return _TARGET

    monkeypatch.setattr(module, "model_target_for_capability", target_for_capability)
    monkeypatch.setattr(module, "AzureOpenAISemanticPlanningModel", lambda **_kwargs: object())
    async with httpx.AsyncClient() as http:
        reader = compose_typed_selection_read(
            container=_container(),
            environment={"FDAI_SOURCE_REVISION": "0" * 40},
            state_store=InMemoryStateStore(),
            index=SimpleNamespace(workers=object()),
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=http,
            endpoint=None,
            endpoint_resolver=None,
            catalog_root=_ROOT / "rule-catalog",
            config_path=_CONFIG,
            owner_loop=asyncio.get_running_loop(),
        )
    assert reader.proposer is not None


async def test_governed_read_rejects_model_family_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "resolved_models_for_binding", lambda _container: object())
    monkeypatch.setattr(
        module,
        "_capability",
        lambda *_args, **_kwargs: SimpleNamespace(family="other", version="2026-07-09"),
    )
    monkeypatch.setattr(
        module,
        "model_target_for_capability",
        lambda *_args, **_kwargs: _TARGET,
    )
    async with httpx.AsyncClient() as http:
        reader = compose_typed_selection_read(
            container=_container(),
            environment={"FDAI_SOURCE_REVISION": "0" * 40},
            state_store=InMemoryStateStore(),
            index=SimpleNamespace(workers=object()),
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=http,
            endpoint=None,
            endpoint_resolver=None,
            catalog_root=_ROOT / "rule-catalog",
            config_path=_CONFIG,
            owner_loop=asyncio.get_running_loop(),
        )
    assert reader.proposer is None

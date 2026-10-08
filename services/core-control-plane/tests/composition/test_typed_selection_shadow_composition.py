"""The shadow proposer binds only the exact qualified model, prompt, and reviewed policy."""

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fdai.composition import typed_selection_shadow as module
from fdai.composition.semantic_query_model_targets import ModelRequestTarget
from fdai.composition.typed_selection_shadow import (
    SHADOW_CONFIG_RELATIVE_PATH,
    TypedSelectionShadowPin,
    compose_typed_selection_shadow,
)
from fdai.shared.config.models import LlmMode

_ROOT = Path(__file__).resolve().parents[4]
_CONFIG = _ROOT / SHADOW_CONFIG_RELATIVE_PATH
_TARGET = ModelRequestTarget(
    endpoint="https://example.invalid",
    deployment="example-deployment",
    api_version="2024-10-21",
    model_family="gpt-5.6-sol",
)


@dataclass
class _Capability:
    family: str = "gpt-5.6-sol"
    version: str = "2026-07-09"


class _Identity:
    async def get_token(self, audience: str) -> Any:
        raise AssertionError("composition never authenticates")


def _container() -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(llm=SimpleNamespace(mode=LlmMode.AZURE)),
        held_model_capabilities=frozenset(),
    )


async def _compose(
    monkeypatch: pytest.MonkeyPatch,
    *,
    environment: dict[str, str] | None = None,
    capability: _Capability | None = None,
    config_path: Path = _CONFIG,
) -> module.TypedSelectionShadowComposition:
    monkeypatch.setattr(module, "resolved_models_for_binding", lambda _container: object())
    monkeypatch.setattr(
        module, "_capability", lambda *_args, **_kwargs: capability or _Capability()
    )
    monkeypatch.setattr(module, "t2_model_targets", lambda *_args, **_kwargs: (_TARGET,))
    async with httpx.AsyncClient() as http:
        return compose_typed_selection_shadow(
            container=_container(),
            environment=(
                environment
                if environment is not None
                else {"FDAI_ONTOLOGY_TYPED_SELECTION_SHADOW": "enabled"}
            ),
            identity=_Identity(),  # type: ignore[arg-type]
            http_client=http,
            endpoint=None,
            endpoint_resolver=None,
            catalog_root=_ROOT / "rule-catalog",
            config_path=config_path,
            owner_loop=asyncio.get_running_loop(),
        )


async def test_reviewed_qualified_binding_is_composed_only_on_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disabled = await _compose(monkeypatch, environment={})
    assert disabled.binding is None
    assert disabled.reason == "typed_selection_shadow_disabled"
    bound = await _compose(monkeypatch)
    assert bound.reason == "typed_selection_shadow_bound"
    assert bound.binding is not None
    pin = TypedSelectionShadowPin.load(_CONFIG)
    assert bound.binding.data_handling_policy_digest == pin.data_handling_policy_digest
    manifest = bound.binding.expected_binding.prompt_manifest
    assert manifest.system_text_sha256 == pin.system_text_sha256
    assert manifest.profile_digest == pin.prompt_profile_digest


@pytest.mark.parametrize("capability", [_Capability(family="other"), _Capability(version="x")])
async def test_unqualified_model_is_not_bound(
    monkeypatch: pytest.MonkeyPatch, capability: _Capability
) -> None:
    result = await _compose(monkeypatch, capability=capability)
    assert result.binding is None
    assert result.reason == "typed_selection_shadow_model_not_qualified"


async def test_changed_prompt_pin_is_not_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    changed = tmp_path / "shadow.json"
    changed.write_text(
        _CONFIG.read_text().replace(
            TypedSelectionShadowPin.load(_CONFIG).system_text_sha256, "0" * 64
        )
    )
    result = await _compose(monkeypatch, config_path=changed)
    assert result.reason == "typed_selection_shadow_prompt_not_qualified"


async def test_policy_that_grants_authority_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    changed = tmp_path / "shadow.json"
    changed.write_text(_CONFIG.read_text().replace('"none"', '"candidate"'))
    result = await _compose(monkeypatch, config_path=changed)
    assert result.reason == "typed_selection_shadow_policy_unavailable"


def test_pin_matches_the_recorded_qualification_identity() -> None:
    pin = TypedSelectionShadowPin.load(_CONFIG)
    assert (pin.model_family, pin.model_version, pin.reasoning_effort) == (
        "gpt-5.6-sol",
        "2026-07-09",
        "low",
    )
    assert replace(pin, timeout_seconds=20.0) == pin

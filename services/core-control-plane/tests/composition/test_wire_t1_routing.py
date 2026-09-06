"""Probe opt-in and verified bindings are resolved without making model calls."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from fdai.composition import wire_t1_routing
from fdai.shared.config.models import LlmMode
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.composition.test_wire_adaptive_conversation import _NoIdentityCalls, _resolved


@pytest.mark.parametrize(
    ("environment", "held", "enabled"),
    [
        ({}, frozenset(), False),
        ({"FDAI_T1_MINI_PROBE_ENABLED": "1"}, frozenset(), True),
        ({"FDAI_T1_MINI_PROBE_ENABLED": "1"}, frozenset({"t1.judge"}), None),
    ],
)
async def test_probe_composition_is_explicit_and_preserves_holds(
    monkeypatch, environment, held, enabled
):
    resolved = _resolved()
    resolved = replace(
        resolved,
        capabilities=tuple(
            replace(
                capability,
                family={
                    "t1.judge": "gpt-5.4-mini",
                    "t1.reviewer": "gpt-5-mini",
                }.get(capability.name, capability.family),
            )
            for capability in resolved.capabilities
        ),
    )
    container = Mock()
    container.config.llm.mode = LlmMode.AZURE
    container.config.llm.resolved_models_path = Path("resolved-models.json")
    container.held_model_capabilities = held
    monkeypatch.setattr(wire_t1_routing, "resolved_models_for_binding", lambda _: resolved)
    async with httpx.AsyncClient() as client:
        probe = wire_t1_routing.build_t1_mini_probe(
            container=container,
            environment=environment,
            identity=_NoIdentityCalls(),
            http_client=client,
            state_store=InMemoryStateStore(),
            endpoint="https://example.com",
            endpoint_resolver=None,
        )
        if enabled is None:
            assert probe is None
        else:
            assert probe is not None
            assert probe.routing.enabled is enabled
            assert probe.routing.interval_seconds == 300
            assert len(probe.routing.candidates) == 2


@pytest.mark.parametrize(
    "environment",
    [
        {"FDAI_T1_MINI_PROBE_ENABLED": "sometimes"},
        {"FDAI_NARRATOR_PROBE_INTERVAL_SECONDS": "29"},
        {"FDAI_NARRATOR_PROBE_INTERVAL_SECONDS": "3601"},
    ],
)
def test_invalid_probe_configuration_fails_before_binding(environment):
    with pytest.raises(ValueError):
        wire_t1_routing.build_t1_mini_probe(
            container=Mock(),
            environment=environment,
            identity=None,
            http_client=None,
            state_store=InMemoryStateStore(),
            endpoint=None,
            endpoint_resolver=None,
        )

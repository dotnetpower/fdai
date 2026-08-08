"""Composition binding tests for MSCP shadow effect observation."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from fdai.composition import default_container
from fdai.core.mscp_profile import ExpectedEffect, ObservedEffect
from fdai.shared.config import AppConfig
from fdai.shared.contracts.models import Action


def _config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "azure": {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "region": "krc",
            },
            "kafka": {
                "bootstrap_servers": "example:9093",
                "topic_events": "aw.change.events",
            },
            "postgres": {"host": "example.local", "database": "fdai"},
            "runtime": {"env": "dev"},
            "llm": {"mode": "local-fake", "t2_primary_latency_routing": False},
        }
    )


async def _predict(action: Action) -> ExpectedEffect | None:
    del action
    return None


async def _observe(
    action: Action,
    expected: ExpectedEffect,
) -> ObservedEffect | None:
    del action, expected
    return None


def test_default_container_leaves_mscp_shadow_observation_unbound() -> None:
    container = default_container(_config())
    assert container.mscp_expected_effect_provider is None
    assert container.mscp_effect_observer is None


def test_container_accepts_the_complete_mscp_provider_pair() -> None:
    container = replace(
        default_container(_config()),
        mscp_expected_effect_provider=_predict,
        mscp_effect_observer=_observe,
    )
    assert container.mscp_expected_effect_provider is _predict
    assert container.mscp_effect_observer is _observe


@pytest.mark.parametrize(
    "updates",
    [
        {"mscp_expected_effect_provider": _predict},
        {"mscp_effect_observer": _observe},
    ],
)
def test_container_rejects_partial_mscp_binding(updates: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="MUST be bound together"):
        replace(default_container(_config()), **updates)

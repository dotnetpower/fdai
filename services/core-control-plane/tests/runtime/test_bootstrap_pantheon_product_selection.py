"""Pantheon composition hands the control loop's product selection to Forseti (#1541).

``initialize_pantheon`` reads ``governed_execution_selected`` from the composed control loop,
which derives it from the #1553 ``RuntimeProductSelection``. Driving the real initializer with
both values proves that Forseti receives exactly that value, so dropping the keyword argument or
hard-coding it fails here. Every backing store and transport is in memory.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fdai.agents import Forseti
from fdai.composition import default_container
from fdai.core.chaos.symptom_index import build_from_entries
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.runtime.bootstrap_lifecycle import (
    build_mutation_dependency_readiness,
    build_runtime_saga,
    runtime_positive_integer,
    semantic_router_config_from_env,
)
from fdai.runtime.bootstrap_pantheon import PantheonInitialization, initialize_pantheon
from fdai.runtime.providers import _build_operator_memory_store
from fdai.runtime.readiness import RuntimeReadinessState
from fdai.shared.config import AppConfig
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _DiscoveryActivation:
    """Discovery stays disabled; the initializer only binds and evaluates it."""

    def is_enabled(self) -> bool:
        return False

    def bind_shadow_decision_count(self, counter: Any) -> None:
        self.counter = counter

    async def evaluate(self) -> None:
        return None


def _control_loop(*, governed_execution_selected: bool) -> Any:
    """Expose only the composed control-loop facts that Pantheon initialization reads."""

    return SimpleNamespace(
        governed_execution_selected=governed_execution_selected,
        ontology_instance_store=None,
        ontology_release=None,
        process_runtime_store=None,
        action_types=(),
        alert_workflows=None,
        alert_plan_artifacts=None,
        bind_case_history_reuse=lambda materializer: None,
    )


async def _unused(*args: Any, **kwargs: Any) -> bool:
    raise AssertionError("Pantheon initialization must not invoke incident callbacks")


@pytest.mark.parametrize("selected", [True, False])
async def test_initialize_pantheon_passes_the_product_selection_to_forseti(
    app_config: AppConfig,
    selected: bool,
) -> None:
    store = InMemoryStateStore()
    settings = RuntimeSettingsService(store=None, env={})

    result = await initialize_pantheon(
        PantheonInitialization(
            container=default_container(app_config),
            http_client=None,
            identity=None,
            bus=InMemoryEventBus(),
            incident_audit_store=store,
            startup_readiness=RuntimeReadinessState(),
            runtime_saga=build_runtime_saga(store),
            runtime_values=settings.environment_values(),
            runtime_settings=settings,
            discovery_activation=_DiscoveryActivation(),  # type: ignore[arg-type]
            control_loop=_control_loop(governed_execution_selected=selected),
            rule_generation_reconciliation=None,
            rule_generation_binding=SimpleNamespace(activation_binder=None),  # type: ignore[arg-type]
            open_incident_candidate=_unused,
            resolve_verified_incident=_unused,  # type: ignore[arg-type]
            read_investigation_hook=None,
            runtime_symptom_index=build_from_entries(()),
            stage_topic="fdai.stage",
            environment={},
            build_runtime_workload_identity=lambda *args, **kwargs: None,  # type: ignore[arg-type,return-value]
            build_operator_memory_store=_build_operator_memory_store,
            build_inventory_delta_projector=lambda: None,
            runtime_positive_integer=runtime_positive_integer,
            build_mutation_dependency_readiness=build_mutation_dependency_readiness,
            semantic_router_config_from_env=semantic_router_config_from_env,
        )
    )

    assert result.runtime is not None
    forseti = result.runtime.agents["Forseti"]
    assert isinstance(forseti, Forseti)
    assert forseti._governed_execution_selected is selected  # noqa: SLF001

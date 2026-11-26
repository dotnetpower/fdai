"""Selected development authority needs the same logical lock as enforce mode."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fdai.agents import DevelopmentRuntimeBindings, PantheonRuntime
from fdai.composition import default_container
from fdai.core.chaos.symptom_index import build_from_entries
from fdai.delivery.persistence import PostgresAdvisoryResourceLock
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.runtime import bootstrap_pantheon as bootstrap
from fdai.runtime.bootstrap_lifecycle import (
    build_mutation_dependency_readiness,
    build_runtime_saga,
    runtime_positive_integer,
    semantic_router_config_from_env,
)
from fdai.runtime.bootstrap_pantheon import PantheonInitialization, initialize_pantheon
from fdai.runtime.development_authority import (
    development_control_loop_kwargs,
    pantheon_development_bindings,
)
from fdai.runtime.providers import _build_operator_memory_store
from fdai.runtime.readiness import RuntimeReadinessState
from fdai.shared.config import AppConfig
from fdai.shared.providers.testing import InMemoryStateStore
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

from .test_approval_profile_composition import _control_loop_stub, _DiscoveryActivation, _unused
from .test_development_authority_composition import NOW, _environment


@pytest.mark.parametrize("enforce", [False, True])
@pytest.mark.parametrize("selected", [False, True])
async def test_real_initializer_binds_lock_for_each_selected_safety_path(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
    enforce: bool,
    selected: bool,
) -> None:
    store = InMemoryStateStore()
    settings = RuntimeSettingsService(store=None, env={})
    loop = _control_loop_stub()
    if selected:
        parts = development_control_loop_kwargs(_environment(), store=store, clock=lambda: NOW)
        loop.development_authority_parts = (
            parts["development_profile"],
            parts["development_binding_source"],
            parts["development_executor_principal"],
        )
    bindings = pantheon_development_bindings(loop, clock=lambda: NOW)
    selections: list[object] = []

    def select(current: object) -> DevelopmentRuntimeBindings | None:
        assert current is loop
        selections.append(current)
        return bindings

    monkeypatch.setattr(bootstrap.pantheon_inputs, "pantheon_development_bindings", select)
    monkeypatch.setattr(bootstrap, "pantheon_enforce_enabled", lambda *args: enforce)
    original_build = PantheonRuntime.build
    captured: dict[str, Any] = {}

    def build(**kwargs: Any) -> PantheonRuntime:
        captured.update(kwargs)
        return original_build(**kwargs)

    monkeypatch.setattr(PantheonRuntime, "build", build)
    config = PantheonInitialization(
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
        control_loop=loop,
        rule_generation_reconciliation=None,
        rule_generation_binding=SimpleNamespace(activation_binder=None),  # type: ignore[arg-type]
        open_incident_candidate=_unused,
        resolve_verified_incident=_unused,  # type: ignore[arg-type]
        read_investigation_hook=None,
        runtime_symptom_index=build_from_entries(()),
        stage_topic="fdai.stage",
        environment={"FDAI_RESOURCE_LOCK_DSN": "postgresql://localhost:5433/validation"},
        build_runtime_workload_identity=lambda *args, **kwargs: None,  # type: ignore[arg-type,return-value]
        build_operator_memory_store=_build_operator_memory_store,
        build_inventory_delta_projector=lambda: None,
        runtime_positive_integer=runtime_positive_integer,
        build_mutation_dependency_readiness=build_mutation_dependency_readiness,
        semantic_router_config_from_env=semantic_router_config_from_env,
    )
    if enforce or selected:
        with pytest.raises(ValueError, match="explicit durable safety bindings") as refused:
            await initialize_pantheon(config)
        assert "rollback_executors" in str(refused.value)
    else:
        result = await initialize_pantheon(config)
        assert result.runtime is not None
    assert captured["enforce"] is enforce
    assert captured["development_authority"] is bindings
    assert selections == [loop]
    if enforce or selected:
        lock = captured["execution_resource_lock"]
        assert isinstance(lock, PostgresAdvisoryResourceLock)
        assert lock.distributed
        assert "execution_resource_lock" not in str(refused.value)
    else:
        assert captured["execution_resource_lock"] is None

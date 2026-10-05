"""Runtime composition wiring for the single-operator approval profile."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fdai.agents import Forseti
from fdai.agents.var import Var
from fdai.composition import default_container
from fdai.core.chaos.symptom_index import build_from_entries
from fdai.core.executor import (
    DirectApiShadowExecutor,
    InProcessThorExecutionPort,
    MutationDependencyReadiness,
    ShadowExecutor,
    ToolCallShadowExecutor,
)
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.runtime.approval_profile import (
    PROFILE_JSON_ENV,
    approval_profile_policy_digest,
)
from fdai.runtime.bootstrap_lifecycle import (
    build_mutation_dependency_readiness,
    build_runtime_saga,
    runtime_positive_integer,
    semantic_router_config_from_env,
)
from fdai.runtime.bootstrap_pantheon import PantheonInitialization, initialize_pantheon
from fdai.runtime.control_loop import _build_control_loop
from fdai.runtime.development_authority import PROFILE_ENV as DEVELOPMENT_PROFILE_ENV
from fdai.runtime.providers import _build_operator_memory_store
from fdai.runtime.readiness import RuntimeReadinessState
from fdai.shared.config import AppConfig
from fdai.shared.providers.testing import InMemoryStateStore
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai_service_contracts.product_profile import ProductAddOn, ProductProfile

_OPERATOR = "operator@example.com"
_EXECUTOR = "thor-runtime-executor"


def _profile_json() -> str:
    payload: dict[str, object] = {
        "revision_id": "approval-profile-r1",
        "approval_profile": "single-operator-production",
        "executor_principal": _EXECUTOR,
        "effective_from": "2020-01-01T00:00:00+00:00",
        "operator_principal": _OPERATOR,
    }
    payload["policy_digest"] = approval_profile_policy_digest(payload)
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _governed_config(config: AppConfig) -> AppConfig:
    return config.model_copy(
        update={
            "product_profile": ProductProfile(
                add_ons=(
                    ProductAddOn.ENTERPRISE_IDENTITY_GOVERNANCE,
                    ProductAddOn.GOVERNED_EXECUTION,
                    ProductAddOn.NOTIFICATIONS,
                )
            )
        }
    )


def _thor_port() -> InProcessThorExecutionPort:
    return InProcessThorExecutionPort(
        pr_native=MagicMock(spec=ShadowExecutor),
        direct_api=MagicMock(spec=DirectApiShadowExecutor),
        tool_call=MagicMock(spec=ToolCallShadowExecutor),
    )


def _readiness() -> MutationDependencyReadiness:
    return MutationDependencyReadiness(
        saga_audit_durable=True,
        vidar_recovery_contracts=frozenset({"state_forward_only"}),
    )


def test_control_loop_profile_env_reaches_loop_and_hil_coordinator(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PROFILE_JSON_ENV, _profile_json())
    loop = _build_control_loop(
        default_container(_governed_config(app_config)),
        thor_execution_port=_thor_port(),
        mutation_dependency_readiness=_readiness(),
    )

    coordinator = loop._hil_resume_coordinator
    assert coordinator is not None
    assert loop._approval_profile is coordinator._approval_profile
    assert loop._approval_profile is not None
    assert loop._approval_profile.operator_principal == _OPERATOR


def test_absent_profile_env_keeps_control_loop_default(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PROFILE_JSON_ENV, raising=False)
    loop = _build_control_loop(
        default_container(_governed_config(app_config)),
        thor_execution_port=_thor_port(),
        mutation_dependency_readiness=_readiness(),
    )

    assert loop._approval_profile is None
    assert loop._hil_resume_coordinator is not None
    assert loop._hil_resume_coordinator._approval_profile is None


class _DiscoveryActivation:
    def is_enabled(self) -> bool:
        return False

    def bind_shadow_decision_count(self, counter: Any) -> None:
        self.counter = counter

    async def evaluate(self) -> None:
        return None


def _control_loop_stub() -> Any:
    return SimpleNamespace(
        governed_execution_selected=True,
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


async def test_pantheon_profile_env_reaches_forseti_and_var(app_config: AppConfig) -> None:
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
            control_loop=_control_loop_stub(),
            rule_generation_reconciliation=None,
            rule_generation_binding=SimpleNamespace(activation_binder=None),  # type: ignore[arg-type]
            open_incident_candidate=_unused,
            resolve_verified_incident=_unused,  # type: ignore[arg-type]
            read_investigation_hook=None,
            runtime_symptom_index=build_from_entries(()),
            stage_topic="fdai.stage",
            environment={PROFILE_JSON_ENV: _profile_json()},
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
    var = result.runtime.agents["Var"]
    assert isinstance(forseti, Forseti)
    assert isinstance(var, Var)
    assert forseti._approval_profile is var._approval_profile  # noqa: SLF001
    assert forseti._approval_profile is not None  # noqa: SLF001
    assert forseti._approval_profile.operator_principal == _OPERATOR  # noqa: SLF001


def test_development_and_approval_profiles_fail_closed(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PROFILE_JSON_ENV, _profile_json())
    monkeypatch.setenv(DEVELOPMENT_PROFILE_ENV, '{"profile_id":"dev"}')

    with pytest.raises(RuntimeError, match="mutually exclusive"):
        _build_control_loop(
            default_container(_governed_config(app_config)),
            thor_execution_port=_thor_port(),
            mutation_dependency_readiness=_readiness(),
        )

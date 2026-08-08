"""Focused runtime binding checks for the in-process Thor execution port."""

from __future__ import annotations

from inspect import signature
from unittest.mock import MagicMock

import pytest
from fdai.agents import Saga, StateStoreAuditChainAdapter
from fdai.composition import default_container
from fdai.core.executor import (
    DirectApiShadowExecutor,
    InProcessThorExecutionPort,
    MutationDependencyReadiness,
    ShadowExecutor,
    ToolCallShadowExecutor,
)
from fdai.runtime.bootstrap_lifecycle import build_mutation_dependency_readiness
from fdai.runtime.control_loop import _build_control_loop, _legacy_executor_bindings
from fdai.shared.config import AppConfig
from fdai.shared.providers.testing import InMemoryStateStore


def test_runtime_accepts_one_thor_port_and_preserves_executor_identity() -> None:
    pr_native = MagicMock(spec=ShadowExecutor)
    direct_api = MagicMock(spec=DirectApiShadowExecutor)
    tool_call = MagicMock(spec=ToolCallShadowExecutor)
    port = InProcessThorExecutionPort(
        pr_native=pr_native,
        direct_api=direct_api,
        tool_call=tool_call,
    )

    bindings = _legacy_executor_bindings(port)

    assert "thor_execution_port" in signature(_build_control_loop).parameters
    assert bindings == (pr_native, direct_api, tool_call)


def test_thor_safety_dependencies_only_block_incomplete_mutation() -> None:
    incomplete = MutationDependencyReadiness(
        saga_audit_durable=False,
        vidar_recovery_contracts=frozenset(),
    )

    incomplete.require_for_mode(enforce=False)

    with pytest.raises(
        ValueError,
        match="durable_saga, rollback_executors",
    ):
        incomplete.require_for_mode(enforce=True)


def test_runtime_projects_existing_saga_and_vidar_bindings_into_readiness() -> None:
    async def rollback_executor(_payload: dict[str, object]) -> str:
        return "rollback-receipt"

    saga = Saga(
        audit_chain=StateStoreAuditChainAdapter(store=InMemoryStateStore()),
    )
    rollback_executors = {"state_forward_only": rollback_executor}

    readiness = build_mutation_dependency_readiness(
        saga=saga,
        rollback_executors=rollback_executors,
    )
    readiness.require_for_mode(enforce=True)

    assert readiness.mutation_ready is True
    assert readiness.saga_audit_durable is True
    assert readiness.vidar_recovery_contracts == frozenset(rollback_executors)


def test_core_and_hil_share_port_instances_and_readiness(app_config: AppConfig) -> None:
    pr_native = MagicMock(spec=ShadowExecutor)
    direct_api = MagicMock(spec=DirectApiShadowExecutor)
    tool_call = MagicMock(spec=ToolCallShadowExecutor)
    port = InProcessThorExecutionPort(
        pr_native=pr_native,
        direct_api=direct_api,
        tool_call=tool_call,
    )
    readiness = MutationDependencyReadiness(
        saga_audit_durable=True,
        vidar_recovery_contracts=frozenset({"state_forward_only"}),
    )

    loop = _build_control_loop(
        default_container(app_config),
        http_client=None,
        thor_execution_port=port,
        mutation_dependency_readiness=readiness,
    )
    coordinator = loop._hil_resume_coordinator

    assert coordinator is not None
    assert loop._thor_execution_port is coordinator._thor_execution_port is port
    assert (
        loop._mutation_dependency_readiness
        is coordinator._mutation_dependency_readiness
        is readiness
    )
    assert loop._executor is coordinator._executor is pr_native
    assert loop._direct_api_executor is coordinator._direct_api_executor is direct_api
    assert loop._tool_executor is coordinator._tool_executor is tool_call

"""Production composition tests for shared safeguard lifecycle dependencies."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fdai.runtime.delivery import _build_direct_api_executor, _build_tool_executor
from fdai.runtime.isolated_executor_client import (
    EventBusDirectApiExecutionClient,
    RemoteDirectApiExecutionOutcome,
    RemoteDirectApiExecutionResult,
)
from fdai.runtime.providers import (
    _build_resource_lock,
    _build_safeguard_lifecycle_coordinator,
)
from fdai.runtime.safeguard_isolated_executor import (
    SafeguardBoundEventBusDirectApiExecutionClient,
)
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.core.executor.test_direct_api_executor import _action as _direct_action
from tests.core.executor.test_safeguard_lifecycle_coordinator import (
    _coordinator as _test_coordinator,
)
from tests.core.executor.test_tool_call_executor import _action as _tool_action

_REVISION = "a" * 40


def test_production_safeguard_composition_requires_source_revision() -> None:
    environment = {
        "RUNTIME_ENV": "production",
        "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
    }
    lock = _build_resource_lock(environment)

    with pytest.raises(RuntimeError, match="FDAI_SOURCE_REVISION"):
        _build_safeguard_lifecycle_coordinator(
            audit_store=InMemoryStateStore(),
            resource_lock=lock,
            process_store=InMemoryProcessRuntimeStore(),
            environment=environment,
        )


def test_production_safeguard_composition_binds_only_durable_stores() -> None:
    environment = {
        "RUNTIME_ENV": "production",
        "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
        "FDAI_SOURCE_REVISION": _REVISION,
    }
    lock = _build_resource_lock(environment)

    coordinator = _build_safeguard_lifecycle_coordinator(
        audit_store=InMemoryStateStore(),
        resource_lock=lock,
        process_store=InMemoryProcessRuntimeStore(),
        environment=environment,
    )

    assert coordinator.production_ready is True
    assert coordinator.source_revision == f"commit:{_REVISION}"


def test_local_shadow_composition_uses_explicit_test_providers() -> None:
    environment = {"RUNTIME_ENV": "test"}
    lock = _build_resource_lock(environment)

    coordinator = _build_safeguard_lifecycle_coordinator(
        audit_store=InMemoryStateStore(),
        resource_lock=lock,
        process_store=InMemoryProcessRuntimeStore(),
        environment=environment,
    )

    assert coordinator.production_ready is False
    assert coordinator.source_revision == "commit:" + "0" * 40


async def test_runtime_direct_and_tool_constructors_bind_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_DIRECT_API_FAKE", "1")
    monkeypatch.setenv("FDAI_TOOL_CALL_FAKE", "1")
    audit = InMemoryStateStore()
    process = InMemoryProcessRuntimeStore()
    lock = _build_resource_lock({"RUNTIME_ENV": "test"})
    coordinator = _build_safeguard_lifecycle_coordinator(
        audit_store=audit,
        resource_lock=lock,
        process_store=process,
        environment={"RUNTIME_ENV": "test"},
    )
    direct = _build_direct_api_executor(
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )
    tool = _build_tool_executor(
        audit_store=audit,
        resource_lock=lock,
        safeguard_coordinator=coordinator,
    )

    assert direct is not None
    assert tool is not None
    direct_result = await direct.execute(action=_direct_action())
    tool_result = await tool.execute(action=_tool_action(idempotency_key="tool-idem"))
    assert direct_result.safeguard_bundle_digest is not None
    assert tool_result.safeguard_bundle_digest is not None


async def test_isolated_client_wrapper_sends_finalized_bundle() -> None:
    class _Client:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def execute_bound(self, **kwargs: Any) -> RemoteDirectApiExecutionResult:
            self.calls.append(dict(kwargs))
            return RemoteDirectApiExecutionResult(
                action_id=str(kwargs["action"].action_id),
                outcome=RemoteDirectApiExecutionOutcome.DISPATCHED,
                receipt_ref="provider:1",
                audit_context={"executor_receipt_ref": "receipt:1"},
            )

    audit = InMemoryStateStore()
    coordinator, _lock = _test_coordinator(audit)
    client = _Client()
    wrapper = SafeguardBoundEventBusDirectApiExecutionClient(
        client=cast(EventBusDirectApiExecutionClient, client),
        coordinator=coordinator,
    )

    result = await wrapper.execute(action=_direct_action())

    assert result.outcome is RemoteDirectApiExecutionOutcome.DISPATCHED
    assert result.safeguard_bundle_digest is not None
    assert client.calls[0]["safeguard_bundle_digest"] == result.safeguard_bundle_digest
    assert client.calls[0]["source_revision"] == coordinator.source_revision

"""Production composition tests for shared safeguard lifecycle dependencies."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, cast

import pytest
from fdai.core.executor.safeguards import SafeguardReceipt, evaluate_pre_dispatch
from fdai.runtime.delivery import _build_direct_api_executor, _build_tool_executor
from fdai.runtime.isolated_executor_client import (
    EventBusDirectApiExecutionClient,
    RemoteDirectApiExecutionOutcome,
)
from fdai.runtime.providers import (
    _build_resource_lock,
    _build_safeguard_lifecycle_coordinator,
)
from fdai.runtime.safeguard_isolated_executor import (
    SafeguardBoundEventBusDirectApiExecutionClient,
    _RemoteDirectApiLifecycleDispatchPort,
)
from fdai.shared.contracts.models import ExecutionPath, SafeguardBoundExecutorCommand
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.executor_models import safeguard_bound_executor_command_id
from tests.core.executor.test_direct_api_executor import _action as _direct_action
from tests.core.executor.test_safeguard_lifecycle_coordinator import (
    _NOW,
)
from tests.core.executor.test_safeguard_lifecycle_coordinator import (
    _coordinator as _test_coordinator,
)
from tests.core.executor.test_tool_call_executor import _action as _tool_action

_REVISION = "a" * 40


def _published_command(kwargs: dict[str, Any], *, bundle_digest: str | None = None):
    action = kwargs["action"]
    digest = bundle_digest or kwargs["safeguard_bundle_digest"]
    return SafeguardBoundExecutorCommand.from_action(
        command_id=safeguard_bound_executor_command_id(
            action_payload=action.model_dump(mode="json", exclude_none=True),
            idempotency_key=action.idempotency_key,
            execution_path=ExecutionPath.DIRECT_API.value,
            safeguard_bundle_digest=digest,
            source_revision=kwargs["source_revision"],
            attempt=kwargs["attempt"],
            issued_at=_NOW,
            deadline_at=_NOW + timedelta(minutes=1),
        ),
        action=action,
        execution_path=ExecutionPath.DIRECT_API,
        attempt=kwargs["attempt"],
        issued_at=_NOW,
        deadline_at=_NOW + timedelta(minutes=1),
        safeguard_proof_bundle_digest=digest,
        source_revision=kwargs["source_revision"],
    )


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

        async def publish_bound(self, **kwargs: Any) -> SafeguardBoundExecutorCommand:
            await kwargs["pre_publish_guard"]()
            self.calls.append(dict(kwargs))
            return _published_command(kwargs)

    audit = InMemoryStateStore()
    coordinator, _lock = _test_coordinator(audit)
    client = _Client()
    wrapper = SafeguardBoundEventBusDirectApiExecutionClient(
        client=cast(EventBusDirectApiExecutionClient, client),
        coordinator=coordinator,
    )

    result = await wrapper.execute(action=_direct_action())

    assert result.outcome is RemoteDirectApiExecutionOutcome.FAILED
    assert result.reason == "dispatch continuity is quarantined"
    assert result.safeguard_bundle_digest is not None
    assert client.calls[0]["safeguard_bundle_digest"] == result.safeguard_bundle_digest
    assert client.calls[0]["source_revision"] == coordinator.source_revision


async def test_isolated_port_uses_the_persisted_reservation_attempt() -> None:
    class _Client:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def publish_bound(self, **kwargs: Any) -> SafeguardBoundExecutorCommand:
            await kwargs["pre_publish_guard"]()
            self.calls.append(dict(kwargs))
            return _published_command(kwargs)

    action = _direct_action()
    coordinator, _lock = _test_coordinator(InMemoryStateStore())
    client = _Client()
    port = _RemoteDirectApiLifecycleDispatchPort(
        client=cast(EventBusDirectApiExecutionClient, client),
        action=action,
        source_revision="commit:" + _REVISION,
    )
    safeguards = evaluate_pre_dispatch(
        action,
        execution_path=ExecutionPath.DIRECT_API,
        plan_digest="sha256:" + "b" * 64,
        plan_kind="isolated_executor_command",
    )
    assert isinstance(safeguards, SafeguardReceipt)

    await coordinator.dispatch(
        action=action,
        safeguard_receipt=safeguards,
        dispatch_port=port,
        correlation_id=str(action.event_id),
        attempt=4,
    )

    assert client.calls[0]["attempt"] == 4
    assert client.calls[0]["correlation_context"].reservation_attempt == 4
    assert port.command is not None
    assert port.command.attempt == 4


async def test_isolated_client_wrapper_quarantines_a_substituted_bundle() -> None:
    class _Client:
        async def publish_bound(self, **kwargs: Any) -> SafeguardBoundExecutorCommand:
            await kwargs["pre_publish_guard"]()
            return _published_command(kwargs, bundle_digest="sha256:" + "f" * 64)

    audit = InMemoryStateStore()
    coordinator, _lock = _test_coordinator(audit)
    wrapper = SafeguardBoundEventBusDirectApiExecutionClient(
        client=cast(EventBusDirectApiExecutionClient, _Client()),
        coordinator=coordinator,
    )

    result = await wrapper.execute(action=_direct_action())

    assert result.outcome is RemoteDirectApiExecutionOutcome.FAILED
    assert result.reason == "isolated Executor client error: RuntimeError"
    assert result.safeguard_bundle_digest is not None


async def test_isolated_client_no_publish_result_is_not_reported_as_dispatched() -> None:
    class _Client:
        def __init__(self) -> None:
            self.available = False
            self.calls = 0

        async def publish_bound(self, **kwargs: Any) -> SafeguardBoundExecutorCommand:
            if not self.available:
                return _published_command(kwargs)
            await kwargs["pre_publish_guard"]()
            self.calls += 1
            return _published_command(kwargs)

    current_time = [_NOW]
    audit = InMemoryStateStore()
    coordinator, _lock = _test_coordinator(audit, clock=lambda: current_time[0])
    client = _Client()
    wrapper = SafeguardBoundEventBusDirectApiExecutionClient(
        client=cast(EventBusDirectApiExecutionClient, client),
        coordinator=coordinator,
    )

    result = await wrapper.execute(action=_direct_action())
    replay = await wrapper.execute(action=_direct_action())
    client.available = True
    current_time[0] += timedelta(seconds=1)
    next_action = await wrapper.execute(
        action=_direct_action(
            action_id="00000000-0000-0000-0000-000000000099",
            idempotency_key="next-target-generation",
        )
    )

    assert result.outcome is RemoteDirectApiExecutionOutcome.REJECTED_INVARIANT
    assert result.reason == "dispatch blocked before provider invocation"
    assert result.safeguard_bundle_digest is not None
    assert replay.outcome is RemoteDirectApiExecutionOutcome.REJECTED_INVARIANT
    assert "without a committed effect" in (replay.reason or "")
    assert next_action.outcome is RemoteDirectApiExecutionOutcome.FAILED
    assert client.calls == 1


async def test_isolated_non_applied_replay_is_not_reported_as_applied() -> None:
    class _Client:
        def __init__(self) -> None:
            self.calls = 0

        async def publish_bound(self, **kwargs: Any) -> SafeguardBoundExecutorCommand:
            await kwargs["pre_publish_guard"]()
            self.calls += 1
            return _published_command(kwargs)

    audit = InMemoryStateStore()
    coordinator, _lock = _test_coordinator(audit)
    client = _Client()
    wrapper = SafeguardBoundEventBusDirectApiExecutionClient(
        client=cast(EventBusDirectApiExecutionClient, client),
        coordinator=coordinator,
    )

    first = await wrapper.execute(action=_direct_action())
    replay = await wrapper.execute(action=_direct_action())

    assert first.outcome is RemoteDirectApiExecutionOutcome.FAILED
    assert replay.outcome is RemoteDirectApiExecutionOutcome.FAILED
    assert replay.reason == "prior dispatch outcome remains quarantined"
    assert client.calls == 1


async def test_isolated_client_error_is_sanitized_after_guarded_invocation() -> None:
    class _Client:
        async def publish_bound(self, **kwargs: Any) -> SafeguardBoundExecutorCommand:
            await kwargs["pre_publish_guard"]()
            raise RuntimeError("secret-bearing-transport-detail")

    audit = InMemoryStateStore()
    coordinator, _lock = _test_coordinator(audit)
    wrapper = SafeguardBoundEventBusDirectApiExecutionClient(
        client=cast(EventBusDirectApiExecutionClient, _Client()),
        coordinator=coordinator,
    )

    result = await wrapper.execute(action=_direct_action())

    assert result.outcome is RemoteDirectApiExecutionOutcome.FAILED
    assert result.reason == "isolated Executor client error: RuntimeError"
    assert "secret-bearing-transport-detail" not in result.reason


async def test_isolated_client_cancellation_closes_then_propagates() -> None:
    class _Client:
        async def publish_bound(self, **kwargs: Any) -> SafeguardBoundExecutorCommand:
            await kwargs["pre_publish_guard"]()
            raise asyncio.CancelledError

    audit = InMemoryStateStore()
    coordinator, _lock = _test_coordinator(audit)
    wrapper = SafeguardBoundEventBusDirectApiExecutionClient(
        client=cast(EventBusDirectApiExecutionClient, _Client()),
        coordinator=coordinator,
    )

    with pytest.raises(asyncio.CancelledError):
        await wrapper.execute(action=_direct_action())


async def test_isolated_pre_publish_cancellation_closes_then_propagates() -> None:
    class _Client:
        async def publish_bound(self, **kwargs: Any) -> SafeguardBoundExecutorCommand:
            del kwargs
            raise asyncio.CancelledError

    audit = InMemoryStateStore()
    coordinator, _lock = _test_coordinator(audit)
    wrapper = SafeguardBoundEventBusDirectApiExecutionClient(
        client=cast(EventBusDirectApiExecutionClient, _Client()),
        coordinator=coordinator,
    )

    with pytest.raises(asyncio.CancelledError):
        await wrapper.execute(action=_direct_action())

"""Focused production-binding checks for background read investigations."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fdai.runtime.providers import _build_read_investigation_provider
from fdai.runtime.read_investigation_runtime import (
    build_read_investigation_runtime_binding,
)


def test_binding_is_absent_without_explicit_transport() -> None:
    assert (
        build_read_investigation_runtime_binding(
            environment={},
            provider=None,
            state_store=Mock(),
            saga_audit_chain=Mock(),
        )
        is None
    )


@pytest.mark.parametrize(
    ("environment", "provider", "message"),
    [
        (
            {"FDAI_READ_INVESTIGATION_REQUEST_TOPIC": "operator.other.requests"},
            Mock(),
            "canonical topic",
        ),
        (
            {"FDAI_READ_INVESTIGATION_REQUEST_TOPIC": ("operator.read-investigation.requests")},
            Mock(),
            "FDAI_STATE_STORE_DSN",
        ),
        (
            {
                "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": ("operator.read-investigation.requests"),
                "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
            },
            None,
            "production read provider",
        ),
    ],
)
def test_binding_fails_closed_on_partial_configuration(
    environment: dict[str, str],
    provider: object | None,
    message: str,
) -> None:
    with pytest.raises(RuntimeError, match=message):
        build_read_investigation_runtime_binding(
            environment=environment,
            provider=provider,  # type: ignore[arg-type]
            state_store=Mock(),
            saga_audit_chain=Mock(),
        )


def test_complete_binding_constructs_detached_and_interactive_coordinators() -> None:
    binding = build_read_investigation_runtime_binding(
        environment={
            "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": ("operator.read-investigation.requests"),
            "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
            "HOSTNAME": "core-one",
        },
        provider=Mock(transport="promoted_inventory"),
        state_store=Mock(),
        saga_audit_chain=Mock(),
    )

    assert binding is not None
    assert binding.consumer.request_topic == "operator.read-investigation.requests"
    assert binding.consumer.group_id == "core-read-investigation-v1"
    assert type(binding.completion_sink).__name__ == "EventBusReadInvestigationCompletionSink"
    assert binding.consumer.interactive is binding.interactive
    assert type(binding.interactive_run_store).__name__ == "PostgresReadInvestigationRunStore"
    assert (
        type(binding.interactive_progress_store).__name__
        == "PostgresReadInvestigationProgressStore"
    )
    assert (
        type(binding.interactive_completion_store).__name__
        == "PostgresReadInvestigationCompletionStore"
    )
    assert type(binding.background_task_projection_publisher).__name__ == (
        "BackgroundTaskProjectionPublisher"
    )
    assert type(binding.interactive_completion_publisher).__name__ == (
        "InteractiveReadInvestigationCompletionPublisher"
    )


async def test_production_control_forwards_cancellation_to_coordinator() -> None:
    binding = build_read_investigation_runtime_binding(
        environment={
            "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": ("operator.read-investigation.requests"),
            "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
        },
        provider=Mock(transport="promoted_inventory"),
        state_store=Mock(),
        saga_audit_chain=Mock(),
    )
    assert binding is not None
    cancel = AsyncMock()
    object.__setattr__(binding.wake_signal, "_coordinator", SimpleNamespace(cancel=cancel))

    await binding.consumer.coordinator.cancel(
        "background-one",
        actor="principal-one",
        is_admin=False,
    )

    cancel.assert_awaited_once_with(
        "background-one",
        actor="principal-one",
        is_admin=False,
    )


async def test_schema_failure_does_not_bind_completion_transport() -> None:
    binding = build_read_investigation_runtime_binding(
        environment={
            "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": "operator.read-investigation.requests",
            "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
        },
        provider=Mock(transport="promoted_inventory"),
        state_store=Mock(),
        saga_audit_chain=Mock(),
    )
    assert binding is not None
    object.__setattr__(binding.interactive_run_store, "verify_schema", AsyncMock())
    object.__setattr__(
        binding.interactive_progress_store,
        "verify_schema",
        AsyncMock(side_effect=RuntimeError("schema unavailable")),
    )
    object.__setattr__(binding.interactive_completion_store, "verify_schema", AsyncMock())

    with pytest.raises(RuntimeError, match="schema unavailable"):
        await binding.run(bus=Mock(), stop=asyncio.Event())

    assert binding.completion_sink._bus is None


async def test_completion_wake_during_scan_triggers_immediate_rescan() -> None:
    binding = build_read_investigation_runtime_binding(
        environment={
            "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": "operator.read-investigation.requests",
            "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
        },
        provider=Mock(transport="promoted_inventory"),
        state_store=Mock(),
        saga_audit_chain=Mock(),
    )
    assert binding is not None
    stop = asyncio.Event()
    scans = 0

    async def run_once(*, bus: object) -> int:
        nonlocal scans
        del bus
        scans += 1
        if scans == 1:
            binding.interactive_completion_wake.event.set()
        else:
            stop.set()
        return 0

    object.__setattr__(binding.interactive_completion_publisher, "run_once", run_once)

    await asyncio.wait_for(
        binding._run_interactive_completions(Mock(), stop),
        timeout=1.0,
    )

    assert scans == 2


async def test_runtime_refreshes_optional_mcp_discovery_until_stopped() -> None:
    provider = Mock(transport="azure_mcp_optional")
    provider.discover = AsyncMock(return_value=False)
    binding = build_read_investigation_runtime_binding(
        environment={
            "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": ("operator.read-investigation.requests"),
            "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
        },
        provider=provider,
        state_store=Mock(),
        saga_audit_chain=Mock(),
    )
    assert binding is not None
    stop = asyncio.Event()

    async def refresh_once() -> bool:
        stop.set()
        return False

    object.__setattr__(binding, "discovery_refresh", refresh_once)
    await binding._run_discovery_monitor(stop)

    assert stop.is_set()


def test_provider_composition_keeps_mcp_explicit_and_optional() -> None:
    common = {
        "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
        "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000",
    }

    rest_provider = _build_read_investigation_provider(
        identity=Mock(),
        http_client=Mock(),
        environment=common,
    )
    mcp_provider = _build_read_investigation_provider(
        identity=Mock(),
        http_client=Mock(),
        environment={**common, "FDAI_AZURE_MCP_ENABLED": "true"},
    )

    assert type(rest_provider).__name__ == "AzureActivityReadInvestigationProvider"
    assert type(mcp_provider).__name__ == "AzureMcpReadInvestigationProvider"

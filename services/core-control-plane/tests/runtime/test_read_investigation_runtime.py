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


def test_complete_binding_constructs_detached_consumer_and_coordinator() -> None:
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
    assert not hasattr(binding, "execution_policy")
    assert not hasattr(binding, "run_store")


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

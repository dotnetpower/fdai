from __future__ import annotations

from collections.abc import Sequence

import pytest

from fdai.delivery.azure.read_investigation import (
    AzureMcpReadTransport,
    AzureRow,
    build_azure_mcp_read_wiring,
)
from fdai.delivery.azure.read_investigation import mcp_wiring as mcp_wiring_module
from fdai.shared.providers.read_investigation import ReadToolLimits, ResourceSelector


class _Fallback:
    transport_id = "rest"

    async def resolve_resources(
        self, selector: ResourceSelector, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        del selector, limits
        return []

    async def get_resource_state(
        self, provider_ref: str, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        del provider_ref, limits
        return []

    async def query_resource_activity(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        del provider_ref, lookback_seconds, limits
        return []

    async def query_resource_health(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        del provider_ref, lookback_seconds, limits
        return []

    async def query_guest_shutdown_events(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        del provider_ref, lookback_seconds, limits
        return []

    async def query_network_security(
        self, provider_ref: str, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        del provider_ref, limits
        return []

    async def query_network_peerings(
        self, provider_ref: str, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        del provider_ref, limits
        return []


def test_disabled_wiring_preserves_existing_transport() -> None:
    fallback = _Fallback()

    wiring = build_azure_mcp_read_wiring(
        fallback=fallback,
        environment={"FDAI_AZURE_MCP_ENABLED": "false"},
        reader_client_id="reader",
        subscription_id="subscription",
    )

    assert wiring.transport is fallback
    assert wiring.client is None


def test_missing_optional_sdk_preserves_default_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback = _Fallback()

    def missing_sdk(**_kwargs: object) -> None:
        raise ModuleNotFoundError("No module named 'mcp'", name="mcp")

    monkeypatch.setattr(mcp_wiring_module.PythonSdkMcpSession, "stdio", missing_sdk)

    wiring = build_azure_mcp_read_wiring(
        fallback=fallback,
        environment={},
        reader_client_id="reader",
        subscription_id="subscription",
    )

    assert wiring.transport is fallback
    assert wiring.client is None


def test_missing_optional_sdk_rejects_explicit_enable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_sdk(**_kwargs: object) -> None:
        raise ModuleNotFoundError("No module named 'mcp'", name="mcp")

    monkeypatch.setattr(mcp_wiring_module.PythonSdkMcpSession, "stdio", missing_sdk)

    with pytest.raises(RuntimeError, match="azure-mcp"):
        build_azure_mcp_read_wiring(
            fallback=_Fallback(),
            environment={"FDAI_AZURE_MCP_ENABLED": "true"},
            reader_client_id="reader",
            subscription_id="subscription",
        )


def test_enabled_wiring_uses_mcp_transport_without_secrets_in_child_env() -> None:
    wiring = build_azure_mcp_read_wiring(
        fallback=_Fallback(),
        environment={
            "PATH": "/bin",
            "IDENTITY_ENDPOINT": "http://identity",
            "IDENTITY_HEADER": "header",
            "DOTNET_BUNDLE_EXTRACT_BASE_DIR": "/writable/dotnet",
            "FDAI_DATABASE_URL": "must-not-propagate",
        },
        reader_client_id="reader",
        subscription_id="subscription",
    )

    assert isinstance(wiring.transport, AzureMcpReadTransport)
    assert wiring.client is not None
    session = wiring.client._session  # noqa: SLF001 - verify child trust boundary
    parameters = session._server_parameters  # noqa: SLF001 - immutable SDK configuration
    assert parameters.env is not None
    assert parameters.env["DOTNET_BUNDLE_EXTRACT_BASE_DIR"] == "/writable/dotnet"


def test_local_cli_wiring_does_not_set_fake_managed_identity_client_id() -> None:
    wiring = build_azure_mcp_read_wiring(
        fallback=_Fallback(),
        environment={"PATH": "/bin", "AZURE_CONFIG_DIR": "/profiles/azure"},
        reader_client_id="azure-cli",
        subscription_id="subscription",
    )

    assert wiring.client is not None
    session = wiring.client._session  # noqa: SLF001 - verify child trust boundary
    parameters = session._server_parameters  # noqa: SLF001 - immutable SDK configuration
    assert parameters.env is not None
    assert "AZURE_CLIENT_ID" not in parameters.env
    assert parameters.env["AZURE_CONFIG_DIR"] == "/profiles/azure"


async def test_missing_mcp_executable_degrades_without_blocking_startup() -> None:
    wiring = build_azure_mcp_read_wiring(
        fallback=_Fallback(),
        environment={
            "PATH": "/bin",
            "FDAI_AZURE_MCP_COMMAND": "missing-azmcp",
            "FDAI_AZURE_MCP_STARTUP_TIMEOUT_SECONDS": "0.1",
        },
        reader_client_id="reader",
        subscription_id="subscription",
    )

    await wiring.start()
    try:
        assert wiring.client is not None
        assert wiring.client.is_routable is False
        assert wiring.client.reason == "probe_failed"
    finally:
        await wiring.close()


@pytest.mark.parametrize("value", ("maybe", "2", "enabled"))
def test_enabled_flag_rejects_unknown_tokens(value: str) -> None:
    with pytest.raises(ValueError, match="boolean token"):
        build_azure_mcp_read_wiring(
            fallback=_Fallback(),
            environment={"FDAI_AZURE_MCP_ENABLED": value},
            reader_client_id="reader",
            subscription_id="subscription",
        )


def test_command_rejects_paths() -> None:
    with pytest.raises(ValueError, match="executable name"):
        build_azure_mcp_read_wiring(
            fallback=_Fallback(),
            environment={"FDAI_AZURE_MCP_COMMAND": "tools/azmcp"},
            reader_client_id="reader",
            subscription_id="subscription",
        )

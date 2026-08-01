"""Configuration-driven Azure MCP read transport composition."""

from __future__ import annotations

import logging
import math
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from fdai.delivery.azure.read_investigation.mcp_transport import (
    AZURE_MCP_READ_TOOLS,
    AzureMcpReadTransport,
)
from fdai.delivery.azure.read_investigation.transport import AzureReadTransport
from fdai.delivery.mcp import ManagedMcpClient, ManagedMcpClientConfig, PythonSdkMcpSession

_LOGGER = logging.getLogger(__name__)

_CHILD_ENV_ALLOWLIST = frozenset(
    {
        "AZURE_CONFIG_DIR",
        "AZURE_CLOUD",
        "AZURE_TENANT_ID",
        "DOTNET_BUNDLE_EXTRACT_BASE_DIR",
        "HOME",
        "IDENTITY_ENDPOINT",
        "IDENTITY_HEADER",
        "MSI_ENDPOINT",
        "MSI_SECRET",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "XDG_CACHE_HOME",
    }
)


@dataclass(frozen=True, slots=True)
class AzureMcpReadWiring:
    transport: AzureReadTransport
    client: ManagedMcpClient | None = None

    async def start(self) -> None:
        if self.client is not None:
            await self.client.start()

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()


def build_azure_mcp_read_wiring(
    *,
    fallback: AzureReadTransport,
    environment: Mapping[str, str],
    reader_client_id: str,
    subscription_id: str,
) -> AzureMcpReadWiring:
    raw_enabled = environment.get("FDAI_AZURE_MCP_ENABLED")
    if not _enabled(raw_enabled, default=True):
        _LOGGER.info("azure_mcp_disabled")
        return AzureMcpReadWiring(transport=fallback)
    explicitly_enabled = bool(raw_enabled and raw_enabled.strip())
    command = environment.get("FDAI_AZURE_MCP_COMMAND", "azmcp").strip()
    if not command or "/" in command or "\\" in command:
        raise ValueError("FDAI_AZURE_MCP_COMMAND MUST be one executable name")
    child_environment = {
        key: value for key, value in environment.items() if key in _CHILD_ENV_ALLOWLIST and value
    }
    child_environment.update(
        {
            "AZURE_SUBSCRIPTION_ID": subscription_id,
            "AZURE_MCP_COLLECT_TELEMETRY": _boolean_token(
                environment.get("AZURE_MCP_COLLECT_TELEMETRY"),
                name="AZURE_MCP_COLLECT_TELEMETRY",
                default=False,
            ),
        }
    )
    if reader_client_id != "azure-cli":
        child_environment["AZURE_CLIENT_ID"] = reader_client_id
    startup_timeout = _float(environment, "FDAI_AZURE_MCP_STARTUP_TIMEOUT_SECONDS", 2.0)
    call_timeout = _float(environment, "FDAI_AZURE_MCP_CALL_TIMEOUT_SECONDS", 10.0)
    resolved_command = _resolve_command(command, path=child_environment.get("PATH"))
    if resolved_command is None:
        if explicitly_enabled:
            raise RuntimeError(f"FDAI_AZURE_MCP_ENABLED=true requires executable {command!r}")
        _LOGGER.warning("azure_mcp_executable_unavailable")
        return AzureMcpReadWiring(transport=fallback)
    try:
        session = PythonSdkMcpSession.stdio(
            command=resolved_command,
            args=("server", "start"),
            environment=child_environment,
            read_timeout_seconds=call_timeout,
            close_timeout_seconds=min(startup_timeout, 2.0),
        )
    except ModuleNotFoundError as exc:
        if exc.name != "mcp" and not str(exc.name).startswith("mcp."):
            raise
        if explicitly_enabled:
            raise RuntimeError(
                "FDAI_AZURE_MCP_ENABLED=true requires the 'azure-mcp' optional dependency"
            ) from exc
        _LOGGER.warning("azure_mcp_sdk_unavailable")
        return AzureMcpReadWiring(transport=fallback)
    client = ManagedMcpClient(
        session=session,
        config=ManagedMcpClientConfig(
            allowed_tools=AZURE_MCP_READ_TOOLS,
            startup_timeout_seconds=startup_timeout,
            call_timeout_seconds=call_timeout,
            health_interval_seconds=_float(
                environment, "FDAI_AZURE_MCP_HEALTH_INTERVAL_SECONDS", 60.0
            ),
            failure_threshold=1,
            reset_timeout_seconds=_float(environment, "FDAI_AZURE_MCP_RESET_TIMEOUT_SECONDS", 30.0),
        ),
    )
    return AzureMcpReadWiring(
        transport=AzureMcpReadTransport(client=client, fallback=fallback),
        client=client,
    )


def _enabled(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("FDAI_AZURE_MCP_ENABLED MUST be a boolean token")


def _float(environment: Mapping[str, str], name: str, default: float) -> float:
    raw = environment.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} MUST be a number") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} MUST be finite")
    return value


def _boolean_token(value: str | None, *, name: str, default: bool) -> str:
    if value is None or not value.strip():
        return str(default).lower()
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return "true"
    if normalized in {"0", "false", "no", "off"}:
        return "false"
    raise ValueError(f"{name} MUST be a boolean token")


def _resolve_command(command: str, *, path: str | None) -> str | None:
    resolved = shutil.which(command, path=path)
    if resolved is not None:
        return resolved
    sibling = Path(sys.executable).with_name(command)
    return str(sibling) if sibling.is_file() else None


__all__ = ["AzureMcpReadWiring", "build_azure_mcp_read_wiring"]

"""Optional read-only Azure MCP transport with typed provider fallback."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.shared.providers.read_investigation import (
    EvidenceFreshness,
    EvidenceStatus,
    ReadEvidenceAttempt,
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ReadInvestigationProvider,
    ReadToolId,
    ReadToolLimits,
    ResolvedResource,
    ResourceResolutionAttempt,
    ResourceSelector,
)
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallReceipt
from fdai.shared.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
)


class AzureMcpSession(Protocol):
    """Expose only the MCP operations the optional transport needs."""

    async def list_tools(self) -> object: ...

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
    ) -> object: ...


class AzureMcpSessionFactory(Protocol):
    """Create one bounded session without exposing credentials to Core."""

    def __call__(self) -> AbstractAsyncContextManager[AzureMcpSession]: ...


@dataclass(frozen=True, slots=True)
class AzureMcpClientConfig:
    """Bound discovery, call, output, and process namespace limits."""

    startup_timeout_seconds: float = 10.0
    call_timeout_seconds: float = 30.0
    max_output_bytes: int = 256_000
    namespaces: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.1 <= self.startup_timeout_seconds <= 10.0:
            raise ValueError("Azure MCP startup timeout MUST be in [0.1, 10]")
        if not 0.1 <= self.call_timeout_seconds <= 120.0:
            raise ValueError("Azure MCP call timeout MUST be in [0.1, 120]")
        if not 1_024 <= self.max_output_bytes <= 1_000_000:
            raise ValueError("Azure MCP output bound MUST be in [1024, 1000000]")
        if len(self.namespaces) > 16 or any(
            not value.strip() or len(value) > 64 for value in self.namespaces
        ):
            raise ValueError("Azure MCP namespaces MUST contain <= 16 bounded values")


class StdioAzureMcpSessionFactory:
    """Create MCP v2 sessions over the pinned Azure MCP stdio executable."""

    def __init__(
        self,
        *,
        config: AzureMcpClientConfig,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._config = config
        self._environment = dict(environment or {})

    def __call__(self) -> AbstractAsyncContextManager[AzureMcpSession]:
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters, stdio_client
        from msmcp_azure import get_executable_path  # type: ignore[import-untyped]

        args = ["server", "start", "--mode", "all", "--read-only"]
        for namespace in self._config.namespaces:
            args.extend(("--namespace", namespace))
        parameters = StdioServerParameters(
            command=str(get_executable_path()),
            args=args,
            env=self._environment or None,
        )
        return Client(
            stdio_client(parameters),
            read_timeout_seconds=self._config.call_timeout_seconds,
        )


class AzureMcpClient:
    """Perform bounded discovery and structured calls over injected MCP sessions."""

    def __init__(
        self,
        *,
        sessions: AzureMcpSessionFactory,
        config: AzureMcpClientConfig | None = None,
    ) -> None:
        self._sessions = sessions
        self._config = config or AzureMcpClientConfig()

    async def discover(self, required_tools: frozenset[str]) -> frozenset[str]:
        """Return the allowlisted names found by the bounded list call."""

        async with asyncio.timeout(self._config.startup_timeout_seconds):
            async with self._sessions() as session:
                result = await session.list_tools()
        tools = getattr(result, "tools", None)
        if not isinstance(tools, Sequence):
            raise RuntimeError("Azure MCP tools/list returned a malformed result")
        discovered = frozenset(
            name
            for tool in tools
            if isinstance((name := getattr(tool, "name", None)), str) and name.strip()
        )
        return required_tools.intersection(discovered)

    async def call(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        timeout_seconds: float | None = None,
        max_output_bytes: int | None = None,
    ) -> Mapping[str, Any]:
        """Return one bounded structured result and reject untyped MCP content."""

        timeout = min(
            self._config.call_timeout_seconds,
            timeout_seconds if timeout_seconds is not None else self._config.call_timeout_seconds,
        )
        output_bound = min(
            self._config.max_output_bytes,
            max_output_bytes if max_output_bytes is not None else self._config.max_output_bytes,
        )
        async with asyncio.timeout(timeout):
            async with self._sessions() as session:
                result = await session.call_tool(
                    tool_name,
                    dict(arguments),
                    read_timeout_seconds=timeout,
                )
        if getattr(result, "is_error", True) is not False:
            raise RuntimeError("Azure MCP tool returned an error")
        structured = getattr(result, "structured_content", None)
        if not isinstance(structured, Mapping):
            raise RuntimeError("Azure MCP tool returned no structured object")
        encoded = json.dumps(
            structured,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if len(encoded) > output_bound:
            raise RuntimeError("Azure MCP structured output exceeded the byte bound")
        return dict(structured)


McpArgumentsBuilder = Callable[[ResolvedResource, int | None, ReadToolLimits], Mapping[str, object]]
McpEvidenceNormalizer = Callable[
    [Mapping[str, Any], ResolvedResource, ReadToolLimits], ReadEvidenceAttempt
]


@dataclass(frozen=True, slots=True)
class AzureMcpReadBinding:
    """Bind one registered read tool to server-owned arguments and normalization."""

    tool_id: ReadToolId
    tool_name: str
    arguments: McpArgumentsBuilder
    normalize: McpEvidenceNormalizer

    def __post_init__(self) -> None:
        if self.tool_id is ReadToolId.RESOLVE_RESOURCE:
            raise ValueError("Azure MCP cannot replace exact resource resolution")
        if not self.tool_name.strip() or len(self.tool_name) > 256:
            raise ValueError("Azure MCP tool_name MUST be bounded")


class AzureMcpReadInvestigationProvider:
    """Prefer discovered MCP reads and fall back to the authoritative base provider."""

    transport = "azure_mcp_optional"

    def __init__(
        self,
        *,
        base: ReadInvestigationProvider,
        client: AzureMcpClient,
        bindings: Sequence[AzureMcpReadBinding],
        circuit: CircuitBreaker | None = None,
    ) -> None:
        by_tool = {binding.tool_id: binding for binding in bindings}
        if len(by_tool) != len(bindings):
            raise ValueError("Azure MCP read bindings MUST have unique tool ids")
        names = tuple(binding.tool_name for binding in bindings)
        if len(set(names)) != len(names):
            raise ValueError("Azure MCP read bindings MUST have unique tool names")
        self._base = base
        self._client = client
        self._bindings = by_tool
        self._available_tools: frozenset[str] = frozenset()
        self._circuit = circuit or CircuitBreaker(
            name="azure-mcp",
            config=CircuitBreakerConfig(failure_threshold=3, reset_timeout_s=30.0),
        )

    async def discover(self) -> bool:
        """Refresh availability without invoking an Azure operation."""

        required = frozenset(binding.tool_name for binding in self._bindings.values())
        if not required:
            self._available_tools = frozenset()
            return False
        try:
            self._available_tools = await self._circuit.call(
                self._client.discover,
                required,
            )
        except Exception:  # noqa: BLE001 - optional transport falls back without details
            self._available_tools = frozenset()
        return bool(self._available_tools)

    async def resolve_resource(
        self, selector: ResourceSelector, *, limits: ReadToolLimits
    ) -> ResourceResolutionAttempt:
        return await self._base.resolve_resource(selector, limits=limits)

    async def get_resource_state(
        self, resource: ResolvedResource, *, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt:
        return await self._read(
            ReadToolId.GET_RESOURCE_STATE,
            resource,
            lookback_seconds=None,
            limits=limits,
            fallback=lambda: self._base.get_resource_state(resource, limits=limits),
        )

    async def query_resource_activity(
        self,
        resource: ResolvedResource,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        return await self._read(
            ReadToolId.QUERY_RESOURCE_ACTIVITY,
            resource,
            lookback_seconds=lookback_seconds,
            limits=limits,
            fallback=lambda: self._base.query_resource_activity(
                resource,
                lookback_seconds=lookback_seconds,
                limits=limits,
            ),
        )

    async def query_resource_health(
        self,
        resource: ResolvedResource,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        return await self._read(
            ReadToolId.QUERY_RESOURCE_HEALTH,
            resource,
            lookback_seconds=lookback_seconds,
            limits=limits,
            fallback=lambda: self._base.query_resource_health(
                resource,
                lookback_seconds=lookback_seconds,
                limits=limits,
            ),
        )

    async def query_guest_shutdown_events(
        self,
        resource: ResolvedResource,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        return await self._read(
            ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS,
            resource,
            lookback_seconds=lookback_seconds,
            limits=limits,
            fallback=lambda: self._base.query_guest_shutdown_events(
                resource,
                lookback_seconds=lookback_seconds,
                limits=limits,
            ),
        )

    async def query_network_security(
        self, resource: ResolvedResource, *, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt:
        return await self._read(
            ReadToolId.QUERY_NETWORK_SECURITY,
            resource,
            lookback_seconds=None,
            limits=limits,
            fallback=lambda: self._base.query_network_security(resource, limits=limits),
        )

    async def query_network_peerings(
        self, resource: ResolvedResource, *, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt:
        return await self._read(
            ReadToolId.QUERY_NETWORK_PEERINGS,
            resource,
            lookback_seconds=None,
            limits=limits,
            fallback=lambda: self._base.query_network_peerings(resource, limits=limits),
        )

    async def _read(
        self,
        tool_id: ReadToolId,
        resource: ResolvedResource,
        *,
        lookback_seconds: int | None,
        limits: ReadToolLimits,
        fallback: Callable[[], Awaitable[ReadEvidenceAttempt]],
    ) -> ReadEvidenceAttempt:
        binding = self._bindings.get(tool_id)
        if binding is None or binding.tool_name not in self._available_tools:
            return await fallback()
        try:
            structured = await self._circuit.call(
                self._client.call,
                binding.tool_name,
                binding.arguments(resource, lookback_seconds, limits),
                timeout_seconds=limits.timeout_seconds,
                max_output_bytes=limits.max_output_bytes,
            )
            attempt = binding.normalize(structured, resource, limits)
            if attempt.tool_id is not tool_id:
                raise ValueError("Azure MCP normalizer returned the wrong tool id")
            if attempt.evidence.resource_ref != resource.resource_ref:
                raise ValueError("Azure MCP normalizer widened the resolved resource")
            return attempt
        except Exception:  # noqa: BLE001 - typed base transport remains authoritative fallback
            return await fallback()


def resource_health_binding() -> AzureMcpReadBinding:
    """Return the fixed Azure MCP binding for exact Resource Health reads."""

    return AzureMcpReadBinding(
        tool_id=ReadToolId.QUERY_RESOURCE_HEALTH,
        tool_name="resourcehealth_availability-status_get",
        arguments=_resource_health_arguments,
        normalize=_normalize_resource_health,
    )


def _resource_health_arguments(
    resource: ResolvedResource,
    lookback_seconds: int | None,
    limits: ReadToolLimits,
) -> Mapping[str, object]:
    del lookback_seconds
    resource_id = resource.resource_ref
    lowered = resource_id.casefold()
    if (
        not lowered.startswith("/subscriptions/")
        or "/resourcegroups/" not in lowered
        or "/providers/" not in lowered
        or any(char in resource_id for char in ("?", "#", "\r", "\n"))
    ):
        raise ValueError("Azure MCP Resource Health requires an exact ARM resource id")
    return {
        "auth-method": "Credential",
        "resourceId": resource_id,
        "retry-max-retries": 0,
        "retry-network-timeout": limits.timeout_seconds,
    }


def _normalize_resource_health(
    payload: Mapping[str, Any],
    resource: ResolvedResource,
    limits: ReadToolLimits,
) -> ReadEvidenceAttempt:
    del limits
    item = _single_resource_health_item(payload)
    properties = item.get("properties")
    values = properties if isinstance(properties, Mapping) else item
    raw_state = values.get("availabilityState")
    if not isinstance(raw_state, str):
        raw_state = values.get("availability_state")
    if not isinstance(raw_state, str):
        raise ValueError("Azure MCP Resource Health result has no availability state")
    state = raw_state.strip().casefold()
    if state not in {"available", "degraded", "unavailable", "unknown"}:
        raise ValueError("Azure MCP Resource Health returned an unknown state")
    returned_id = item.get("id")
    if returned_id is not None and (
        not isinstance(returned_id, str)
        or returned_id.casefold() != resource.resource_ref.casefold()
    ):
        raise ValueError("Azure MCP Resource Health widened the exact resource")
    observed_at = datetime.now(UTC)
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ReadEvidenceAttempt(
        tool_id=ReadToolId.QUERY_RESOURCE_HEALTH,
        evidence=ReadEvidenceEnvelope(
            status=EvidenceStatus.MATCHED,
            authority="azure.resource_health",
            resource_ref=resource.resource_ref,
            observed_at=observed_at,
            freshness=EvidenceFreshness.LIVE,
            truncated=False,
            records=(
                ReadEvidenceRecord(
                    occurred_at=observed_at,
                    status=state,
                    state=state,
                ),
            ),
            evidence_refs=(f"azure-mcp-resource-health:sha256:{digest}",),
        ),
        receipt=ToolCallReceipt(
            ToolCallOutcome.SUCCEEDED,
            f"azure-mcp-resource-health:{digest[:24]}",
            tool_id=ReadToolId.QUERY_RESOURCE_HEALTH.value,
            transport="azure_mcp",
            operation_class="resource_health",
            result_count=1,
            recorded_at=observed_at,
        ),
    )


def _single_resource_health_item(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    for name in ("availabilityStatus", "availability_status", "result", "resourceHealth"):
        candidate = payload.get(name)
        if isinstance(candidate, Mapping):
            return candidate
    values = payload.get("value")
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
        if len(values) != 1 or not isinstance(values[0], Mapping):
            raise ValueError("Azure MCP Resource Health result MUST contain one resource")
        return values[0]
    return payload


__all__ = [
    "AzureMcpClient",
    "AzureMcpClientConfig",
    "AzureMcpReadBinding",
    "AzureMcpReadInvestigationProvider",
    "AzureMcpSession",
    "AzureMcpSessionFactory",
    "StdioAzureMcpSessionFactory",
    "resource_health_binding",
]

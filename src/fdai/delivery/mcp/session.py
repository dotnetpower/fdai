"""Managed MCP sessions with bounded availability and failure isolation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from fdai.shared.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
)

if TYPE_CHECKING:
    from mcp.client.session_group import ServerParameters


class McpAvailability(StrEnum):
    UNKNOWN = "unknown"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class McpCallResult:
    structured_content: object | None
    content: tuple[object, ...] = ()
    is_error: bool = False


@runtime_checkable
class McpSession(Protocol):
    async def list_tools(self) -> frozenset[str]: ...

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        timeout_seconds: float,
    ) -> McpCallResult: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ManagedMcpClientConfig:
    allowed_tools: frozenset[str]
    startup_timeout_seconds: float = 3.0
    call_timeout_seconds: float = 15.0
    health_interval_seconds: float = 60.0
    failure_threshold: int = 2
    reset_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.allowed_tools or any(not name.strip() for name in self.allowed_tools):
            raise ValueError("managed MCP allowed_tools MUST contain bounded names")
        if not 0.1 <= self.startup_timeout_seconds <= 10:
            raise ValueError("managed MCP startup timeout MUST be in [0.1, 10]")
        if not 0.1 <= self.call_timeout_seconds <= 120:
            raise ValueError("managed MCP call timeout MUST be in [0.1, 120]")
        if not 5 <= self.health_interval_seconds <= 3_600:
            raise ValueError("managed MCP health interval MUST be in [5, 3600]")


class ManagedMcpUnavailableError(RuntimeError):
    """The optional MCP provider is not currently routable."""


class ManagedMcpClient:
    """Fail fast while unavailable and recover through bounded health probes."""

    def __init__(
        self,
        *,
        session: McpSession,
        config: ManagedMcpClientConfig,
    ) -> None:
        self._session = session
        self._config = config
        self._availability = McpAvailability.UNKNOWN
        self._reason = "not_probed"
        self._discovered_tools: frozenset[str] = frozenset()
        self._probe_lock = asyncio.Lock()
        self._dispatch_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._monitor_task: asyncio.Task[None] | None = None
        self._breaker = CircuitBreaker(
            name="mcp",
            config=CircuitBreakerConfig(
                failure_threshold=config.failure_threshold,
                reset_timeout_s=config.reset_timeout_seconds,
                half_open_max_calls=1,
            ),
        )

    @property
    def availability(self) -> McpAvailability:
        return self._availability

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def discovered_tools(self) -> frozenset[str]:
        return self._discovered_tools

    @property
    def is_routable(self) -> bool:
        return (
            self._availability is McpAvailability.AVAILABLE and self._breaker.state.value != "open"
        )

    def snapshot(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "availability": self._availability.value,
                "reason": self._reason,
                "discovered_tool_count": len(self._discovered_tools),
                "breaker": self._breaker.snapshot(),
            }
        )

    async def probe(self) -> bool:
        async with self._probe_lock:
            try:
                async with self._dispatch_lock:
                    tools = await asyncio.wait_for(
                        self._session.list_tools(),
                        timeout=self._config.startup_timeout_seconds,
                    )
            except TimeoutError:
                await self._reset_session()
                self._mark_unavailable("probe_timed_out")
                return False
            except Exception:  # noqa: BLE001 - provider details stay behind the boundary
                await self._reset_session()
                self._mark_unavailable("probe_failed")
                return False
            missing = self._config.allowed_tools - tools
            if missing:
                self._discovered_tools = tools
                self._mark_unavailable("allowlisted_tools_missing")
                return False
            self._discovered_tools = tools
            self._availability = McpAvailability.AVAILABLE
            self._reason = "ready"
            self._breaker.on_success()
            return True

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        timeout_seconds: float | None = None,
    ) -> McpCallResult:
        if name not in self._config.allowed_tools:
            raise ValueError(f"MCP tool {name!r} is not allowlisted")
        if self._availability is not McpAvailability.AVAILABLE:
            raise ManagedMcpUnavailableError(f"MCP provider is unavailable: {self._reason}")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("MCP call timeout_seconds MUST be positive")
        timeout = min(
            self._config.call_timeout_seconds if timeout_seconds is None else timeout_seconds,
            120.0,
        )
        try:
            async with self._dispatch_lock:
                return await self._breaker.call(
                    self._session.call_tool,
                    name,
                    dict(arguments),
                    timeout_seconds=timeout,
                )
        except asyncio.CancelledError:
            await self._reset_session()
            self._mark_unavailable("call_cancelled")
            raise
        except CircuitOpenError as exc:
            raise ManagedMcpUnavailableError("MCP provider circuit is open") from exc
        except Exception:
            if self._breaker.snapshot()["state"] == "open":
                self._mark_unavailable("circuit_open")
            raise

    def reject_result(self) -> None:
        """Score a transport-successful but invalid tool result as a failure."""
        self._breaker.on_failure()
        if self._breaker.snapshot()["state"] == "open":
            self._mark_unavailable("invalid_result")

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._monitor_task is not None:
                return
            self._stop.clear()
            await self.probe()
            self._monitor_task = asyncio.create_task(self._monitor(), name="mcp-health-monitor")

    async def close(self) -> None:
        async with self._lifecycle_lock:
            self._stop.set()
            monitor_task = self._monitor_task
            self._monitor_task = None
            try:
                if monitor_task is not None:
                    await monitor_task
            finally:
                async with self._dispatch_lock:
                    await self._session.close()

    async def _monitor(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._config.health_interval_seconds
                )
            except TimeoutError:
                await self.probe()

    def _mark_unavailable(self, reason: str) -> None:
        self._availability = McpAvailability.UNAVAILABLE
        self._reason = reason

    async def _reset_session(self) -> None:
        try:
            async with self._dispatch_lock:
                await self._session.close()
        except Exception:  # noqa: BLE001 - failed optional cleanup must not block fallback
            return


class PythonSdkMcpSession:
    """Official MCP Python SDK session for stdio or Streamable HTTP."""

    def __init__(
        self,
        server_parameters: ServerParameters,
        *,
        read_timeout_seconds: float,
        close_timeout_seconds: float = 1.0,
    ) -> None:
        if read_timeout_seconds <= 0:
            raise ValueError("MCP SDK read timeout MUST be positive")
        if not 0.1 <= close_timeout_seconds <= 10:
            raise ValueError("MCP SDK close timeout MUST be in [0.1, 10]")
        self._server_parameters = server_parameters
        self._read_timeout_seconds = read_timeout_seconds
        self._group: Any = None
        self._init_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._close_timeout_seconds = close_timeout_seconds

    @classmethod
    def stdio(
        cls,
        *,
        command: str,
        args: Sequence[str],
        environment: Mapping[str, str] | None = None,
        read_timeout_seconds: float = 15.0,
        close_timeout_seconds: float = 1.0,
    ) -> PythonSdkMcpSession:
        from mcp.client.stdio import StdioServerParameters

        return cls(
            StdioServerParameters(
                command=command,
                args=list(args),
                env=None if environment is None else dict(environment),
            ),
            read_timeout_seconds=read_timeout_seconds,
            close_timeout_seconds=close_timeout_seconds,
        )

    @classmethod
    def streamable_http(
        cls,
        *,
        url: str,
        headers: Mapping[str, str] | None = None,
        read_timeout_seconds: float = 15.0,
        close_timeout_seconds: float = 1.0,
    ) -> PythonSdkMcpSession:
        from mcp.client.session_group import StreamableHttpParameters

        return cls(
            StreamableHttpParameters(
                url=url,
                headers=None if headers is None else dict(headers),
                timeout=read_timeout_seconds,
                sse_read_timeout=read_timeout_seconds,
            ),
            read_timeout_seconds=read_timeout_seconds,
            close_timeout_seconds=close_timeout_seconds,
        )

    async def list_tools(self) -> frozenset[str]:
        async with self._operation_lock:
            group = await self._ensure_group()
            return frozenset(group.tools)

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        timeout_seconds: float,
    ) -> McpCallResult:
        async with self._operation_lock:
            group = await self._ensure_group()
            result = await asyncio.wait_for(
                group.call_tool(
                    name,
                    dict(arguments),
                    read_timeout_seconds=timeout_seconds,
                ),
                timeout=timeout_seconds,
            )
        return McpCallResult(
            structured_content=result.structured_content,
            content=tuple(result.content),
            is_error=result.is_error,
        )

    async def close(self) -> None:
        async with self._operation_lock:
            async with self._init_lock:
                group = self._group
                self._group = None
                if group is not None:
                    await self._close_group(group)

    async def _ensure_group(self) -> Any:
        if self._group is not None:
            return self._group
        async with self._init_lock:
            if self._group is not None:
                return self._group
            from mcp.client.session_group import ClientSessionGroup, ClientSessionParameters

            group = ClientSessionGroup()
            await group.__aenter__()
            try:
                await group.connect_to_server(
                    self._server_parameters,
                    ClientSessionParameters(read_timeout_seconds=self._read_timeout_seconds),
                )
            except BaseException:
                await self._close_group(group)
                raise
            self._group = group
            return group

    async def _close_group(self, group: Any) -> None:
        await asyncio.wait_for(
            group.__aexit__(None, None, None),
            timeout=self._close_timeout_seconds,
        )


__all__ = [
    "ManagedMcpClient",
    "ManagedMcpClientConfig",
    "ManagedMcpUnavailableError",
    "McpAvailability",
    "McpCallResult",
    "McpSession",
    "PythonSdkMcpSession",
]

"""MCP (Model Context Protocol) implementation of the
:class:`~fdai.shared.providers.tool.ToolExecutor` seam.

Design contract: ``docs/roadmap/decisioning/execution-model.md § 5.6 Tool call`` and
the "natural attach point for an MCP adapter" note in
``shared/providers/tool.py``. This is the first **real** ``ToolExecutor``:
it maps a ``tool.*`` ActionType onto one tool exposed by an MCP server and
invokes it over JSON-RPC 2.0. The upstream Day-1 binding stays
:class:`~fdai.shared.providers.testing.tool.RecordingToolExecutor`, so
dev / local-fake runs never make a network call and the parity contract
holds. ``core/`` only knows the ``ToolExecutor`` Protocol - this module is
bound at the composition root by a fork.

Safety semantics
----------------

- **Shadow is a real no-op.** The P1 core executor only dispatches
  ``Mode.SHADOW`` requests (enforce is refused upstream). A shadow request
  MUST NOT invoke the MCP tool and MUST NOT write the idempotency ledger -
  it returns a planned receipt describing what *would* run. This keeps the
  shadow-first invariant in ``architecture.instructions.md`` honest even
  though the caller still calls ``execute``. An ActionType that is not in
  ``tool_map`` still fails closed with a ``config`` :class:`ToolError`
  even in shadow, so a mis-wired ``tool_map`` surfaces before enforce
  rather than at the first real invocation.
- **Enforce requires the label.** An ``enforce`` request without the
  ``enforce`` label raises :class:`ToolPromotionError`, mirroring the
  direct-API promotion contract.
- **Idempotent by key.** A prior successful ledger entry short-circuits to
  :attr:`ToolCallOutcome.ALREADY_APPLIED`; the tool is not re-invoked.
- **Fail-closed.** A transport error or non-2xx response raises
  :class:`ToolError`; a JSON-RPC / MCP tool error maps to
  :attr:`ToolCallOutcome.FAILED`. The caller writes exactly one audit
  entry per attempt - this adapter never touches the audit log.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import count
from typing import Any, Final, Protocol, runtime_checkable

import httpx

from fdai.shared.contracts.models import Mode, StopConditionKind
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolCallReceipt,
    ToolCallRequest,
    ToolError,
    ToolPromotionError,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
_DEFAULT_MAX_REQUEST_BYTES: Final[int] = 1_000_000
_DEFAULT_MAX_RESPONSE_BYTES: Final[int] = 5_000_000


@runtime_checkable
class McpIdempotencyLedger(Protocol):
    """Durable dedupe store for MCP tool invocations.

    Kept minimal and async so a fork can back it with Postgres / Redis.
    The in-process :class:`InMemoryMcpLedger` default survives one process
    only; a real deployment injects a persistent implementation so a
    retried enforce call after a restart still short-circuits.
    """

    async def seen(self, key: str) -> str | None:
        """Return the recorded ``receipt_ref`` for ``key`` or ``None``."""
        ...

    async def record(self, key: str, receipt_ref: str) -> None:
        """Persist a successful invocation keyed by ``key``."""
        ...


class InMemoryMcpLedger:
    """Per-process ledger - the upstream default when none is injected."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def seen(self, key: str) -> str | None:
        return self._store.get(key)

    async def record(self, key: str, receipt_ref: str) -> None:
        self._store[key] = receipt_ref


@dataclass(frozen=True, slots=True)
class McpToolExecutorConfig:
    """Configuration for the MCP tool executor.

    ``tool_map`` binds each CSP-neutral ``tool.*`` ActionType name to the
    concrete MCP server tool name. A dispatch whose ActionType is absent
    fails closed with :class:`ToolError` (kind ``config``).
    """

    server_url: str
    tool_map: Mapping[str, str]
    audience: str | None = None
    """When set, a bearer token for this audience is attached via the
    injected :class:`WorkloadIdentity`. When ``None`` the server is
    reached unauthenticated (e.g. a sidecar on localhost)."""

    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS

    max_request_bytes: int = _DEFAULT_MAX_REQUEST_BYTES
    """Hard cap on the encoded JSON-RPC request body."""

    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES
    """Hard cap on the MCP response body. A larger body fails closed with
    a protocol :class:`ToolError` before it is parsed, so a misbehaving or
    hostile server cannot exhaust memory through the JSON decoder."""

    def __post_init__(self) -> None:
        if not self.server_url:
            raise ValueError("McpToolExecutorConfig.server_url MUST be non-empty")
        if self.max_request_bytes < 1:
            raise ValueError("McpToolExecutorConfig.max_request_bytes MUST be >= 1")
        if self.max_response_bytes < 1:
            raise ValueError("McpToolExecutorConfig.max_response_bytes MUST be >= 1")


class McpToolExecutor:
    """Invoke a registered MCP server tool for one ``tool.*`` ActionType."""

    def __init__(
        self,
        *,
        config: McpToolExecutorConfig,
        http_client: httpx.AsyncClient,
        identity: WorkloadIdentity | None = None,
        ledger: McpIdempotencyLedger | None = None,
    ) -> None:
        if config.audience and identity is None:
            raise ValueError(
                "McpToolExecutorConfig.audience is set but no WorkloadIdentity "
                "was injected to mint the bearer token"
            )
        self._config: Final[McpToolExecutorConfig] = config
        self._http: Final[httpx.AsyncClient] = http_client
        self._identity: Final[WorkloadIdentity | None] = identity
        self._ledger: Final[McpIdempotencyLedger] = ledger or InMemoryMcpLedger()
        self._rpc_ids = count(1)

    async def execute(self, request: ToolCallRequest) -> ToolCallReceipt:
        # 1. Promotion check - enforce needs the explicit label.
        if request.mode is Mode.ENFORCE and "enforce" not in request.labels:
            raise ToolPromotionError(
                "enforce-mode MCP tool call requires an explicit 'enforce' "
                "label (execution-model.md 5.6 promotion contract)"
            )

        # 2. Idempotency - a prior success wins, no re-invocation.
        prior_ref = await self._ledger.seen(request.idempotency_key)
        if prior_ref is not None:
            return ToolCallReceipt(
                outcome=ToolCallOutcome.ALREADY_APPLIED,
                receipt_ref=prior_ref,
                already_existed=True,
                detail="idempotency ledger hit",
            )

        mcp_tool = self._config.tool_map.get(request.action_type_name)
        if mcp_tool is None:
            raise ToolError(
                kind="config",
                message=(f"no MCP tool mapped for ActionType {request.action_type_name!r}"),
            )

        # 3. Shadow is a real no-op: never invoke, never record the ledger.
        if request.mode is Mode.SHADOW:
            return ToolCallReceipt(
                outcome=ToolCallOutcome.SUCCEEDED,
                receipt_ref=f"shadow:{mcp_tool}:{request.idempotency_key}",
                detail=f"shadow: would call MCP tool {mcp_tool!r} (no side effect)",
            )

        # 4. Enforce path - the real JSON-RPC invocation.
        timeout_seconds = self._execution_timeout(request)
        return await self._invoke(
            request=request,
            mcp_tool=mcp_tool,
            timeout_seconds=timeout_seconds,
        )

    def _execution_timeout(self, request: ToolCallRequest) -> float:
        timeout_seconds = self._config.timeout_seconds
        for condition in request.stop_conditions:
            if condition.kind is StopConditionKind.TIME_BOX_EXCEEDED_SECONDS:
                if condition.seconds is None:
                    raise ToolError(
                        kind="config",
                        message="MCP time-box stop condition requires seconds",
                    )
                timeout_seconds = min(timeout_seconds, float(condition.seconds))
                continue
            raise ToolError(
                kind="config",
                message=(
                    f"MCP executor has no evaluator for stop condition {condition.kind.value!r}"
                ),
            )
        return timeout_seconds

    async def _invoke(
        self,
        *,
        request: ToolCallRequest,
        mcp_tool: str,
        timeout_seconds: float,
    ) -> ToolCallReceipt:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._config.audience and self._identity is not None:
            token = await self._identity.get_token(self._config.audience)
            headers["Authorization"] = f"Bearer {token.token}"

        rpc_id = next(self._rpc_ids)
        body = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "tools/call",
            "params": {"name": mcp_tool, "arguments": dict(request.arguments)},
        }

        try:
            encoded_body = json.dumps(body)
        except (TypeError, ValueError) as exc:
            raise ToolError(
                kind="protocol",
                message=f"MCP arguments were not JSON-serializable for tool {mcp_tool!r}",
            ) from exc
        if len(encoded_body.encode("utf-8")) > self._config.max_request_bytes:
            raise ToolError(
                kind="protocol",
                message=f"MCP request exceeded the configured cap for tool {mcp_tool!r}",
            )

        try:
            response = await asyncio.wait_for(
                self._http.post(
                    self._config.server_url,
                    headers=headers,
                    content=encoded_body,
                    timeout=timeout_seconds,
                ),
                timeout=timeout_seconds,
            )
        except (TimeoutError, httpx.TimeoutException):
            return ToolCallReceipt(
                outcome=ToolCallOutcome.STOPPED,
                receipt_ref=f"mcp-timeout:{mcp_tool}",
                rollback_succeeded=False,
                detail="MCP tool exceeded its time-box stop condition",
            )
        except httpx.HTTPError as exc:
            raise ToolError(
                kind="transport",
                message=f"MCP transport failed for tool {mcp_tool!r}",
            ) from exc

        if not response.is_success:
            raise ToolError(
                kind="http",
                message=(f"MCP server returned HTTP {response.status_code} for tool {mcp_tool!r}"),
            )

        # Cap the body BEFORE parsing so a hostile/misbehaving server
        # cannot exhaust memory through the JSON decoder.
        if len(response.content) > self._config.max_response_bytes:
            raise ToolError(
                kind="protocol",
                message=(
                    f"MCP response for tool {mcp_tool!r} is "
                    f"{len(response.content)} bytes, over the "
                    f"{self._config.max_response_bytes}-byte cap"
                ),
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ToolError(
                kind="protocol",
                message=f"MCP server returned non-JSON for tool {mcp_tool!r}",
            ) from exc

        return await self._map_result(
            request=request, mcp_tool=mcp_tool, payload=payload, rpc_id=rpc_id
        )

    async def _map_result(
        self, *, request: ToolCallRequest, mcp_tool: str, payload: Any, rpc_id: int
    ) -> ToolCallReceipt:
        if not isinstance(payload, Mapping):
            raise ToolError(
                kind="protocol",
                message=f"MCP response is not a JSON object for tool {mcp_tool!r}",
            )

        # A JSON-RPC top-level error means the invocation itself failed.
        rpc_error = payload.get("error")
        if isinstance(rpc_error, Mapping):
            return ToolCallReceipt(
                outcome=ToolCallOutcome.FAILED,
                receipt_ref=f"mcp-error:{mcp_tool}",
                rollback_succeeded=None,
                detail="MCP server reported a JSON-RPC error",
            )

        result = payload.get("result")
        # An MCP tool that ran but reported failure sets result.isError.
        if isinstance(result, Mapping) and result.get("isError") is True:
            return ToolCallReceipt(
                outcome=ToolCallOutcome.FAILED,
                receipt_ref=f"mcp-tool-error:{mcp_tool}",
                rollback_succeeded=None,
                detail=f"MCP tool {mcp_tool!r} reported isError",
            )

        # JSON-RPC 2.0: a response carries EXACTLY ONE of result / error.
        # A body with neither (result is absent/null) is malformed - never
        # bank it as a successful side effect and never record the ledger,
        # otherwise a retry short-circuits to ALREADY_APPLIED forever on a
        # tool that never actually ran.
        if result is None:
            raise ToolError(
                kind="protocol",
                message=(
                    f"MCP response for tool {mcp_tool!r} carries neither a 'result' nor an 'error'"
                ),
            )

        # The response id MUST echo the request id (JSON-RPC 2.0). A
        # mismatch means we correlated the wrong response - fail closed
        # rather than bank an unrelated result.
        response_id = payload.get("id")
        if type(response_id) is not int or response_id != rpc_id:
            raise ToolError(
                kind="protocol",
                message=(
                    f"MCP response id {response_id!r} does not match request "
                    f"id {rpc_id!r} for tool {mcp_tool!r}"
                ),
            )

        receipt_ref = request.metadata.get("mcp_receipt_hint") or (
            f"mcp:{mcp_tool}:{request.idempotency_key}"
        )
        # The tool has already run at this point. If the durable ledger
        # write fails we MUST NOT surface a failure - that would make the
        # caller retry and double-apply the side effect. Record the gap
        # and return success; a post-restart retry is investigable via the
        # warning + the detail string.
        try:
            await self._ledger.record(request.idempotency_key, receipt_ref)
        except Exception as exc:  # noqa: BLE001 - ledger boundary, tool already ran
            _LOGGER.warning(
                "mcp_ledger_record_failed",
                extra={"tool": mcp_tool, "error_type": type(exc).__name__},
            )
            return ToolCallReceipt(
                outcome=ToolCallOutcome.SUCCEEDED,
                receipt_ref=receipt_ref,
                detail=(
                    f"MCP tool {mcp_tool!r} succeeded; idempotency ledger write "
                    f"failed (a post-restart retry may double-apply)"
                ),
            )
        return ToolCallReceipt(
            outcome=ToolCallOutcome.SUCCEEDED,
            receipt_ref=receipt_ref,
            detail=f"MCP tool {mcp_tool!r} succeeded",
        )


__all__ = [
    "InMemoryMcpLedger",
    "McpIdempotencyLedger",
    "McpToolExecutor",
    "McpToolExecutorConfig",
]

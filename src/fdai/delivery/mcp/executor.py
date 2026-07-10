"""MCP (Model Context Protocol) implementation of the
:class:`~fdai.shared.providers.tool.ToolExecutor` seam.

Design contract: ``docs/roadmap/execution-model.md § 5.6 Tool call`` and
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
  though the caller still calls ``execute``.
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

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import count
from typing import Any, Final, Protocol, runtime_checkable

import httpx

from fdai.shared.contracts.models import Mode
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

    def __post_init__(self) -> None:
        if not self.server_url:
            raise ValueError("McpToolExecutorConfig.server_url MUST be non-empty")


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
                message=(
                    f"no MCP tool mapped for ActionType "
                    f"{request.action_type_name!r}"
                ),
            )

        # 3. Shadow is a real no-op: never invoke, never record the ledger.
        if request.mode is Mode.SHADOW:
            return ToolCallReceipt(
                outcome=ToolCallOutcome.SUCCEEDED,
                receipt_ref=f"shadow:{mcp_tool}",
                detail=f"shadow: would call MCP tool {mcp_tool!r} (no side effect)",
            )

        # 4. Enforce path - the real JSON-RPC invocation.
        return await self._invoke(request=request, mcp_tool=mcp_tool)

    async def _invoke(self, *, request: ToolCallRequest, mcp_tool: str) -> ToolCallReceipt:
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
            response = await self._http.post(
                self._config.server_url,
                headers=headers,
                content=json.dumps(body),
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ToolError(
                kind="transport",
                message=f"MCP request failed for tool {mcp_tool!r}: {exc}",
            ) from exc

        if response.status_code >= 400:
            snippet = response.text[:200].replace("\n", " ")
            raise ToolError(
                kind="http",
                message=(
                    f"MCP server returned HTTP {response.status_code} for "
                    f"tool {mcp_tool!r}: {snippet!r}"
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
            message = str(rpc_error.get("message", "unknown MCP error"))[:200]
            return ToolCallReceipt(
                outcome=ToolCallOutcome.FAILED,
                receipt_ref=f"mcp-error:{mcp_tool}",
                rollback_succeeded=None,
                detail=f"MCP JSON-RPC error: {message}",
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
                    f"MCP response for tool {mcp_tool!r} carries neither a "
                    f"'result' nor an 'error'"
                ),
            )

        # The response id MUST echo the request id (JSON-RPC 2.0). A
        # mismatch means we correlated the wrong response - fail closed
        # rather than bank an unrelated result.
        response_id = payload.get("id")
        if response_id != rpc_id:
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
                "mcp ledger record failed for key %s (tool %r): %r",
                request.idempotency_key,
                mcp_tool,
                exc,
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

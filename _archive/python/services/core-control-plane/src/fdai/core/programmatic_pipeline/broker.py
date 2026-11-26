"""Capability-checked broker over the existing registered ToolExecutor seam."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.core.programmatic_pipeline.capability import (
    PipelineCapabilityAuthority,
    PipelineCapabilityError,
)
from fdai.core.programmatic_pipeline.models import (
    ProgrammaticCallStatus,
    ProgrammaticPipelineCallReceipt,
)
from fdai.core.programmatic_pipeline.store import ProgrammaticPipelineStore
from fdai.core.rpc import RpcMethod, RpcRegistry, RpcRequest, RpcResponse, RpcScope
from fdai.core.tools.executor import ToolExecutor
from fdai.shared.providers.programmatic_pipeline import (
    PipelineToolCall,
    PipelineToolResponse,
)


class ProgrammaticPipelineBroker:
    def __init__(
        self,
        *,
        authority: PipelineCapabilityAuthority,
        executor: ToolExecutor,
        store: ProgrammaticPipelineStore,
        max_output_bytes: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._authority = authority
        self._executor = executor
        self._store = store
        self._max_output_bytes = max_output_bytes
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._rpc = RpcRegistry().register(
            RpcMethod(
                name="programmatic_pipeline.tool_call",
                description="Dispatch one capability-scoped read-only pipeline tool call.",
                required_scope=RpcScope.READ,
                handler=self._dispatch_params,
            )
        )

    async def dispatch(self, call: PipelineToolCall) -> PipelineToolResponse:
        response = await self.invoke_rpc(
            RpcRequest(
                request_id=f"{call.run_id}:{call.call_id}",
                method="programmatic_pipeline.tool_call",
                params={
                    "run_id": call.run_id,
                    "capability_token": call.capability_token,
                    "call_id": call.call_id,
                    "tool_id": call.tool_id,
                    "arguments_json": call.arguments_json,
                },
            ),
            scopes=frozenset({RpcScope.READ}),
        )
        if not response.ok:
            return PipelineToolResponse(
                ok=False,
                error_code=response.error_code,
                error_message=response.error_message,
            )
        return PipelineToolResponse(
            ok=bool(response.result.get("ok")),
            output_json=_optional_string(response.result.get("output_json")),
            error_code=_optional_string(response.result.get("error_code")),
            error_message=_optional_string(response.result.get("error_message")),
        )

    async def invoke_rpc(
        self,
        request: RpcRequest,
        *,
        scopes: frozenset[RpcScope],
    ) -> RpcResponse:
        """Invoke the fixed read-only method through the shared RPC registry."""
        return await self._rpc.invoke(request, scopes=scopes)

    async def _dispatch_params(self, params: Mapping[str, Any]) -> Mapping[str, Any]:
        call = PipelineToolCall(
            run_id=_required_string(params, "run_id"),
            capability_token=_required_string(params, "capability_token"),
            call_id=_required_string(params, "call_id"),
            tool_id=_required_string(params, "tool_id"),
            arguments_json=_required_string(params, "arguments_json"),
        )
        response = await self._dispatch_call(call)
        return {
            "ok": response.ok,
            "output_json": response.output_json,
            "error_code": response.error_code,
            "error_message": response.error_message,
        }

    async def _dispatch_call(self, call: PipelineToolCall) -> PipelineToolResponse:
        started_at = self._clock()
        started = time.monotonic()
        input_bytes = len(call.arguments_json.encode("utf-8"))
        try:
            sequence = self._authority.authorize(
                run_id=call.run_id,
                token=call.capability_token,
                call_id=call.call_id,
                tool_id=call.tool_id,
                input_bytes=input_bytes,
            )
        except PipelineCapabilityError as exc:
            return PipelineToolResponse(ok=False, error_code=exc.code, error_message=str(exc))

        try:
            arguments = json.loads(call.arguments_json)
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments MUST be a JSON object")
            tool_result = await self._executor.dispatch(
                tool_id=call.tool_id,
                arguments=arguments,
            )
            output_json = json.dumps(
                tool_result.raw,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            output_bytes = len(output_json.encode("utf-8"))
            if output_bytes > self._max_output_bytes:
                raise ValueError("tool output exceeds the pipeline call limit")
        except Exception as exc:  # noqa: BLE001 - broker is an isolation boundary
            receipt = _receipt(
                call=call,
                sequence=sequence,
                status=ProgrammaticCallStatus.FAILED,
                input_bytes=input_bytes,
                output_json=None,
                started_at=started_at,
                finished_at=self._clock(),
                latency_ms=int((time.monotonic() - started) * 1000),
                error_code=type(exc).__name__,
            )
            await self._store.append_call(receipt)
            return PipelineToolResponse(
                ok=False,
                error_code="broker_failure",
                error_message="registered tool dispatch failed",
            )

        receipt = _receipt(
            call=call,
            sequence=sequence,
            status=ProgrammaticCallStatus.SUCCEEDED,
            input_bytes=input_bytes,
            output_json=output_json,
            started_at=started_at,
            finished_at=self._clock(),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        await self._store.append_call(receipt)
        return PipelineToolResponse(ok=True, output_json=output_json)


def _required_string(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"pipeline RPC param {key!r} MUST be a non-empty string")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _receipt(
    *,
    call: PipelineToolCall,
    sequence: int,
    status: ProgrammaticCallStatus,
    input_bytes: int,
    output_json: str | None,
    started_at: datetime,
    finished_at: datetime,
    latency_ms: int,
    error_code: str | None = None,
) -> ProgrammaticPipelineCallReceipt:
    input_digest = hashlib.sha256(call.arguments_json.encode("utf-8")).hexdigest()
    output_digest = (
        hashlib.sha256(output_json.encode("utf-8")).hexdigest() if output_json is not None else None
    )
    receipt_ref = f"pipeline-call:{call.run_id}:{sequence}"
    return ProgrammaticPipelineCallReceipt(
        run_id=call.run_id,
        call_id=call.call_id,
        tool_id=call.tool_id,
        sequence=sequence,
        status=status,
        input_digest=input_digest,
        output_digest=output_digest,
        receipt_ref=receipt_ref,
        started_at=started_at,
        finished_at=finished_at,
        latency_ms=latency_ms,
        input_bytes=input_bytes,
        output_bytes=0 if output_json is None else len(output_json.encode("utf-8")),
        error_code=error_code,
    )


__all__ = ["ProgrammaticPipelineBroker"]

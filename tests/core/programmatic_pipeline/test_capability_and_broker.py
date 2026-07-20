from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.programmatic_pipeline import (
    InMemoryProgrammaticPipelineStore,
    PipelineCapabilityAuthority,
    PipelineCapabilityError,
    ProgrammaticPipelineBroker,
)
from fdai.core.rpc import RpcRequest
from fdai.core.tools.executor import ToolResult
from fdai.shared.providers.programmatic_pipeline import PipelineToolCall


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class _Executor:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def dispatch(self, *, tool_id: str, arguments: dict[str, object]) -> ToolResult:
        self.calls.append((tool_id, arguments))
        if self.fail:
            raise RuntimeError("provider failed")
        return ToolResult(
            tool_id=tool_id,
            wrapped_text='<tool_result trusted="false">ok</tool_result>',
            raw={"items": [1, 2]},
            cost_usd=0.0,
            latency_ms=1,
        )


def _authority(clock: _Clock) -> tuple[PipelineCapabilityAuthority, str]:
    authority = PipelineCapabilityAuthority(clock=clock)
    capability = authority.issue(
        run_id="run-1",
        allowed_tools=frozenset({"tool.read-inventory"}),
        ttl_seconds=30,
        max_calls=1,
        max_input_bytes=64,
    )
    return authority, capability.token


def test_capability_rejects_forgery_wrong_run_replay_limit_and_expiry() -> None:
    clock = _Clock()
    authority, token = _authority(clock)

    with pytest.raises(PipelineCapabilityError, match="recognized") as forged:
        authority.authorize(
            run_id="run-1",
            token="forged",
            call_id="c-1",
            tool_id="tool.read-inventory",
            input_bytes=2,
        )
    assert forged.value.code == "forged_token"

    with pytest.raises(PipelineCapabilityError) as wrong_run:
        authority.authorize(
            run_id="run-2", token=token, call_id="c-1", tool_id="tool.read-inventory", input_bytes=2
        )
    assert wrong_run.value.code == "wrong_run"

    assert (
        authority.authorize(
            run_id="run-1", token=token, call_id="c-1", tool_id="tool.read-inventory", input_bytes=2
        )
        == 1
    )
    with pytest.raises(PipelineCapabilityError) as replay:
        authority.authorize(
            run_id="run-1", token=token, call_id="c-1", tool_id="tool.read-inventory", input_bytes=2
        )
    assert replay.value.code == "replay"
    with pytest.raises(PipelineCapabilityError) as limit:
        authority.authorize(
            run_id="run-1", token=token, call_id="c-2", tool_id="tool.read-inventory", input_bytes=2
        )
    assert limit.value.code == "call_limit"

    other = PipelineCapabilityAuthority(clock=clock)
    expiring = other.issue(
        run_id="run-expired",
        allowed_tools=frozenset({"tool.read-inventory"}),
        ttl_seconds=1,
        max_calls=1,
        max_input_bytes=8,
    )
    clock.now += timedelta(seconds=2)
    with pytest.raises(PipelineCapabilityError) as expired:
        other.authorize(
            run_id="run-expired",
            token=expiring.token,
            call_id="c-1",
            tool_id="tool.read-inventory",
            input_bytes=2,
        )
    assert expired.value.code == "expired_token"


@pytest.mark.parametrize(
    ("tool_id", "arguments", "code"),
    [
        ("tool.write-resource", "{}", "tool_forbidden"),
        ("tool.read-inventory", json.dumps({"value": "x" * 100}), "input_too_large"),
    ],
)
def test_capability_rejects_tool_and_input_overreach(
    tool_id: str, arguments: str, code: str
) -> None:
    clock = _Clock()
    authority, token = _authority(clock)
    with pytest.raises(PipelineCapabilityError) as error:
        authority.authorize(
            run_id="run-1",
            token=token,
            call_id="c-1",
            tool_id=tool_id,
            input_bytes=len(arguments.encode()),
        )
    assert error.value.code == code


async def test_broker_dispatches_existing_executor_and_persists_receipt() -> None:
    clock = _Clock()
    authority, token = _authority(clock)
    executor = _Executor()
    store = InMemoryProgrammaticPipelineStore()
    broker = ProgrammaticPipelineBroker(
        authority=authority,
        executor=executor,
        store=store,
        max_output_bytes=1_000,
        clock=clock,
    )

    response = await broker.dispatch(
        PipelineToolCall(
            run_id="run-1",
            capability_token=token,
            call_id="c-1",
            tool_id="tool.read-inventory",
            arguments_json='{"scope":"example"}',
        )
    )

    assert response.ok and json.loads(response.output_json or "null") == {"items": [1, 2]}
    assert executor.calls == [("tool.read-inventory", {"scope": "example"})]
    receipts = await store.calls_for("run-1")
    assert len(receipts) == 1
    assert receipts[0].receipt_ref == "pipeline-call:run-1:1"


async def test_broker_failure_is_bounded_and_receipted() -> None:
    clock = _Clock()
    authority, token = _authority(clock)
    store = InMemoryProgrammaticPipelineStore()
    broker = ProgrammaticPipelineBroker(
        authority=authority,
        executor=_Executor(fail=True),
        store=store,
        max_output_bytes=1_000,
        clock=clock,
    )
    response = await broker.dispatch(
        PipelineToolCall(
            run_id="run-1",
            capability_token=token,
            call_id="c-1",
            tool_id="tool.read-inventory",
            arguments_json="{}",
        )
    )

    assert response.error_code == "broker_failure"
    receipts = await store.calls_for("run-1")
    assert receipts[0].status.value == "failed"
    assert receipts[0].error_code == "RuntimeError"


async def test_broker_rejects_oversized_tool_output_and_receipts_failure() -> None:
    clock = _Clock()
    authority, token = _authority(clock)
    store = InMemoryProgrammaticPipelineStore()
    broker = ProgrammaticPipelineBroker(
        authority=authority,
        executor=_Executor(),
        store=store,
        max_output_bytes=4,
        clock=clock,
    )
    response = await broker.dispatch(
        PipelineToolCall(
            run_id="run-1",
            capability_token=token,
            call_id="c-1",
            tool_id="tool.read-inventory",
            arguments_json="{}",
        )
    )

    assert response.error_code == "broker_failure"
    assert (await store.calls_for("run-1"))[0].error_code == "ValueError"


async def test_broker_rpc_requires_read_scope_before_dispatch() -> None:
    clock = _Clock()
    authority, token = _authority(clock)
    executor = _Executor()
    store = InMemoryProgrammaticPipelineStore()
    broker = ProgrammaticPipelineBroker(
        authority=authority,
        executor=executor,
        store=store,
        max_output_bytes=1_000,
        clock=clock,
    )

    response = await broker.invoke_rpc(
        RpcRequest(
            request_id="rbac-denied",
            method="programmatic_pipeline.tool_call",
            params={
                "run_id": "run-1",
                "capability_token": token,
                "call_id": "c-1",
                "tool_id": "tool.read-inventory",
                "arguments_json": "{}",
            },
        ),
        scopes=frozenset(),
    )

    assert response.error_code == "forbidden"
    assert executor.calls == []
    assert await store.calls_for("run-1") == ()

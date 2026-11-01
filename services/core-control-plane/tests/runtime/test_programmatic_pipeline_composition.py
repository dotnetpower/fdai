"""Focused composition and ToolExecutor integration tests for ProgrammaticPipelineService."""

from __future__ import annotations

import hashlib
import json

from fdai.core.programmatic_pipeline import (
    InMemoryProgrammaticPipelineStore,
    ProgrammaticPipelineLimits,
    ProgrammaticPipelineStatus,
    ProgrammaticToolPipelineRequest,
)
from fdai.core.prompts.types import PromptMode
from fdai.core.tools import (
    CapabilityGate,
    DefaultToolExecutor,
    StaticToolRegistry,
    ToolArtifact,
    ToolProvider,
)
from fdai.runtime.programmatic_pipeline_runtime import build_programmatic_pipeline_service
from fdai.shared.providers.programmatic_pipeline import (
    PipelineRunnerOutput,
    PipelineRunnerStatus,
    PipelineRunSpec,
    PipelineToolBroker,
    PipelineToolCall,
)


class _ReadInventoryProvider(ToolProvider):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def call(
        self,
        *,
        artifact: ToolArtifact,
        arguments: dict[str, object],
    ) -> object:
        assert artifact.id == "tool.read-inventory"
        self.calls.append(dict(arguments))
        return {"items": [{"id": "vm-1", "region": arguments.get("region", "koreacentral")}]}


class _BrokerExercisingRunner:
    async def run(
        self,
        spec: PipelineRunSpec,
        *,
        broker: PipelineToolBroker,
    ) -> PipelineRunnerOutput:
        resp = await broker.dispatch(
            PipelineToolCall(
                run_id=spec.run_id,
                capability_token=spec.capability_token,
                call_id="call-1",
                tool_id="tool.read-inventory",
                arguments_json=json.dumps({"region": "koreacentral"}),
            )
        )
        assert resp.ok is True
        assert resp.output_json is not None
        # Attempt an unauthorized tool call and verify the broker denies it fail-closed
        denied = await broker.dispatch(
            PipelineToolCall(
                run_id=spec.run_id,
                capability_token=spec.capability_token,
                call_id="call-2",
                tool_id="tool.unregistered-mutate",
                arguments_json="{}",
            )
        )
        assert denied.ok is False
        return PipelineRunnerOutput(
            status=PipelineRunnerStatus.SUCCEEDED,
            stdout="ok",
            stderr="",
            final_json=resp.output_json,
            duration_ms=5,
        )

    async def cancel(self, run_id: str) -> bool:
        return bool(run_id)


def _registered_tool_executor() -> tuple[DefaultToolExecutor, _ReadInventoryProvider]:
    artifact = ToolArtifact(
        id="tool.read-inventory",
        version=1,
        description="Read inventory records",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["region"],
            "properties": {"region": {"type": "string", "minLength": 1}},
        },
        capability_gate=CapabilityGate(
            requires_tier=None,
            requires_novelty_score=None,
            cost_budget_usd_per_call=None,
        ),
        allowlist=None,
        output_wrapper='<tool_result trusted="false" tool="tool.read-inventory">{}</tool_result>',
        default_mode=PromptMode.ENFORCE,
        provider="inventory-provider",
        provenance_source="https://example.com/tools/read-inventory",
    )
    provider = _ReadInventoryProvider()
    registry = StaticToolRegistry((artifact,))
    executor = DefaultToolExecutor(
        registry=registry,
        providers={"inventory-provider": provider},
    )
    return executor, provider


async def test_composed_programmatic_pipeline_executes_through_registered_tool_executor() -> None:
    executor, provider = _registered_tool_executor()
    store = InMemoryProgrammaticPipelineStore()
    service = build_programmatic_pipeline_service(
        runner=_BrokerExercisingRunner(),
        executor=executor,
        store=store,
    )
    source = "def main(client, inputs):\n    return {'count': len(inputs)}\n"
    request = ProgrammaticToolPipelineRequest(
        run_id="run-comp-1",
        reviewed_source=source,
        reviewed_source_digest=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        idempotency_key="idem-comp-1",
        input_json=(json.dumps({"region": "koreacentral"}),),
        allowed_read_tools=frozenset({"tool.read-inventory"}),
        sandbox_profile_id="pipeline.local-read",
        limits=ProgrammaticPipelineLimits(),
    )

    result = await service.run(request)
    assert result.status is ProgrammaticPipelineStatus.SUCCEEDED
    assert result.complete is True
    assert result.stats.tool_calls == 1
    assert result.stats.succeeded_calls == 1
    assert len(result.receipt_refs) == 1
    assert len(provider.calls) == 1
    receipts = await store.calls_for("run-comp-1")
    assert len(receipts) == 1
    assert receipts[0].tool_id == "tool.read-inventory"

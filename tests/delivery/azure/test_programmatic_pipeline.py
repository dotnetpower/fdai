from __future__ import annotations

from dataclasses import replace

import pytest

from fdai.core.programmatic_pipeline.client import generate_pipeline_client
from fdai.delivery.azure.programmatic_pipeline import AzureIsolatedPipelineRunner
from fdai.shared.providers.programmatic_pipeline import (
    PipelineRunnerOutput,
    PipelineRunnerStatus,
    PipelineRunSpec,
    PipelineToolCall,
    PipelineToolResponse,
)


class _Broker:
    async def dispatch(self, call: PipelineToolCall) -> PipelineToolResponse:
        del call
        return PipelineToolResponse(ok=True, output_json="{}")


class _Client:
    def __init__(self) -> None:
        self.submitted = False

    async def submit(self, spec: PipelineRunSpec, *, broker: _Broker) -> PipelineRunnerOutput:
        del spec, broker
        self.submitted = True
        return PipelineRunnerOutput(PipelineRunnerStatus.SUCCEEDED, "", "", "{}", 1)

    async def cancel(self, run_id: str) -> bool:
        return run_id == "run-azure"


def _spec() -> PipelineRunSpec:
    source = "def main(client, inputs):\n    return {}\n"
    import hashlib

    return PipelineRunSpec(
        run_id="run-azure",
        source=source,
        source_digest=hashlib.sha256(source.encode()).hexdigest(),
        input_json=("{}",),
        capability_token="random-capability",
        client=generate_pipeline_client(frozenset({"tool.read-inventory"})),
        timeout_seconds=30,
        max_stdout_bytes=1_000,
        max_stderr_bytes=1_000,
        max_final_json_bytes=1_000,
    )


async def test_azure_adapter_submits_validated_spec_and_cancels() -> None:
    client = _Client()
    runner = AzureIsolatedPipelineRunner(client=client)

    output = await runner.run(_spec(), broker=_Broker())

    assert output.status is PipelineRunnerStatus.SUCCEEDED
    assert client.submitted
    assert await runner.cancel("run-azure")


async def test_azure_adapter_rejects_tampered_source_before_submission() -> None:
    client = _Client()
    runner = AzureIsolatedPipelineRunner(client=client)

    with pytest.raises(ValueError, match="source digest"):
        await runner.run(replace(_spec(), source="tampered"), broker=_Broker())

    assert not client.submitted

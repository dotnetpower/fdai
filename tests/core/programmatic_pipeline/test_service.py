from __future__ import annotations

import hashlib
import json

import pytest

from fdai.core.programmatic_pipeline import (
    InMemoryProgrammaticPipelineStore,
    ProgrammaticPipelineLimits,
    ProgrammaticPipelineService,
    ProgrammaticToolPipelineRequest,
)
from fdai.core.sandbox import (
    ProgrammaticPipelineSandboxCatalog,
    ProgrammaticPipelineSandboxProfile,
)
from fdai.core.tools.executor import ToolResult
from fdai.shared.providers.programmatic_pipeline import (
    PipelineRunnerOutput,
    PipelineRunnerStatus,
    PipelineRunSpec,
    PipelineToolBroker,
)


class _Runner:
    def __init__(self) -> None:
        self.calls = 0

    async def run(
        self,
        spec: PipelineRunSpec,
        *,
        broker: PipelineToolBroker,
    ) -> PipelineRunnerOutput:
        del broker
        self.calls += 1
        assert spec.client.allowed_tools == ("tool.read-inventory",)
        return PipelineRunnerOutput(
            status=PipelineRunnerStatus.SUCCEEDED,
            stdout="processed",
            stderr="",
            final_json='{"count":2}',
            duration_ms=4,
        )

    async def cancel(self, run_id: str) -> bool:
        return run_id == "run-1"


class _BrokenRunner(_Runner):
    async def run(
        self,
        spec: PipelineRunSpec,
        *,
        broker: PipelineToolBroker,
    ) -> PipelineRunnerOutput:
        del spec, broker
        raise RuntimeError("credential-canary")


class _Executor:
    async def dispatch(self, *, tool_id: str, arguments: dict[str, object]) -> ToolResult:
        return ToolResult(tool_id, "wrapped", arguments, 0.0, 0)


def _request(source: str, *, digest: str | None = None) -> ProgrammaticToolPipelineRequest:
    return ProgrammaticToolPipelineRequest(
        run_id="run-1",
        reviewed_source=source,
        reviewed_source_digest=digest or hashlib.sha256(source.encode()).hexdigest(),
        idempotency_key="pipeline-example-1",
        input_json=(json.dumps({"value": 1}), json.dumps({"value": 2})),
        allowed_read_tools=frozenset({"tool.read-inventory"}),
        sandbox_profile_id="pipeline.local-read",
        limits=ProgrammaticPipelineLimits(),
    )


def _service(runner: _Runner) -> ProgrammaticPipelineService:
    profile = ProgrammaticPipelineSandboxProfile(
        profile_id="pipeline.local-read",
        allowed_read_tools=frozenset({"tool.read-inventory"}),
        max_timeout_seconds=30,
        max_input_items=64,
        max_input_bytes=256_000,
        max_tool_calls=32,
        max_call_input_bytes=64_000,
        max_call_output_bytes=256_000,
        max_stdout_bytes=16_000,
        max_stderr_bytes=16_000,
        max_final_json_bytes=256_000,
    )
    return ProgrammaticPipelineService(
        runner=runner,
        executor=_Executor(),
        store=InMemoryProgrammaticPipelineStore(),
        sandbox_profiles=ProgrammaticPipelineSandboxCatalog((profile,)),
    )


async def test_service_validates_runs_projects_and_deduplicates() -> None:
    runner = _Runner()
    service = _service(runner)
    source = "def main(client, inputs):\n    return {'count': len(inputs)}\n"

    first = await service.run(_request(source))
    second = await service.run(_request(source))

    assert first == second
    assert first.complete
    assert first.compact_projection()["final"] == {"count": 2}
    assert runner.calls == 1


async def test_service_rejects_digest_mismatch_and_recursive_source() -> None:
    runner = _Runner()
    service = _service(runner)
    source = "def main(client, inputs):\n    return client.run_pipeline({})\n"

    mismatch = await service.run(_request(source, digest="0" * 64))
    assert mismatch.status.value == "rejected"
    assert "digest mismatch" in (mismatch.detail or "")

    recursive_request = _request(source)
    recursive_request = ProgrammaticToolPipelineRequest(
        run_id="run-2",
        reviewed_source=recursive_request.reviewed_source,
        reviewed_source_digest=recursive_request.reviewed_source_digest,
        idempotency_key="pipeline-example-2",
        input_json=recursive_request.input_json,
        allowed_read_tools=recursive_request.allowed_read_tools,
        sandbox_profile_id=recursive_request.sandbox_profile_id,
        limits=recursive_request.limits,
    )
    recursive = await service.run(recursive_request)
    assert recursive.status.value == "rejected"
    assert "recursive_pipeline" in (recursive.detail or "")
    assert runner.calls == 0


def test_sandbox_profile_preserves_tool_authorization_boundary() -> None:
    profile = ProgrammaticPipelineSandboxProfile(
        profile_id="pipeline.local-read",
        allowed_read_tools=frozenset({"tool.read-inventory"}),
        max_timeout_seconds=30,
        max_input_items=64,
        max_input_bytes=256_000,
        max_tool_calls=32,
        max_call_input_bytes=64_000,
        max_call_output_bytes=256_000,
        max_stdout_bytes=16_000,
        max_stderr_bytes=16_000,
        max_final_json_bytes=256_000,
    )
    source = "def main(client, inputs):\n    return {}\n"
    request = _request(source)
    request = ProgrammaticToolPipelineRequest(
        run_id=request.run_id,
        reviewed_source=request.reviewed_source,
        reviewed_source_digest=request.reviewed_source_digest,
        idempotency_key=request.idempotency_key,
        input_json=request.input_json,
        allowed_read_tools=frozenset({"tool.write-resource"}),
        sandbox_profile_id=request.sandbox_profile_id,
        limits=request.limits,
    )

    with pytest.raises(ValueError, match="outside"):
        ProgrammaticPipelineSandboxCatalog((profile,)).constrain(request)


async def test_service_marks_runner_adapter_failure_incomplete_without_secret() -> None:
    service = _service(_BrokenRunner())
    source = "def main(client, inputs):\n    return {}\n"

    result = await service.run(_request(source))

    assert result.status.value == "incomplete"
    assert not result.complete
    assert result.final_json is None
    assert "RuntimeError" in (result.detail or "")
    assert "credential-canary" not in (result.detail or "")

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from fdai.core.programmatic_pipeline import (
    InMemoryProgrammaticPipelineStore,
    ProgrammaticPipelineLimits,
    ProgrammaticPipelineService,
    ProgrammaticToolPipelineRequest,
)
from fdai.core.programmatic_pipeline.client import generate_pipeline_client
from fdai.core.sandbox import (
    ProgrammaticPipelineSandboxCatalog,
    ProgrammaticPipelineSandboxProfile,
)
from fdai.core.tools.executor import ToolResult
from fdai.delivery.local_programmatic_pipeline import (
    LocalPipelineConfig,
    LocalProgrammaticPipelineRunner,
)
from fdai.shared.providers.programmatic_pipeline import (
    PipelineRunnerStatus,
    PipelineRunSpec,
    PipelineToolCall,
    PipelineToolResponse,
)

requires_bubblewrap = pytest.mark.skipif(
    not Path("/usr/bin/bwrap").is_file(),
    reason="bubblewrap is unavailable on this test host",
)


@pytest.fixture
def workspace() -> Path:
    root = Path.cwd() / ".fdai-pipeline-test"
    assert not root.exists()
    root.mkdir(mode=0o700)
    try:
        yield root
        assert list(root.iterdir()) == []
    finally:
        shutil.rmtree(root)


class _Broker:
    def __init__(self) -> None:
        self.calls: list[PipelineToolCall] = []

    async def dispatch(self, call: PipelineToolCall) -> PipelineToolResponse:
        self.calls.append(call)
        return PipelineToolResponse(ok=True, output_json='{"rows":[1,2]}')


class _Executor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def dispatch(self, *, tool_id: str, arguments: dict[str, object]) -> ToolResult:
        self.calls.append(tool_id)
        return ToolResult(tool_id, "wrapped", {"rows": [1, 2]}, 0.0, 0)


def _spec(source: str, *, timeout: float = 2, run_id: str = "run-1") -> PipelineRunSpec:
    return PipelineRunSpec(
        run_id=run_id,
        source=source,
        source_digest=hashlib.sha256(source.encode()).hexdigest(),
        input_json=('{"value":1}',),
        capability_token="test-capability",
        client=generate_pipeline_client(frozenset({"tool.read-inventory"})),
        timeout_seconds=timeout,
        max_stdout_bytes=32,
        max_stderr_bytes=32,
        max_final_json_bytes=256,
    )


@requires_bubblewrap
async def test_local_runner_uses_unix_broker_and_isolated_source(workspace: Path) -> None:
    runner = LocalProgrammaticPipelineRunner(LocalPipelineConfig(workspace))
    broker = _Broker()
    source = (
        "def main(client, inputs):\n"
        "    print('example output')\n"
        "    return {'result': client.call('tool.read-inventory', {'value': inputs[0]['value']})}\n"
    )
    output = await runner.run(_spec(source), broker=broker)
    assert output.status is PipelineRunnerStatus.SUCCEEDED
    assert json.loads(output.final_json or "null") == {"result": {"rows": [1, 2]}}
    assert output.stdout == "example output\n"
    assert len(broker.calls) == 1
    assert broker.calls[0].tool_id == "tool.read-inventory"
    assert await runner.cancel("run-1") is False


async def test_local_runner_rejects_tampering_before_child_creation(workspace: Path) -> None:
    runner = LocalProgrammaticPipelineRunner(LocalPipelineConfig(workspace))
    spec = _spec("def main(client, inputs):\n    return {}\n")
    with pytest.raises(ValueError, match="source digest mismatch"):
        await runner.run(replace(spec, source_digest="0" * 64), broker=_Broker())
    with pytest.raises(ValueError, match="generated client mismatch"):
        await runner.run(
            replace(spec, client=replace(spec.client, source="untrusted")),
            broker=_Broker(),
        )


@requires_bubblewrap
async def test_local_runner_isolates_host_and_bounds_output(workspace: Path) -> None:
    runner = LocalProgrammaticPipelineRunner(LocalPipelineConfig(workspace))
    source = (
        "import os\n"
        "def main(client, inputs):\n"
        "    print('x' * 200)\n"
        "    return {'host_visible': os.path.exists('/home'), 'value': 'y' * 1000}\n"
    )
    output = await runner.run(_spec(source), broker=_Broker())
    assert output.status is PipelineRunnerStatus.INCOMPLETE
    assert output.final_json is None
    assert output.final_json_truncated
    assert output.stdout_truncated
    assert len(output.stdout.encode()) <= 32


@requires_bubblewrap
async def test_local_runner_cannot_read_host_home_or_inherited_environment(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FDAI_PIPELINE_TEST_SECRET", "unavailable")
    runner = LocalProgrammaticPipelineRunner(LocalPipelineConfig(workspace))
    source = (
        "import os\n"
        "def main(client, inputs):\n"
        "    return {'home': os.path.exists('/home'), "
        "'environment': os.getenv('FDAI_PIPELINE_TEST_SECRET')}\n"
    )
    output = await runner.run(_spec(source), broker=_Broker())
    assert output.status is PipelineRunnerStatus.SUCCEEDED
    assert json.loads(output.final_json or "null") == {"home": False, "environment": None}


@requires_bubblewrap
async def test_local_runner_bounds_raw_child_output_and_cleans_up(workspace: Path) -> None:
    runner = LocalProgrammaticPipelineRunner(LocalPipelineConfig(workspace))
    source = "import os\ndef main(client, inputs):\n    os.write(1, b'x' * 20000)\n    return {}\n"
    output = await runner.run(_spec(source), broker=_Broker())
    assert output.status is PipelineRunnerStatus.INCOMPLETE
    assert output.final_json is None


@requires_bubblewrap
async def test_local_runner_failed_source_and_spawn_failure_cleanup(workspace: Path) -> None:
    runner = LocalProgrammaticPipelineRunner(LocalPipelineConfig(workspace))
    source = "def main(client, inputs):\n    raise RuntimeError('private marker')\n"
    output = await runner.run(_spec(source), broker=_Broker())
    assert output.status is PipelineRunnerStatus.FAILED
    assert output.final_json is None
    assert "private marker" not in (output.detail or "")
    unavailable = LocalProgrammaticPipelineRunner(
        LocalPipelineConfig(workspace, bubblewrap="/nonexistent-bubblewrap")
    )
    with pytest.raises(FileNotFoundError):
        await unavailable.run(_spec(source), broker=_Broker())


@requires_bubblewrap
async def test_local_runner_timeout_kills_child_and_removes_workspace(workspace: Path) -> None:
    runner = LocalProgrammaticPipelineRunner(LocalPipelineConfig(workspace))
    source = "import time\ndef main(client, inputs):\n    time.sleep(10)\n    return {}\n"
    output = await runner.run(_spec(source, timeout=0.2), broker=_Broker())
    assert output.status is PipelineRunnerStatus.TIMED_OUT


@requires_bubblewrap
async def test_local_runner_cancellation_kills_child_and_clears_run(workspace: Path) -> None:
    runner = LocalProgrammaticPipelineRunner(LocalPipelineConfig(workspace))
    source = "import time\ndef main(client, inputs):\n    time.sleep(10)\n    return {}\n"
    task = asyncio.create_task(runner.run(_spec(source), broker=_Broker()))
    for _ in range(200):
        await asyncio.sleep(0.01)
        active = runner._active.get("run-1")
        if active is not None and active.process is not None:
            break
    else:
        pytest.fail("child process was not started")
    assert await runner.cancel("run-1")
    output = await task
    assert output.status is PipelineRunnerStatus.CANCELLED
    assert not runner._active


@requires_bubblewrap
async def test_local_runner_parent_task_cancellation_cleans_up(workspace: Path) -> None:
    runner = LocalProgrammaticPipelineRunner(LocalPipelineConfig(workspace))
    source = "import time\ndef main(client, inputs):\n    time.sleep(10)\n    return {}\n"
    task = asyncio.create_task(runner.run(_spec(source), broker=_Broker()))
    for _ in range(200):
        await asyncio.sleep(0.01)
        active = runner._active.get("run-1")
        if active is not None and active.process is not None:
            break
    else:
        pytest.fail("child process was not started")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not runner._active


@requires_bubblewrap
async def test_service_dispatches_registered_tool_and_reuses_result(workspace: Path) -> None:
    executor = _Executor()
    runner = LocalProgrammaticPipelineRunner(LocalPipelineConfig(workspace))
    store = InMemoryProgrammaticPipelineStore()
    service = ProgrammaticPipelineService(
        runner=runner,
        executor=executor,
        store=store,
        sandbox_profiles=ProgrammaticPipelineSandboxCatalog(
            (
                ProgrammaticPipelineSandboxProfile(
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
                ),
            )
        ),
    )
    source = (
        "from fdai_pipeline_client import PipelineClient\n"
        "def main(client, inputs):\n"
        "    return client.call('tool.read-inventory', {'value': inputs[0]['value']})\n"
    )
    request = ProgrammaticToolPipelineRequest(
        run_id="run-1",
        reviewed_source=source,
        reviewed_source_digest=hashlib.sha256(source.encode()).hexdigest(),
        idempotency_key="pipeline-local-example",
        input_json=('{"value":1}',),
        allowed_read_tools=frozenset({"tool.read-inventory"}),
        sandbox_profile_id="pipeline.local-read",
        limits=ProgrammaticPipelineLimits(),
    )
    first = await service.run(request)
    second = await service.run(request)
    assert first == second
    assert first.complete
    assert json.loads(first.final_json or "null") == {"rows": [1, 2]}
    assert first.receipt_refs == ("pipeline-call:run-1:1",)
    assert executor.calls == ["tool.read-inventory"]

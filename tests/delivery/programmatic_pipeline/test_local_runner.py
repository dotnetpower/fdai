from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

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
from fdai.delivery.programmatic_pipeline import (
    LocalProgrammaticPipelineRunner,
    LocalProgrammaticPipelineRunnerConfig,
)
from fdai.delivery.programmatic_pipeline.local_runner import _bubblewrap_argv


class _ReadExecutor:
    async def dispatch(self, *, tool_id: str, arguments: dict[str, object]) -> ToolResult:
        value = int(arguments["value"])
        return ToolResult(tool_id, "wrapped", {"items": [value, value + 1]}, 0.0, 1)


def _service(
    temp_root: Path,
    *,
    timeout: float = 2.0,
    stdout: int = 1_000,
    use_bubblewrap: bool = False,
):
    limits = ProgrammaticPipelineLimits(
        timeout_seconds=timeout,
        max_stdout_bytes=stdout,
        max_stderr_bytes=1_000,
        max_final_json_bytes=1_000,
    )
    profile = ProgrammaticPipelineSandboxProfile(
        profile_id="pipeline.local-read",
        allowed_read_tools=frozenset({"tool.read-inventory"}),
        max_timeout_seconds=5,
        max_input_items=64,
        max_input_bytes=256_000,
        max_tool_calls=32,
        max_call_input_bytes=64_000,
        max_call_output_bytes=256_000,
        max_stdout_bytes=16_000,
        max_stderr_bytes=16_000,
        max_final_json_bytes=256_000,
    )
    runner = LocalProgrammaticPipelineRunner(
        LocalProgrammaticPipelineRunnerConfig(
            use_bubblewrap=use_bubblewrap,
            temp_root=str(temp_root),
        )
    )
    service = ProgrammaticPipelineService(
        runner=runner,
        executor=_ReadExecutor(),
        store=InMemoryProgrammaticPipelineStore(),
        sandbox_profiles=ProgrammaticPipelineSandboxCatalog((profile,)),
    )
    return service, runner, limits


def _request(source: str, limits: ProgrammaticPipelineLimits, run_id: str = "run-local"):
    return ProgrammaticToolPipelineRequest(
        run_id=run_id,
        reviewed_source=source,
        reviewed_source_digest=hashlib.sha256(source.encode()).hexdigest(),
        idempotency_key=f"idempotency-{run_id}",
        input_json=(json.dumps({"value": 2}), json.dumps({"value": 5})),
        allowed_read_tools=frozenset({"tool.read-inventory"}),
        sandbox_profile_id="pipeline.local-read",
        limits=limits,
    )


async def test_local_runner_calls_broker_and_cleans_workspace(tmp_path: Path) -> None:
    service, _, limits = _service(tmp_path)
    source = """from fdai_pipeline_client import PipelineClient

def main(client: PipelineClient, inputs: list[object]) -> object:
    rows = []
    for item in inputs:
        rows.extend(client.call("tool.read-inventory", {"value": item["value"]})["items"])
    return {"sum": sum(rows)}
"""
    result = await service.run(_request(source, limits))

    assert result.complete
    assert json.loads(result.final_json or "null") == {"sum": 16}
    assert result.stats.tool_calls == 2
    assert list(tmp_path.iterdir()) == []


async def test_local_runner_scrubs_credentials_and_truncates_stdout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "credential-canary")
    service, _, limits = _service(tmp_path, stdout=64)
    source = """def main(client, inputs):
    print("x" * 500)
    return {"ok": True}
"""
    result = await service.run(_request(source, limits, "run-truncate"))

    assert result.complete
    assert result.truncated
    assert result.stdout.endswith("[truncated]")
    assert "credential-canary" not in result.stdout + result.stderr + (result.final_json or "")


async def test_local_runner_timeout_crash_and_cancel_are_incomplete(tmp_path: Path) -> None:
    timeout_service, _, timeout_limits = _service(tmp_path, timeout=0.1)
    looping = "def main(client, inputs):\n    while True:\n        pass\n"
    timed_out = await timeout_service.run(_request(looping, timeout_limits, "run-timeout"))
    assert timed_out.status.value == "timed_out"
    assert not timed_out.complete

    crash_service, _, crash_limits = _service(tmp_path)
    crashing = "def main(client, inputs):\n    raise RuntimeError('boom')\n"
    crashed = await crash_service.run(_request(crashing, crash_limits, "run-crash"))
    assert crashed.status.value == "failed"
    assert not crashed.complete

    cancel_service, runner, cancel_limits = _service(tmp_path, timeout=5)
    task = asyncio.create_task(cancel_service.run(_request(looping, cancel_limits, "run-cancel")))
    for _ in range(100):
        if await runner.cancel("run-cancel"):
            break
        await asyncio.sleep(0.005)
    cancelled = await task
    assert cancelled.status.value == "cancelled"
    assert not cancelled.complete
    assert list(tmp_path.iterdir()) == []


async def test_local_runner_marks_oversized_final_json_incomplete(tmp_path: Path) -> None:
    service, _, limits = _service(tmp_path)
    limits = ProgrammaticPipelineLimits(
        timeout_seconds=limits.timeout_seconds,
        max_final_json_bytes=16,
    )
    source = "def main(client, inputs):\n    return {'value': 'x' * 100}\n"

    result = await service.run(_request(source, limits, "run-final-limit"))

    assert result.status.value == "incomplete"
    assert not result.complete
    assert result.final_json is None
    assert result.truncated


def test_bubblewrap_command_has_offline_clearenv_read_only_source(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    runtime_dir = tmp_path / "runtime"
    source_dir.mkdir()
    runtime_dir.mkdir()
    config = LocalProgrammaticPipelineRunnerConfig()

    argv = _bubblewrap_argv(
        config=config,
        source_dir=source_dir,
        runtime_dir=runtime_dir,
    )

    assert "--unshare-all" in argv
    assert "--clearenv" in argv
    assert argv[argv.index("--ro-bind") + 1] in {"/usr", "/bin", "/lib", "/lib64"}
    source_index = argv.index(str(source_dir))
    assert argv[source_index - 1] == "--ro-bind"
    assert "AZURE_CLIENT_SECRET" not in argv


@pytest.mark.skipif(not Path("/usr/bin/bwrap").is_file(), reason="bubblewrap is unavailable")
async def test_bubblewrap_runner_smoke(tmp_path: Path) -> None:
    service, _, limits = _service(tmp_path, use_bubblewrap=True)
    source = "def main(client, inputs):\n    return {'count': len(inputs)}\n"

    result = await service.run(_request(source, limits, "run-bubblewrap"))

    assert result.complete
    assert result.final_json == '{"count":2}'

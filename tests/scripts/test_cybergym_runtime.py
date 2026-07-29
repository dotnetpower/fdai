"""CyberGym Docker runtime boundary tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from scripts.benchmarking.cybergym_runtime import (
    CommandExecutor,
    CyberGymDockerRuntime,
    CyberGymPaths,
    CyberGymRuntimeError,
    CyberGymTask,
    ProcessResult,
    _agent_prompt,
    _validation_status,
    _write_command_receipt,
    copilot_sandbox_argv,
    load_task,
    verify_outputs,
)


def _paths(tmp_path: Path) -> CyberGymPaths:
    values = tuple(tmp_path / name for name in ("harness", "data", "output", "copilot"))
    for value in values:
        value.mkdir()
    return CyberGymPaths(*values)


def _task(paths: CyberGymPaths, *, mode: str = "e2e") -> CyberGymTask:
    script_path = paths.harness_root / "projects/example/task-1"
    data_path = paths.data_root / "example/task-1"
    script_path.mkdir(parents=True, exist_ok=True)
    data_path.mkdir(parents=True, exist_ok=True)
    return CyberGymTask(
        task_path="example/task-1",
        mode=mode,
        build_image="example/image@sha256:" + "0" * 64,
        repo_to_patch="project",
        immutable_files=("tests",),
        pre_patches=(),
        script_path=script_path,
        data_path=data_path,
    )


def test_load_task_merges_project_and_task_config(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    project = paths.harness_root / "projects/example"
    task = project / "task-1"
    data = paths.data_root / "example/task-1"
    task.mkdir(parents=True)
    data.mkdir(parents=True)
    project.joinpath("project.toml").write_text(
        'build_image = "example/image@sha256:'
        + "0" * 64
        + '"\nrepo_to_patch = "project"\nimmutable_files = ["tests"]\n',
        encoding="utf-8",
    )
    task.joinpath("config.toml").write_text('pre_patch = "setup.diff"\n', encoding="utf-8")

    loaded = load_task(paths, "example/task-1", mode="patch-only")

    assert loaded.mode == "patch-only"
    assert loaded.repo_to_patch == "project"
    assert loaded.immutable_files == ("tests",)
    assert loaded.pre_patches == ("setup.diff",)


@pytest.mark.parametrize("task_path", ("../task", "project", "/project/task", "project/a/b"))
def test_load_task_rejects_unbounded_task_path(tmp_path: Path, task_path: str) -> None:
    with pytest.raises(CyberGymRuntimeError, match="project/task"):
        load_task(_paths(tmp_path), task_path, mode="e2e")


@pytest.mark.parametrize(
    ("project_config", "task_config", "key"),
    (
        ('repo_to_patch = "../outside"\nimmutable_files = []\n', "", "repo_to_patch"),
        ('repo_to_patch = "/outside"\nimmutable_files = []\n', "", "repo_to_patch"),
        (
            'repo_to_patch = "project"\nimmutable_files = ["../tests"]\n',
            "",
            "immutable_files",
        ),
        (
            'repo_to_patch = "project"\nimmutable_files = []\n',
            'pre_patch = "../../outside.diff"\n',
            "pre_patches",
        ),
    ),
)
def test_load_task_rejects_config_paths_outside_declared_roots(
    tmp_path: Path,
    project_config: str,
    task_config: str,
    key: str,
) -> None:
    paths = _paths(tmp_path)
    project = paths.harness_root / "projects/example"
    task = project / "task-1"
    task.mkdir(parents=True)
    project.joinpath("project.toml").write_text(
        'build_image = "example/image@sha256:' + "0" * 64 + '"\n' + project_config,
        encoding="utf-8",
    )
    task.joinpath("config.toml").write_text(task_config, encoding="utf-8")

    with pytest.raises(CyberGymRuntimeError, match=key):
        load_task(paths, "example/task-1", mode="patch-only")


def test_verify_outputs_enforces_mode_and_bounds(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    task = _task(paths)
    artifacts = paths.output_root / "artifacts"
    artifacts.mkdir()
    artifacts.joinpath("fix.patch").write_text("diff --git a/a b/a\n", encoding="utf-8")

    with pytest.raises(CyberGymRuntimeError, match="poc.bin"):
        verify_outputs(task, artifacts)

    artifacts.joinpath("poc.bin").write_bytes(b"poc")
    verify_outputs(task, artifacts)


@pytest.mark.parametrize("file_descriptor", (1, 2))
def test_command_executor_stops_output_above_cap(file_descriptor: int) -> None:
    command = (
        sys.executable,
        "-c",
        f"import os; os.write({file_descriptor}, b'x' * (2 * 1024 * 1024 + 1))",
    )

    with pytest.raises(CyberGymRuntimeError, match="byte cap"):
        CommandExecutor().run(command, timeout=10)


def test_command_executor_preserves_bounded_output_streams() -> None:
    result = CommandExecutor().run(
        (
            sys.executable,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr)",
        ),
        timeout=10,
    )

    assert result == ProcessResult(0, "out\n", "err\n")


def test_copilot_sandbox_exposes_only_task_and_output_writes(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    workspace = paths.output_root / "workspace"
    artifacts = paths.output_root / "artifacts"
    workspace.mkdir()
    artifacts.mkdir()

    argv = copilot_sandbox_argv(
        paths=paths,
        workspace_root=workspace,
        artifact_root=artifacts,
        prompt="repair",
    )

    assert argv[0] == "/usr/bin/bwrap"
    assert ("--bind", str(workspace), "/src") == _triple(argv, str(workspace))
    assert ("--bind", str(artifacts), "/output") == _triple(argv, str(artifacts))
    assert "--deny-tool=shell" in argv
    assert "--deny-tool=url" in argv
    assert "--disable-builtin-mcps" in argv
    assert "--allow-all-paths" not in argv


def test_agent_prompt_requires_patched_poc_to_exit_successfully(tmp_path: Path) -> None:
    prompt = _agent_prompt(_task(_paths(tmp_path), mode="patch-only"))

    assert "run_poc.sh must exit with status 0 for a repaired input" in prompt
    assert "nonzero status instead of crashing does not pass validation" in prompt


def test_validation_stops_dependent_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    runtime = CyberGymDockerRuntime(paths=paths)
    task = _task(paths)
    called: list[int] = []

    def validate_stage(
        task_value: CyberGymTask,
        *,
        stage: int,
        artifact_root: Path,
        receipt_path: Path,
    ) -> str:
        assert task_value is task
        called.append(stage)
        return "failed" if stage == 1 else "passed"

    monkeypatch.setattr(runtime, "_validate_stage", validate_stage)

    results = runtime._validate(task, paths.output_root, paths.output_root)  # noqa: SLF001

    assert called == [1]
    assert results == {
        "stage1": "failed",
        "stage2": "skipped",
        "stage3": "skipped",
        "stage4": "skipped",
    }


@pytest.mark.parametrize(
    ("payload", "expected"),
    (
        ({"stage3": "passed"}, "passed"),
        ({"stage3": {"status": "failed"}}, "failed"),
        ({"stage3": None}, None),
    ),
)
def test_validation_status_accepts_official_and_internal_shapes(
    payload: object,
    expected: str | None,
) -> None:
    assert _validation_status(payload, 3) == expected


def test_command_receipt_preserves_bounded_validator_failure(tmp_path: Path) -> None:
    path = tmp_path / "stage3.json"
    _write_command_receipt(
        path,
        stage=3,
        process=ProcessResult(2, "x" * 5_000, "failure"),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["stage"] == 3
    assert payload["status"] == "error"
    assert len(payload["stdout_tail"]) == 4_096
    assert payload["stderr_tail"] == "failure"


def _triple(argv: tuple[str, ...], value: str) -> tuple[str, str, str]:
    index = argv.index(value)
    return argv[index - 1], argv[index], argv[index + 1]

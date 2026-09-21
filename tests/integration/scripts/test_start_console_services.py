from __future__ import annotations

import hashlib
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

_BASH = "/usr/bin/bash"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEV_UP_SCRIPT = _REPO_ROOT / "scripts/deployment/local/dev-up.sh"
_LOCAL_COMPOSE = _REPO_ROOT / "infra/local/docker-compose.yml"
_PREPARE_SCRIPT = _REPO_ROOT / "scripts/deployment/local/prepare-console-full-stack.sh"
_RUN_SERVICE_SCRIPT = _REPO_ROOT / "scripts/deployment/local/run-console-service.sh"
_START_SCRIPT = _REPO_ROOT / "scripts/deployment/local/start-console-services.sh"
_BOUNDED_RUNNER = _REPO_ROOT / "scripts/automation/run-bounded-command.py"


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_ready_dependency_script(repo: Path) -> None:
    _write_executable(
        repo / "scripts/deployment/local/dev-up.sh",
        "#!/usr/bin/env bash\nexit 0\n",
    )


def test_local_redpanda_reserves_capacity_for_parallel_semantic_partitions() -> None:
    compose = yaml.safe_load(_LOCAL_COMPOSE.read_text(encoding="utf-8"))
    nofile = compose["services"]["redpanda"]["ulimits"]["nofile"]

    assert nofile == {"soft": 65536, "hard": 65536}


def test_core_runtime_digest_includes_prompt_catalog() -> None:
    script = _RUN_SERVICE_SCRIPT.read_text(encoding="utf-8")

    assert 'if [[ "$service" == "core-runtime" ]]' in script
    assert "digest_inputs+=(rule-catalog)" in script
    assert '--timing-label "$service"' in script
    assert '--core-ready-after "$readiness_started_at"' in script


def test_preparation_reports_named_digest_and_stage_durations() -> None:
    script = _PREPARE_SCRIPT.read_text(encoding="utf-8")

    assert "service=local-input-digest stage=%s event=completed duration_ms=%s" in script
    assert "path_digest authoritative-inventory" in script
    assert "path_digest authoritative-catalogs" in script
    assert "event=reused duration_ms=%s" in script
    assert "event=completed duration_ms=%s" in script


def test_console_launcher_uses_prepared_local_auth_mode() -> None:
    script = _RUN_SERVICE_SCRIPT.read_text(encoding="utf-8")

    assert 'expected_auth_mode="${FDAI_CONSOLE_EXPECTED_AUTH_MODE:-}"' in script
    assert 'VITE_LOCAL_AZURE_CLI_AUTH="$local_azure_cli_auth"' in script
    assert 'VITE_LOCAL_AZURE_CLI_AUTH_CONFIRM="$local_azure_cli_auth"' in script
    assert "local-console-auth-mode" not in script


def test_preparation_rejects_missing_opa_before_starting_dependencies(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    script = repo / "scripts/deployment/local/prepare-console-full-stack.sh"
    script.parent.mkdir(parents=True)
    shutil.copy2(_PREPARE_SCRIPT, script)
    _write_executable(repo / ".venv/bin/python", "#!/bin/bash\nexit 99\n")
    (repo / "console").mkdir()
    (repo / "console/.env.local").write_text("", encoding="utf-8")
    binaries = tmp_path / "bin"
    _write_executable(binaries / "npm", "#!/bin/bash\nexit 99\n")
    (binaries / "dirname").symlink_to(shutil.which("dirname") or "/usr/bin/dirname")

    result = subprocess.run(  # noqa: S603 - isolated local prerequisite check
        [_BASH, str(script)],
        env={"PATH": str(binaries)},
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert result.returncode == 1
    assert "missing OPA" in result.stderr
    assert not (repo / ".fdai").exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--auth-mode"],
        ["--auth-mode", "unexpected"],
        ["--unknown"],
    ],
)
def test_preparation_rejects_invalid_auth_mode_arguments(
    tmp_path: Path,
    arguments: list[str],
) -> None:
    repo = tmp_path / "repo"
    script = repo / "scripts/deployment/local/prepare-console-full-stack.sh"
    script.parent.mkdir(parents=True)
    shutil.copy2(_PREPARE_SCRIPT, script)

    result = subprocess.run(  # noqa: S603 - isolated argument validation.
        [_BASH, str(script), *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert not (repo / ".fdai").exists()


def _operator_restart_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    run_script = repo / "scripts/deployment/local/run-console-service.sh"
    run_script.parent.mkdir(parents=True)
    shutil.copy2(_RUN_SERVICE_SCRIPT, run_script)
    (repo / ".fdai").mkdir()
    (repo / ".fdai/local-console-auth-mode").write_text("browser-entra\n", encoding="utf-8")
    (repo / ".fdai/local-operator-service.env").write_text(
        "FDAI_OPERATOR_API_LOCAL_AZURE_CLI=0\n"
        "FDAI_OPERATOR_API_LOCAL_AZURE_CLI_CONFIRM=0\n"
        "FDAI_DEVELOPMENT_DIAGNOSTICS=0\n",
        encoding="utf-8",
    )
    _write_executable(
        repo / "scripts/automation/run-local-service.sh",
        """#!/usr/bin/env bash
status="${FDAI_TEST_RUNNER_STATUS:-0}"
if [[ "$status" != "0" ]]; then
    exit "$status"
fi
printf '%s\n' "${FDAI_DEVELOPMENT_DIAGNOSTICS:-}" > diagnostics.txt
sleep "${FDAI_TEST_LAUNCH_DELAY:-0}"
printf '2026-08-26T00:00:00.000000+00:00 service=operator-api event=starting\n'
printf '2026-08-26T00:00:00.000000+00:00 service=operator-api event=reused\n'
printf 'launch\n' >> "$FDAI_TEST_ORDER_FILE"
mkdir -p "$(dirname "$FDAI_LOCAL_SERVICE_LAUNCH_MARKER")"
printf '%s\n' "${FDAI_TEST_LAUNCH_EVENT:-reused}" > "$FDAI_LOCAL_SERVICE_LAUNCH_MARKER"
""",
    )
    _write_executable(
        repo / ".venv/bin/python",
        """#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  */local-service-input-digest.py) printf '%064d\n' 0 ;;
  */run-bounded-command.py)
        printf 'readiness\n' >> "$FDAI_TEST_ORDER_FILE"
    sleep "${FDAI_TEST_READINESS_DELAY:-0}"
    exit "${FDAI_TEST_READINESS_STATUS:-0}"
    ;;
  *) printf 'unexpected python call: %s\n' "$1" >&2; exit 99 ;;
esac
""",
    )
    return repo


def _run_operator_restart(
    repo: Path,
    *,
    readiness_status: int = 0,
    readiness_delay: int = 0,
    runner_status: int = 0,
    launch_delay: int = 0,
    launch_event: str = "reused",
) -> subprocess.CompletedProcess[str]:
    order_file = repo / "order.txt"
    return subprocess.run(  # noqa: S603 - fixed test script with test-owned environment.
        [
            _BASH,
            str(repo / "scripts/deployment/local/run-console-service.sh"),
            "operator-api",
            "--wait-ready",
        ],
        cwd=repo,
        env={
            **os.environ,
            "FDAI_CONSOLE_EXPECTED_AUTH_MODE": "browser-entra",
            "FDAI_TEST_LAUNCH_DELAY": str(launch_delay),
            "FDAI_TEST_LAUNCH_EVENT": launch_event,
            "FDAI_TEST_ORDER_FILE": str(order_file),
            "FDAI_TEST_READINESS_DELAY": str(readiness_delay),
            "FDAI_TEST_READINESS_STATUS": str(readiness_status),
            "FDAI_TEST_RUNNER_STATUS": str(runner_status),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )


def test_operator_restart_emits_ready_after_reuse(tmp_path: Path) -> None:
    repo = _operator_restart_repo(tmp_path)
    result = _run_operator_restart(repo, launch_delay=1)

    assert result.returncode == 0
    assert (repo / "order.txt").read_text(encoding="utf-8").splitlines() == [
        "launch",
        "readiness",
    ]
    assert "service=operator-api event=ready" in result.stdout
    assert "service=operator-api event=failed" not in result.stderr


def test_operator_launcher_always_enables_development_diagnostics(tmp_path: Path) -> None:
    repo = _operator_restart_repo(tmp_path)

    result = _run_operator_restart(repo)

    assert result.returncode == 0
    assert (repo / "diagnostics.txt").read_text(encoding="utf-8") == "1\n"
    assert "core-runtime|operator-api)" in _RUN_SERVICE_SCRIPT.read_text(encoding="utf-8")


def test_operator_launcher_prints_input_digest_without_auth_or_start(tmp_path: Path) -> None:
    repo = _operator_restart_repo(tmp_path)

    result = subprocess.run(  # noqa: S603 - fixed test-owned launcher.
        [
            _BASH,
            str(repo / "scripts/deployment/local/run-console-service.sh"),
            "operator-api",
            "--print-input-digest",
        ],
        cwd=repo,
        env=os.environ,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 0
    assert result.stdout == f"{'0' * 64}\n"
    assert not (repo / "diagnostics.txt").exists()


def test_operator_restart_emits_failed_for_readiness_failure(tmp_path: Path) -> None:
    result = _run_operator_restart(
        _operator_restart_repo(tmp_path),
        readiness_status=7,
    )

    assert result.returncode == 7
    assert "service=operator-api event=ready" not in result.stdout
    assert "service=operator-api event=failed stage=readiness exit_code=7" in result.stderr


def test_operator_restart_emits_failed_for_runner_failure(tmp_path: Path) -> None:
    result = _run_operator_restart(
        _operator_restart_repo(tmp_path),
        readiness_delay=1,
        runner_status=9,
    )

    assert result.returncode == 9
    assert "service=operator-api event=ready" not in result.stdout
    assert "service=operator-api event=failed stage=runner exit_code=9" in result.stderr


def test_operator_restart_rejects_started_service_early_zero_exit(tmp_path: Path) -> None:
    result = _run_operator_restart(
        _operator_restart_repo(tmp_path),
        readiness_delay=1,
        launch_event="starting",
    )

    assert result.returncode == 1
    assert "service=operator-api event=ready" not in result.stdout
    assert "service=operator-api event=failed stage=runner exit_code=1" in result.stderr


def test_operator_restart_rejects_prepared_auth_mode_mismatch(tmp_path: Path) -> None:
    repo = _operator_restart_repo(tmp_path)
    (repo / ".fdai/local-operator-service.env").write_text(
        "FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1\nFDAI_OPERATOR_API_LOCAL_AZURE_CLI_CONFIRM=1\n",
        encoding="utf-8",
    )

    result = _run_operator_restart(repo)

    assert result.returncode == 1
    assert "prepared Console and Operator API auth modes do not match" in result.stderr
    assert not (repo / "order.txt").exists()


def test_wait_ready_wrapper_forwards_term_and_reaps_runner(tmp_path: Path) -> None:
    repo = _operator_restart_repo(tmp_path)
    runner_pid_file = repo / "runner.pid"
    stopped_file = repo / "runner.stopped"
    _write_executable(
        repo / "scripts/automation/run-local-service.sh",
        """#!/usr/bin/env bash
set -euo pipefail
    setsid sleep 60 &
    child_pid=$!
stop_child() {
    kill -TERM -- "-$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
    printf stopped > "$FDAI_TEST_STOPPED_FILE"
    exit 143
}
trap stop_child TERM
    printf '%s %s\n' "$$" "$child_pid" > "$FDAI_TEST_RUNNER_PID_FILE"
    mkdir -p "$(dirname "$FDAI_LOCAL_SERVICE_LAUNCH_MARKER")"
printf '%s\n' starting > "$FDAI_LOCAL_SERVICE_LAUNCH_MARKER"
    wait "$child_pid"
""",
    )
    _write_executable(
        repo / ".venv/bin/python",
        """#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  */local-service-input-digest.py) printf '%064d\n' 0 ;;
  */run-bounded-command.py) exec sleep 60 ;;
  *) printf 'unexpected python call: %s\n' "$1" >&2; exit 99 ;;
esac
""",
    )
    process = subprocess.Popen(  # noqa: S603 - fixed test-owned launcher.
        [
            _BASH,
            str(repo / "scripts/deployment/local/run-console-service.sh"),
            "operator-api",
            "--wait-ready",
        ],
        cwd=repo,
        env={
            **os.environ,
            "FDAI_CONSOLE_EXPECTED_AUTH_MODE": "browser-entra",
            "FDAI_TEST_RUNNER_PID_FILE": str(runner_pid_file),
            "FDAI_TEST_STOPPED_FILE": str(stopped_file),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    runner_pid = 0
    child_pid = 0
    try:
        deadline = time.monotonic() + 3
        while not runner_pid_file.exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.02)
        runner_pid, child_pid = (
            int(value) for value in runner_pid_file.read_text(encoding="utf-8").split()
        )

        process.terminate()
        assert process.wait(timeout=5) == 143

        assert stopped_file.read_text(encoding="utf-8") == "stopped"
        with pytest.raises(ProcessLookupError):
            os.kill(runner_pid, 0)
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if runner_pid:
            try:
                os.kill(runner_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if child_pid:
            try:
                os.killpg(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_supervisor_reports_a_service_that_exits_before_readiness(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    start_script = repo / "scripts/deployment/local/start-console-services.sh"
    start_script.parent.mkdir(parents=True)
    shutil.copy2(_START_SCRIPT, start_script)
    (repo / ".fdai/logs").mkdir(parents=True)
    (repo / ".fdai/local-console-auth-mode").write_text("browser-entra\n", encoding="utf-8")

    _write_executable(
        repo / "scripts/deployment/local/run-console-service.sh",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "document-ingestion-api" ]]; then
  exit 9
fi
exec sleep 10
""",
    )
    _write_executable(
        repo / ".venv/bin/python",
        """#!/usr/bin/env bash
set -euo pipefail
    exec sleep 10
""",
    )

    started = time.monotonic()
    result = subprocess.run(  # noqa: S603 - fixed test script and executable.
        [_BASH, str(start_script), "--auth-mode", "browser-entra"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert time.monotonic() - started < 2
    assert result.returncode == 9
    assert "service exited before readiness: document-ingestion-api" in result.stderr
    assert "service=console-stack event=failed" in result.stderr
    assert "stage=service-startup service=document-ingestion-api exit_code=9" in result.stderr


def test_supervisor_propagates_an_immediate_readiness_failure(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    start_script = repo / "scripts/deployment/local/start-console-services.sh"
    start_script.parent.mkdir(parents=True)
    shutil.copy2(_START_SCRIPT, start_script)
    (repo / ".fdai/logs").mkdir(parents=True)
    (repo / ".fdai/local-console-auth-mode").write_text("browser-entra\n", encoding="utf-8")
    _write_executable(
        repo / "scripts/deployment/local/run-console-service.sh",
        "#!/usr/bin/env bash\nexec sleep 10\n",
    )
    _write_executable(repo / ".venv/bin/python", "#!/usr/bin/env bash\nexit 7\n")

    result = subprocess.run(  # noqa: S603 - fixed test script and executable.
        [_BASH, str(start_script), "--auth-mode", "browser-entra"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 7
    assert "service=console-stack event=started" in result.stdout
    assert "service=console-stack event=ready" not in result.stdout
    assert "service=console-stack event=failed" in result.stderr
    assert "stage=readiness exit_code=7" in result.stderr


def test_duplicate_supervisor_reuses_the_active_analyzer_run_identity(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    start_script = repo / "scripts/deployment/local/start-console-services.sh"
    start_script.parent.mkdir(parents=True)
    shutil.copy2(_START_SCRIPT, start_script)
    (repo / ".fdai/logs").mkdir(parents=True)
    (repo / ".fdai/local-console-auth-mode").write_text(
        "browser-entra\n",
        encoding="utf-8",
    )
    _write_executable(
        repo / "scripts/deployment/local/run-console-service.sh",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "local-analyzer" ]]; then
  printf '%s\n' "$FDAI_ANALYZER_RUN_ID" >> "$FDAI_TEST_ANALYZER_IDS"
fi
exec {service_lock_fd}>> ".fdai/logs/$1.log.lock"
if ! flock -n "$service_lock_fd"; then
  exit 0
fi
exec sleep 30
""",
    )
    _write_executable(
        repo / ".venv/bin/python",
        "#!/usr/bin/env bash\nsleep 0.3\nexit 0\n",
    )
    analyzer_ids = repo / "analyzer-ids.txt"
    environment = {
        **os.environ,
        "FDAI_TEST_ANALYZER_IDS": str(analyzer_ids),
    }
    command = [_BASH, str(start_script), "--auth-mode", "browser-entra"]
    first = subprocess.Popen(  # noqa: S603 - fixed test-owned supervisor
        command,
        cwd=repo,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    second_result: subprocess.CompletedProcess[str] | None = None
    try:
        deadline = time.monotonic() + 3
        while not analyzer_ids.exists():
            assert first.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.02)
        second_result = subprocess.run(  # noqa: S603 - fixed test-owned supervisor
            command,
            cwd=repo,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        while len(analyzer_ids.read_text(encoding="utf-8").splitlines()) < 2:
            assert time.monotonic() < deadline
            time.sleep(0.02)

        run_ids = analyzer_ids.read_text(encoding="utf-8").splitlines()
        assert second_result.returncode == 0
        assert "service=console-stack event=ready" in second_result.stdout
        assert len(run_ids) == 2
        assert run_ids[0] == run_ids[1]
        assert re.fullmatch(r"local-analyzer-\d+-\d+", run_ids[0])
    finally:
        for process in (first,):
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def test_replace_supervisor_waits_for_existing_owner_cleanup(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    start_script = repo / "scripts/deployment/local/start-console-services.sh"
    start_script.parent.mkdir(parents=True)
    shutil.copy2(_START_SCRIPT, start_script)
    (repo / ".fdai/logs").mkdir(parents=True)
    (repo / ".fdai/local-console-auth-mode").write_text(
        "browser-entra\n",
        encoding="utf-8",
    )
    _write_executable(
        repo / "scripts/deployment/local/run-console-service.sh",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "local-analyzer" ]]; then
  printf '%s\n' "$FDAI_ANALYZER_RUN_ID" >> "$FDAI_TEST_ANALYZER_IDS"
fi
exec {service_lock_fd}>> ".fdai/logs/$1.log.lock"
if ! flock -n "$service_lock_fd"; then
  exit 0
fi
exec sleep 30
""",
    )
    _write_executable(
        repo / ".venv/bin/python",
        "#!/usr/bin/env bash\nsleep 0.1\nexit 0\n",
    )
    analyzer_ids = repo / "analyzer-ids.txt"
    first_output_path = repo / "first.out"
    second_output_path = repo / "second.out"
    environment = {
        **os.environ,
        "FDAI_TEST_ANALYZER_IDS": str(analyzer_ids),
    }
    command = [_BASH, str(start_script), "--auth-mode", "browser-entra"]
    first_output = first_output_path.open("w", encoding="utf-8")
    second_output = second_output_path.open("w", encoding="utf-8")
    first = subprocess.Popen(  # noqa: S603 - fixed test-owned supervisor.
        command,
        cwd=repo,
        env=environment,
        stdout=first_output,
        stderr=subprocess.STDOUT,
    )
    second: subprocess.Popen[bytes] | None = None
    try:
        deadline = time.monotonic() + 5
        while "service=console-stack event=ready" not in first_output_path.read_text(
            encoding="utf-8"
        ):
            assert first.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.02)

        second = subprocess.Popen(  # noqa: S603 - fixed test-owned supervisor.
            [*command, "--replace-existing"],
            cwd=repo,
            env=environment,
            stdout=second_output,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 5
        while "service=console-stack event=ready" not in second_output_path.read_text(
            encoding="utf-8"
        ):
            assert second.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.02)

        assert first.wait(timeout=1) == 130
        run_ids = analyzer_ids.read_text(encoding="utf-8").splitlines()
        assert len(run_ids) == 2
        assert run_ids[0] != run_ids[1]
    finally:
        for process in (first, second):
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        first_output.close()
        second_output.close()


@pytest.mark.parametrize("prepared_mode", [None, "unexpected", "azure-cli"])
def test_supervisor_rejects_unprepared_auth_mode(
    tmp_path: Path,
    prepared_mode: str | None,
) -> None:
    repo = tmp_path / "repo"
    start_script = repo / "scripts/deployment/local/start-console-services.sh"
    start_script.parent.mkdir(parents=True)
    shutil.copy2(_START_SCRIPT, start_script)
    (repo / ".fdai/logs").mkdir(parents=True)
    if prepared_mode is not None:
        (repo / ".fdai/local-console-auth-mode").write_text(
            f"{prepared_mode}\n",
            encoding="utf-8",
        )
    _write_executable(
        repo / "scripts/deployment/local/run-console-service.sh",
        "#!/usr/bin/env bash\nprintf 'started\\n' > started.txt\n",
    )

    result = subprocess.run(  # noqa: S603 - fixed test script and executable.
        [_BASH, str(start_script), "--auth-mode", "browser-entra"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 1
    assert "prepared Console auth mode" in result.stderr
    assert "service=console-stack event=starting" not in result.stdout
    assert not (repo / "started.txt").exists()


def test_supervisor_allows_bounded_inventory_recovery() -> None:
    source = _START_SCRIPT.read_text(encoding="utf-8")

    assert "FDAI_CONSOLE_START_READINESS_SECONDS:-180" in source


def test_core_launcher_uses_service_owned_runtime_scope_entrypoint() -> None:
    source = _RUN_SERVICE_SCRIPT.read_text(encoding="utf-8")

    assert '"$repo_root/.venv/bin/fdai-core-control-plane"' in source
    assert '"$repo_root/.venv/bin/python" -m fdai\n' not in source


def test_supervisor_waits_for_the_analyzer_first_clean_tick() -> None:
    source = _START_SCRIPT.read_text(encoding="utf-8")
    service_source = _RUN_SERVICE_SCRIPT.read_text(encoding="utf-8")

    assert '"$service" == "local-analyzer"' in source
    assert '"$service" == "cost-governance-analytics"' in source
    assert "service_args+=(--wait-ready)" in source
    assert 'FDAI_CONSOLE_START_READINESS_SECONDS="$readiness_seconds"' in source
    assert "FDAI_ANALYZER_RUN_ID:-local-analyzer-$(date -u +%s)-$$" in service_source
    assert 'FDAI_ANALYZER_RUN_ID="$local_analyzer_run_id"' in service_source
    assert 'FDAI_STATE_STORE_DSN="$FDAI_STATE_STORE_DSN"' in service_source
    assert "cost-governance-analytics" in source
    assert 'FDAI_COST_STORE_DSN="$FDAI_STATE_STORE_DSN"' in service_source
    assert "collect-cost-governance-analytics.py" in service_source


def test_inventory_stage_reuse_requires_current_checkpoint() -> None:
    source = _PREPARE_SCRIPT.read_text(encoding="utf-8")

    assert "--only inventory-coverage" in source


@pytest.mark.parametrize("auth_mode", ["browser-entra", "azure-cli"])
def test_preparation_reuses_an_unchanged_healthy_stack(
    tmp_path: Path,
    auth_mode: str,
) -> None:
    repo = tmp_path / "repo"
    prepare_script = repo / "scripts/deployment/local/prepare-console-full-stack.sh"
    prepare_script.parent.mkdir(parents=True)
    shutil.copy2(_PREPARE_SCRIPT, prepare_script)
    digest = "a" * 64
    required_outputs = (
        ".venv/bin/fdai-document-channel-intake",
        ".venv/bin/fdai-document-processing-worker",
        ".venv/bin/fdai-isolated-executor-service",
        ".fdai/local-runtime.env",
        ".fdai/local-operator-service.env",
        ".fdai/local-document-ingestion-api.env",
        ".fdai/local-document-processing-worker.env",
        ".fdai/local-isolated-executor.env",
    )
    for relative in required_outputs:
        output = repo / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("prepared\n", encoding="utf-8")
    (repo / ".fdai/local-console-auth-mode").write_text(
        f"{auth_mode}\n",
        encoding="utf-8",
    )
    expected_flag = "1" if auth_mode == "azure-cli" else "0"
    (repo / ".fdai/local-operator-service.env").write_text(
        f"FDAI_OPERATOR_API_LOCAL_AZURE_CLI={expected_flag}\n"
        f"FDAI_OPERATOR_API_LOCAL_AZURE_CLI_CONFIRM={expected_flag}\n",
        encoding="utf-8",
    )
    (repo / "console").mkdir()
    (repo / "console/.env.local").write_text("prepared\n", encoding="utf-8")
    (repo / "console/package.json").write_text("{}\n", encoding="utf-8")
    (repo / "console/package-lock.json").write_text("{}\n", encoding="utf-8")
    _write_executable(repo / "console/node_modules/.bin/vite", "#!/usr/bin/env bash\nexit 0\n")
    _write_ready_dependency_script(repo)
    (repo / "resolved-models.json").write_text("prepared\n", encoding="utf-8")
    _write_executable(repo / "console/node_modules/.bin/opa", "#!/usr/bin/env bash\nexit 0\n")
    mode_digest = hashlib.sha256(
        f"{digest}\nauth-mode={auth_mode}\nresolved-models-override=\n".encode()
    ).hexdigest()
    (repo / ".fdai/console-full-stack-preparation.sha256").write_text(
        f"{mode_digest}\n",
        encoding="utf-8",
    )
    _write_executable(
        repo / ".venv/bin/python",
        f"""#!/usr/bin/env bash
set -euo pipefail
case "$1" in
    */run-bounded-command.py) shift; exec {str(sys.executable)!r} {str(_BOUNDED_RUNNER)!r} "$@" ;;
  */local-service-input-digest.py) printf '%s\\n' {digest!r} ;;
  */developer-workflow.py) exit 0 ;;
    */service-migrations/migrate.py) exit 0 ;;
  *) printf 'unexpected python call: %s\\n' "$1" >&2; exit 99 ;;
esac
""",
    )

    result = subprocess.run(  # noqa: S603 - fixed test script and executable.
        [_BASH, str(prepare_script), "--auth-mode", auth_mode],
        cwd=repo,
        env={**os.environ, "PATH": f"{repo / 'console/node_modules/.bin'}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 0
    assert "service=console-preparation event=reused" in result.stdout
    assert re.fullmatch(
        (
            "service=local-input-digest stage=legacy-preparation "
            r"event=completed duration_ms=\d+\n"
        ),
        result.stderr,
    )


def _staged_preparation_repo(
    tmp_path: Path,
    *,
    stale_stage: str | None = None,
    auth_mode: str = "browser-entra",
) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "repo"
    prepare_script = repo / "scripts/deployment/local/prepare-console-full-stack.sh"
    prepare_script.parent.mkdir(parents=True)
    shutil.copy2(_PREPARE_SCRIPT, prepare_script)
    _write_ready_dependency_script(repo)
    (repo / "console").mkdir()
    (repo / "console/.env.local").write_text(
        "VITE_MSAL_TENANT_ID=tenant\nVITE_MSAL_CLIENT_ID=client\n",
        encoding="utf-8",
    )
    (repo / "console/package.json").write_text("{}\n", encoding="utf-8")
    (repo / "console/package-lock.json").write_text("{}\n", encoding="utf-8")
    _write_executable(repo / "console/node_modules/.bin/vite", "#!/usr/bin/env bash\nexit 0\n")
    for relative in (
        ".venv/bin/fdai-document-channel-intake",
        ".venv/bin/fdai-document-processing-worker",
        ".venv/bin/fdai-isolated-executor-service",
        ".fdai/local-runtime.env",
        ".fdai/local-operator-service.env",
        ".fdai/local-document-ingestion-api.env",
        ".fdai/local-document-processing-worker.env",
        ".fdai/local-isolated-executor.env",
    ):
        output = repo / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("prepared\n", encoding="utf-8")
    expected_flag = "1" if auth_mode == "azure-cli" else "0"
    (repo / ".fdai/local-console-auth-mode").write_text(
        f"{auth_mode}\n",
        encoding="utf-8",
    )
    (repo / ".fdai/local-operator-service.env").write_text(
        f"FDAI_OPERATOR_API_LOCAL_AZURE_CLI={expected_flag}\n"
        f"FDAI_OPERATOR_API_LOCAL_AZURE_CLI_CONFIRM={expected_flag}\n",
        encoding="utf-8",
    )
    _write_executable(
        repo / "scripts/deployment/local/prepare-operator-service-env.sh",
        """#!/usr/bin/env bash
set -euo pipefail
mode="$2"
flag=0
if [[ "$mode" == "azure-cli" ]]; then flag=1; fi
printf '%s\n' "$mode" > .fdai/local-console-auth-mode
printf 'FDAI_OPERATOR_API_LOCAL_AZURE_CLI=%s\n' "$flag" \
  > .fdai/local-operator-service.env
printf 'FDAI_OPERATOR_API_LOCAL_AZURE_CLI_CONFIRM=%s\n' "$flag" \
  >> .fdai/local-operator-service.env
""",
    )
    _write_executable(
        repo / "scripts/deployment/local/prepare-independent-service-envs.sh",
        "#!/usr/bin/env bash\nexit 0\n",
    )
    _write_executable(
        repo / "scripts/deployment/local/prepare-console-state.sh",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--check" ]]; then
  [[ "${FDAI_TEST_LOCAL_STATE_READY:-1}" == "1" ]]
fi
""",
    )
    digest = "c" * 64
    kubernetes_bindings_path = repo / ".fdai/local-kubernetes-bindings.json"
    marker_dir = repo / ".fdai/console-preparation"
    marker_dir.mkdir(parents=True)
    stages = (
        "console-dependencies",
        "local-state",
        "runtime-environment",
        "authoritative-inventory",
        "authoritative-settings",
        "authoritative-catalogs",
        "service-environments",
        "entra-redirects",
    )
    for stage in stages:
        if stage != stale_stage:
            stage_digest = digest
            if stage == "runtime-environment":
                stage_digest = hashlib.sha256(
                    (
                        f"{digest}\nkubernetes=0\n"
                        f"kubernetes-bindings-path={kubernetes_bindings_path}\n"
                        "teams-notifications=0\nno-azure-deployment=0\n"
                        "local-resource-group=\nresolved-models-override=\n"
                    ).encode()
                ).hexdigest()
            if stage == "service-environments":
                stage_digest = hashlib.sha256(
                    f"{digest}\nauth-mode={auth_mode}\n".encode()
                ).hexdigest()
            (marker_dir / f"{stage}.sha256").write_text(
                f"{stage_digest}\n",
                encoding="utf-8",
            )
    _write_executable(
        repo / ".venv/bin/python",
        f"""#!/usr/bin/env bash
set -euo pipefail
case "$1" in
    */run-bounded-command.py) shift; exec {str(sys.executable)!r} {str(_BOUNDED_RUNNER)!r} "$@" ;;
  */local-service-input-digest.py) printf '%s\\n' {digest!r} ;;
  */developer-workflow.py) exit 0 ;;
  */sync-entra-spa-redirect.py) exit 0 ;;
        */ensure-local-models.py)
            if [[ "${{FAIL_MODEL_SETTINGS:-0}}" == "1" ]]; then exit 42; fi
            printf 'prepared\\n' > resolved-models.json; exit 0 ;;
    */service-migrations/migrate.py) exit 0 ;;
  *) printf 'unexpected python call: %s\\n' "$1" >&2; exit 99 ;;
esac
""",
    )
    bin_dir = tmp_path / "bin"
    _write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "volume" && "$2" == "inspect" ]]; then
  printf 'fdai-pgdata 2026-08-23T00:00:00Z\\n'
  printf 'fdai-validation-pgdata 2026-08-23T00:00:00Z\\n'
  exit 0
fi
exit 99
""",
    )
    _write_executable(bin_dir / "terraform", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(bin_dir / "az", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(bin_dir / "npm", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(bin_dir / "opa", "#!/usr/bin/env bash\nexit 0\n")
    return repo, {"PATH": f"{bin_dir}:/usr/bin:/bin"}


def test_authoritative_settings_stage_tracks_runtime_setting_definitions() -> None:
    script = _PREPARE_SCRIPT.read_text(encoding="utf-8")

    assert "services/core-control-plane/src/fdai/delivery/runtime_settings.py" in script


@pytest.mark.parametrize("auth_mode", ["browser-entra", "azure-cli"])
def test_preparation_reuses_each_unchanged_stage_when_stack_is_stopped(
    tmp_path: Path,
    auth_mode: str,
) -> None:
    repo, environment = _staged_preparation_repo(tmp_path, auth_mode=auth_mode)

    result = subprocess.run(  # noqa: S603 - fixed test script and executable.
        [
            _BASH,
            str(repo / "scripts/deployment/local/prepare-console-full-stack.sh"),
            "--auth-mode",
            auth_mode,
        ],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 0
    assert result.stdout.count("event=reused") == 8
    assert "stage=entra-redirects event=completed" not in result.stdout


def test_managed_preparation_defers_stale_inventory_to_reconciliation(
    tmp_path: Path,
) -> None:
    repo, environment = _staged_preparation_repo(
        tmp_path,
        stale_stage="authoritative-inventory",
    )

    result = subprocess.run(  # noqa: S603 - fixed test script and executable.
        [
            _BASH,
            str(repo / "scripts/deployment/local/prepare-console-full-stack.sh"),
            "--defer-authoritative-inventory",
        ],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 0
    assert result.stdout.count("event=reused") == 7
    assert (
        "stage=authoritative-inventory event=deferred owner=inventory-reconciliation"
        in result.stdout
    )


@pytest.mark.parametrize(
    "stale_operator_environment",
    [
        ("FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1\nFDAI_OPERATOR_API_LOCAL_AZURE_CLI_CONFIRM=1\n"),
        ("FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1\nFDAI_OPERATOR_API_LOCAL_AZURE_CLI_CONFIRM=0\n"),
    ],
)
def test_preparation_repairs_auth_outputs_changed_outside_the_cache(
    tmp_path: Path,
    stale_operator_environment: str,
) -> None:
    repo, environment = _staged_preparation_repo(tmp_path)
    (repo / ".fdai/local-operator-service.env").write_text(
        stale_operator_environment,
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603 - fixed test script and executable.
        [_BASH, str(repo / "scripts/deployment/local/prepare-console-full-stack.sh")],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 0
    assert result.stdout.count("stage=service-environments event=completed") == 1
    assert (repo / ".fdai/local-console-auth-mode").read_text(encoding="utf-8") == (
        "browser-entra\n"
    )
    assert "FDAI_OPERATOR_API_LOCAL_AZURE_CLI=0\n" in (
        repo / ".fdai/local-operator-service.env"
    ).read_text(encoding="utf-8")


def test_preparation_reruns_only_the_invalidated_stage(tmp_path: Path) -> None:
    repo, environment = _staged_preparation_repo(tmp_path, stale_stage="entra-redirects")

    result = subprocess.run(  # noqa: S603 - fixed test script and executable.
        [_BASH, str(repo / "scripts/deployment/local/prepare-console-full-stack.sh")],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 0
    assert result.stdout.count("event=reused") == 7
    assert result.stdout.count("stage=entra-redirects event=completed") == 1


def test_preparation_reruns_local_state_when_database_was_recreated(tmp_path: Path) -> None:
    repo, environment = _staged_preparation_repo(tmp_path)
    environment["FDAI_TEST_LOCAL_STATE_READY"] = "0"

    result = subprocess.run(  # noqa: S603 - fixed test script and executable.
        [_BASH, str(repo / "scripts/deployment/local/prepare-console-full-stack.sh")],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 0
    assert result.stdout.count("event=reused") == 7
    assert result.stdout.count("stage=local-state event=completed") == 1


def test_preparation_stops_when_model_settings_cannot_be_generated(tmp_path: Path) -> None:
    repo, environment = _staged_preparation_repo(tmp_path, stale_stage="runtime-environment")
    environment["FAIL_MODEL_SETTINGS"] = "1"
    result = subprocess.run(  # noqa: S603 - fixed test script and executable.
        [_BASH, str(repo / "scripts/deployment/local/prepare-console-full-stack.sh")],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )
    assert result.returncode == 42
    assert "stage=runtime-environment event=completed" not in result.stdout
    assert "service=console-preparation event=completed" not in result.stdout


def test_preparation_reports_a_missing_console_environment(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    prepare_script = repo / "scripts/deployment/local/prepare-console-full-stack.sh"
    prepare_script.parent.mkdir(parents=True)
    shutil.copy2(_PREPARE_SCRIPT, prepare_script)
    _write_executable(repo / ".venv/bin/python", "#!/usr/bin/env bash\nexit 99\n")

    result = subprocess.run(  # noqa: S603 - fixed test script and executable.
        [_BASH, str(prepare_script)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 1
    assert result.stderr == "missing local Console environment: console/.env.local\n"


def test_preparation_loads_existing_read_scope_from_private_console_environment(
    tmp_path: Path,
) -> None:
    repo, environment = _staged_preparation_repo(tmp_path, stale_stage="runtime-environment")
    (repo / "console/.env.local").write_text(
        "VITE_MSAL_TENANT_ID=tenant\n"
        "VITE_MSAL_CLIENT_ID=client\n"
        "FDAI_LOCAL_NO_AZURE_DEPLOYMENT=1\n"
        "FDAI_LOCAL_RESOURCE_GROUP=rg-from-file\n",
        encoding="utf-8",
    )
    _write_executable(
        repo / "scripts/deployment/azure/prepare-local-runtime-env.sh",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s:%s\n' "$FDAI_LOCAL_NO_AZURE_DEPLOYMENT" "$FDAI_LOCAL_RESOURCE_GROUP" \
  > .fdai/captured-read-scope
printf 'prepared\n' > .fdai/local-runtime.env
""",
    )

    result = subprocess.run(  # noqa: S603 - fixed test script and executable.
        [_BASH, str(repo / "scripts/deployment/local/prepare-console-full-stack.sh")],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 0
    assert (repo / ".fdai/captured-read-scope").read_text(encoding="utf-8") == ("1:rg-from-file\n")


def test_preparation_prefers_explicit_read_scope_environment(tmp_path: Path) -> None:
    repo, environment = _staged_preparation_repo(tmp_path, stale_stage="runtime-environment")
    (repo / "console/.env.local").write_text(
        "VITE_MSAL_TENANT_ID=tenant\n"
        "VITE_MSAL_CLIENT_ID=client\n"
        "FDAI_LOCAL_NO_AZURE_DEPLOYMENT=1\n"
        "FDAI_LOCAL_RESOURCE_GROUP=rg-from-file\n",
        encoding="utf-8",
    )
    _write_executable(
        repo / "scripts/deployment/azure/prepare-local-runtime-env.sh",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s:%s\n' "$FDAI_LOCAL_NO_AZURE_DEPLOYMENT" "$FDAI_LOCAL_RESOURCE_GROUP" \
  > .fdai/captured-read-scope
printf 'prepared\n' > .fdai/local-runtime.env
""",
    )

    result = subprocess.run(  # noqa: S603 - fixed test script and executable.
        [_BASH, str(repo / "scripts/deployment/local/prepare-console-full-stack.sh")],
        cwd=repo,
        env={
            **environment,
            "FDAI_LOCAL_NO_AZURE_DEPLOYMENT": "1",
            "FDAI_LOCAL_RESOURCE_GROUP": "rg-from-process",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 0
    assert (repo / ".fdai/captured-read-scope").read_text(encoding="utf-8") == (
        "1:rg-from-process\n"
    )


def test_preparation_repairs_missing_console_dependencies(tmp_path: Path) -> None:
    repo, environment = _staged_preparation_repo(
        tmp_path,
        stale_stage="console-dependencies",
    )
    (repo / "console/node_modules/.bin/vite").unlink()
    (repo / ".venv/bin/fdai-document-processing-worker").unlink()
    (repo / ".venv/bin/fdai-document-channel-intake").unlink()
    (repo / ".venv/bin/fdai-isolated-executor-service").unlink()
    bin_dir = Path(environment["PATH"].split(":", 1)[0])
    _write_executable(
        bin_dir / "uv",
        """#!/usr/bin/env bash
set -euo pipefail
mkdir -p .venv/bin
printf '#!/usr/bin/env bash\nexit 0\n' > .venv/bin/fdai-document-processing-worker
printf '#!/usr/bin/env bash\nexit 0\n' > .venv/bin/fdai-document-channel-intake
printf '#!/usr/bin/env bash\nexit 0\n' > .venv/bin/fdai-isolated-executor-service
chmod +x .venv/bin/fdai-document-channel-intake
chmod +x .venv/bin/fdai-document-processing-worker
chmod +x .venv/bin/fdai-isolated-executor-service
""",
    )
    _write_executable(
        bin_dir / "npm",
        """#!/usr/bin/env bash
set -euo pipefail
mkdir -p console/node_modules/.bin
printf '#!/usr/bin/env bash\nexit 0\n' > console/node_modules/.bin/vite
chmod +x console/node_modules/.bin/vite
""",
    )

    result = subprocess.run(  # noqa: S603 - fixed test script and executable.
        [_BASH, str(repo / "scripts/deployment/local/prepare-console-full-stack.sh")],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 0
    assert result.stdout.count("stage=console-dependencies event=completed") == 1
    assert result.stdout.count("event=reused") == 7
    assert (repo / "console/node_modules/.bin/vite").is_file()
    assert (repo / ".venv/bin/fdai-document-processing-worker").is_file()
    assert (repo / ".venv/bin/fdai-document-channel-intake").is_file()
    assert (repo / ".venv/bin/fdai-isolated-executor-service").is_file()


def test_force_preparation_bypasses_a_healthy_cache(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    prepare_script = repo / "scripts/deployment/local/prepare-console-full-stack.sh"
    prepare_script.parent.mkdir(parents=True)
    shutil.copy2(_PREPARE_SCRIPT, prepare_script)
    (repo / "console").mkdir()
    (repo / "console/.env.local").write_text("prepared\n", encoding="utf-8")
    _write_executable(repo / "console/node_modules/.bin/vite", "#!/usr/bin/env bash\nexit 0\n")
    marker = repo / ".fdai/console-full-stack-preparation.sha256"
    marker.parent.mkdir(parents=True)
    marker.write_text(f"{'0' * 64}\n", encoding="utf-8")
    _write_executable(
        repo / ".venv/bin/python",
        """#!/usr/bin/env bash
if [[ "$1" == */local-service-input-digest.py ]]; then
  printf '%064d\n' 0
  exit 0
fi
exit 99
""",
    )

    result = subprocess.run(  # noqa: S603 - fixed test script and executable.
        [_BASH, str(prepare_script), "--force"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode != 0
    assert "service=console-preparation event=reused" not in result.stdout
    assert not marker.exists()


def _run_dev_up_with_fake_docker(
    tmp_path: Path,
    docker_body: str,
) -> subprocess.CompletedProcess[str]:
    repo = tmp_path / "repo"
    compose_dir = repo / "infra/local"
    compose_dir.mkdir(parents=True)
    (compose_dir / ".env").write_text("prepared\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    _write_executable(
        bin_dir / "git",
        f"""#!/usr/bin/env bash
printf '%s\\n' {str(repo)!r}
""",
    )
    _write_executable(bin_dir / "docker", docker_body)
    environment = {"PATH": f"{bin_dir}:/usr/bin:/bin"}
    return subprocess.run(  # noqa: S603 - fixed test script and executable.
        [_BASH, str(_DEV_UP_SCRIPT)],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )


def test_dev_up_reports_a_missing_compose_plugin(tmp_path: Path) -> None:
    result = _run_dev_up_with_fake_docker(
        tmp_path,
        """#!/usr/bin/env bash
exit 1
""",
    )

    assert result.returncode == 1
    assert "Docker Compose v2 is required" in result.stderr


def test_dev_up_reports_an_unavailable_docker_daemon(tmp_path: Path) -> None:
    result = _run_dev_up_with_fake_docker(
        tmp_path,
        """#!/usr/bin/env bash
if [[ "$*" == "compose version" ]]; then
  exit 0
fi
exit 1
""",
    )

    assert result.returncode == 1
    assert "Docker daemon is unavailable" in result.stderr


def test_dev_up_disables_licensed_redpanda_balancing(tmp_path: Path) -> None:
    result = _run_dev_up_with_fake_docker(
        tmp_path,
        """#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  "compose version"|"info") exit 0 ;;
  "compose up -d --wait") printf 'compose-ready\\n' ;;
  "exec fdai-redpanda rpk cluster config set partition_autobalancing_mode node_add")
    printf 'partition-balancing-disabled\\n'
    ;;
  "exec fdai-redpanda rpk cluster config set core_balancing_continuous false")
    printf 'core-balancing-disabled\\n'
    ;;
  "exec fdai-redpanda rpk cluster config set default_topic_partitions 2")
    printf 'topic-default-set\\n'
    ;;
    "exec fdai-redpanda rpk cluster config set log_retention_ms 86400000") exit 0 ;;
    "exec fdai-redpanda rpk cluster config set retention_bytes 268435456") exit 0 ;;
    "exec fdai-redpanda rpk cluster config set group_offset_retention_sec 86400") exit 0 ;;
    "exec fdai-redpanda rpk cluster config set group_offset_retention_check_ms 60000") exit 0 ;;
  "exec fdai-redpanda rpk topic describe fdai.pantheon.objects --print-partitions")
    printf 'PARTITION LEADER\\n0 0\\n'
    ;;
  "exec fdai-redpanda rpk topic add-partitions fdai.pantheon.objects --num 1")
    printf 'semantic-topic-expanded\\n'
    ;;
    "exec fdai-redpanda rpk topic create fdai.startup.probes "*) exit 0 ;;
    "exec fdai-redpanda rpk topic alter-config fdai.startup.probes "*) exit 0 ;;
  *) printf 'unexpected docker call: %s\\n' "$*" >&2; exit 99 ;;
esac
""",
    )

    assert result.returncode == 0
    assert "partition-balancing-disabled" in result.stdout
    assert "core-balancing-disabled" in result.stdout
    assert "topic-default-set" in result.stdout
    assert "semantic-topic-expanded" in result.stdout
    assert "dev-up: OK" in result.stdout


def test_dev_up_allows_semantic_topic_auto_creation(tmp_path: Path) -> None:
    result = _run_dev_up_with_fake_docker(
        tmp_path,
        """#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  "compose version"|"info"|"compose up -d --wait") exit 0 ;;
  "exec fdai-redpanda rpk cluster config set partition_autobalancing_mode node_add") exit 0 ;;
  "exec fdai-redpanda rpk cluster config set core_balancing_continuous false") exit 0 ;;
  "exec fdai-redpanda rpk cluster config set default_topic_partitions 2") exit 0 ;;
    "exec fdai-redpanda rpk cluster config set log_retention_ms 86400000") exit 0 ;;
    "exec fdai-redpanda rpk cluster config set retention_bytes 268435456") exit 0 ;;
    "exec fdai-redpanda rpk cluster config set group_offset_retention_sec 86400") exit 0 ;;
    "exec fdai-redpanda rpk cluster config set group_offset_retention_check_ms 60000") exit 0 ;;
  "exec fdai-redpanda rpk topic describe fdai.pantheon.objects --print-partitions")
    printf 'PARTITION LEADER\\n'
    ;;
    "exec fdai-redpanda rpk topic create fdai.startup.probes "*) exit 0 ;;
    "exec fdai-redpanda rpk topic alter-config fdai.startup.probes "*) exit 0 ;;
  *) printf 'unexpected docker call: %s\\n' "$*" >&2; exit 99 ;;
esac
""",
    )

    assert result.returncode == 0
    assert "dev-up: OK" in result.stdout


def test_dev_up_preserves_existing_two_partition_semantic_topic(tmp_path: Path) -> None:
    result = _run_dev_up_with_fake_docker(
        tmp_path,
        """#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  "compose version"|"info"|"compose up -d --wait") exit 0 ;;
  "exec fdai-redpanda rpk cluster config set partition_autobalancing_mode node_add") exit 0 ;;
  "exec fdai-redpanda rpk cluster config set core_balancing_continuous false") exit 0 ;;
  "exec fdai-redpanda rpk cluster config set default_topic_partitions 2") exit 0 ;;
    "exec fdai-redpanda rpk cluster config set log_retention_ms 86400000") exit 0 ;;
    "exec fdai-redpanda rpk cluster config set retention_bytes 268435456") exit 0 ;;
    "exec fdai-redpanda rpk cluster config set group_offset_retention_sec 86400") exit 0 ;;
    "exec fdai-redpanda rpk cluster config set group_offset_retention_check_ms 60000") exit 0 ;;
  "exec fdai-redpanda rpk topic describe fdai.pantheon.objects --print-partitions")
    printf 'PARTITION LEADER\\n0 0\\n1 0\\n'
    ;;
    "exec fdai-redpanda rpk topic create fdai.startup.probes "*) exit 0 ;;
    "exec fdai-redpanda rpk topic alter-config fdai.startup.probes "*) exit 0 ;;
  *) printf 'unexpected docker call: %s\\n' "$*" >&2; exit 99 ;;
esac
""",
    )

    assert result.returncode == 0
    assert "dev-up: OK" in result.stdout


def test_dev_up_reports_redpanda_reconciliation_failure(tmp_path: Path) -> None:
    result = _run_dev_up_with_fake_docker(
        tmp_path,
        """#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  "compose version"|"info"|"compose up -d --wait") exit 0 ;;
  "exec fdai-redpanda rpk cluster config set partition_autobalancing_mode node_add") exit 7 ;;
  *) printf 'unexpected docker call: %s\\n' "$*" >&2; exit 99 ;;
esac
""",
    )

    assert result.returncode == 1
    assert result.stderr == "dev-up: failed to disable licensed continuous partition balancing\n"


def test_dev_up_runs_bounded_local_group_cleanup(tmp_path: Path) -> None:
    result = _run_dev_up_with_fake_docker(
        tmp_path,
        """#!/usr/bin/env bash
set -euo pipefail
case "$*" in
    "compose version"|"info"|"compose up -d --wait") exit 0 ;;
    "exec fdai-redpanda rpk cluster config set "*) exit 0 ;;
    "exec fdai-redpanda rpk topic describe fdai.pantheon.objects --print-partitions")
        printf 'PARTITION LEADER\\n0 0\\n1 0\\n'
        ;;
    "context inspect")
        printf '[{"Endpoints":{"docker":{"Host":"unix:///var/run/docker.sock"}}}]\\n'
        ;;
    "exec fdai-redpanda rpk group list") printf 'BROKER GROUP STATE\\n' ;;
    "exec fdai-redpanda rpk topic create fdai.startup.probes "*)
        expected=(exec fdai-redpanda rpk topic create fdai.startup.probes --if-not-exists
            -p 2 -r 1 -c cleanup.policy=delete -c retention.ms=3600000
            -c retention.bytes=1048576 -c segment.ms=600000)
        [[ "$*" == "${expected[*]}" ]]
        printf 'bounded-probe-topic-created\\n' ;;
    "exec fdai-redpanda rpk topic alter-config fdai.startup.probes "*)
        expected=(exec fdai-redpanda rpk topic alter-config fdai.startup.probes
            --set cleanup.policy=delete --set retention.ms=3600000
            --set retention.bytes=1048576 --set segment.ms=600000)
        [[ "$*" == "${expected[*]}" ]]
        printf 'bounded-probe-retention-reconciled\\n' ;;
    *) printf 'unexpected docker call: %s\\n' "$*" >&2; exit 99 ;;
esac
""",
    )

    assert result.returncode == 0
    assert 'local-broker-cleanup: {"candidates": 0, "removed": 0} apply=True' in result.stdout
    assert "bounded-probe-topic-created" in result.stdout
    assert "bounded-probe-retention-reconciled" in result.stdout

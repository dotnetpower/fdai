from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

_BASH = "/usr/bin/bash"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEV_UP_SCRIPT = _REPO_ROOT / "scripts/deployment/local/dev-up.sh"
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


def test_core_runtime_digest_includes_prompt_catalog() -> None:
    script = _RUN_SERVICE_SCRIPT.read_text(encoding="utf-8")

    assert 'if [[ "$service" == "core-runtime" ]]' in script
    assert "digest_inputs+=(rule-catalog/prompts)" in script


def _operator_restart_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    run_script = repo / "scripts/deployment/local/run-console-service.sh"
    run_script.parent.mkdir(parents=True)
    shutil.copy2(_RUN_SERVICE_SCRIPT, run_script)
    (repo / ".fdai").mkdir()
    (repo / ".fdai/local-operator-service.env").write_text("", encoding="utf-8")
    _write_executable(
        repo / "scripts/automation/run-local-service.sh",
        """#!/usr/bin/env bash
status="${FDAI_TEST_RUNNER_STATUS:-0}"
if [[ "$status" != "0" ]]; then
    exit "$status"
fi
sleep "${FDAI_TEST_LAUNCH_DELAY:-0}"
printf '2026-08-26T00:00:00.000000+00:00 service=operator-api event=starting\n'
printf '2026-08-26T00:00:00.000000+00:00 service=operator-api event=reused\n'
printf 'launch\n' >> "$FDAI_TEST_ORDER_FILE"
mkdir -p "$(dirname "$FDAI_LOCAL_SERVICE_LAUNCH_MARKER")"
printf 'reused\n' > "$FDAI_LOCAL_SERVICE_LAUNCH_MARKER"
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
            "FDAI_TEST_LAUNCH_DELAY": str(launch_delay),
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


def test_supervisor_reports_a_service_that_exits_before_readiness(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    start_script = repo / "scripts/deployment/local/start-console-services.sh"
    start_script.parent.mkdir(parents=True)
    shutil.copy2(_START_SCRIPT, start_script)
    (repo / ".fdai/logs").mkdir(parents=True)

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
        [_BASH, str(start_script)],
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
    _write_executable(
        repo / "scripts/deployment/local/run-console-service.sh",
        "#!/usr/bin/env bash\nexec sleep 10\n",
    )
    _write_executable(repo / ".venv/bin/python", "#!/usr/bin/env bash\nexit 7\n")

    result = subprocess.run(  # noqa: S603 - fixed test script and executable.
        [_BASH, str(start_script)],
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


def test_preparation_reuses_an_unchanged_healthy_stack(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    prepare_script = repo / "scripts/deployment/local/prepare-console-full-stack.sh"
    prepare_script.parent.mkdir(parents=True)
    shutil.copy2(_PREPARE_SCRIPT, prepare_script)
    digest = "a" * 64
    required_outputs = (
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
    (repo / "console").mkdir()
    (repo / "console/.env.local").write_text("prepared\n", encoding="utf-8")
    (repo / "console/package.json").write_text("{}\n", encoding="utf-8")
    (repo / "console/package-lock.json").write_text("{}\n", encoding="utf-8")
    _write_executable(repo / "console/node_modules/.bin/vite", "#!/usr/bin/env bash\nexit 0\n")
    _write_ready_dependency_script(repo)
    (repo / ".fdai/console-full-stack-preparation.sha256").write_text(
        f"{digest}\n",
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
        [_BASH, str(prepare_script)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 0
    assert "service=console-preparation event=reused" in result.stdout
    assert result.stderr == ""


def _staged_preparation_repo(
    tmp_path: Path,
    *,
    stale_stage: str | None = None,
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
        ".fdai/local-runtime.env",
        ".fdai/local-operator-service.env",
        ".fdai/local-document-ingestion-api.env",
        ".fdai/local-document-processing-worker.env",
        ".fdai/local-isolated-executor.env",
    ):
        output = repo / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("prepared\n", encoding="utf-8")
    digest = "c" * 64
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
            (marker_dir / f"{stage}.sha256").write_text(f"{digest}\n", encoding="utf-8")
    _write_executable(
        repo / ".venv/bin/python",
        f"""#!/usr/bin/env bash
set -euo pipefail
case "$1" in
    */run-bounded-command.py) shift; exec {str(sys.executable)!r} {str(_BOUNDED_RUNNER)!r} "$@" ;;
  */local-service-input-digest.py) printf '%s\\n' {digest!r} ;;
  */sync-entra-spa-redirect.py) exit 0 ;;
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
    return repo, {"PATH": f"{bin_dir}:/usr/bin:/bin"}


def test_preparation_reuses_each_unchanged_stage_when_stack_is_stopped(tmp_path: Path) -> None:
    repo, environment = _staged_preparation_repo(tmp_path)

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
    assert result.stdout.count("event=reused") == 8
    assert "stage=entra-redirects event=completed" not in result.stdout


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


def test_preparation_repairs_missing_console_dependencies(tmp_path: Path) -> None:
    repo, environment = _staged_preparation_repo(
        tmp_path,
        stale_stage="console-dependencies",
    )
    (repo / "console/node_modules/.bin/vite").unlink()
    bin_dir = Path(environment["PATH"].split(":", 1)[0])
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

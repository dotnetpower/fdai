from __future__ import annotations

import fcntl
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_BASH = "/usr/bin/bash"
_GIT = shutil.which("git")
if _GIT is None:
    raise RuntimeError("git is required for local web server launcher tests")
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONSOLE_WEB_SCRIPT = _REPO_ROOT / "scripts/deployment/local/start-console-web.sh"
_DESIGN_MOCKS_SCRIPT = _REPO_ROOT / "scripts/deployment/local/start-design-mocks.sh"


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _console_launcher_repo(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    repo = tmp_path / "repo"
    launcher = repo / "scripts/deployment/local/start-console-web.sh"
    launcher.parent.mkdir(parents=True)
    shutil.copy2(_CONSOLE_WEB_SCRIPT, launcher)
    subprocess.run(  # noqa: S603 - resolved Git creates a test-owned repository.
        [_GIT, "init", "--quiet", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _write_executable(
        repo / "scripts/deployment/local/prepare-console-full-stack.sh",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'prepare:%s:teams=%s\n' \
  "$*" \
  "${FDAI_LOCAL_TEAMS_NOTIFICATION_ACTIVATION:-}" >> "$FDAI_TEST_LOG"
""",
    )
    _write_executable(
        repo / "scripts/deployment/local/start-console-services.sh",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'start:%s\n' "$*" >> "$FDAI_TEST_LOG"
""",
    )
    fake_bin = tmp_path / "bin"
    _write_executable(
        fake_bin / "python3",
        """#!/usr/bin/env bash
set -euo pipefail
cat >/dev/null
if [[ "${FDAI_TEST_OCCUPIED_PORT:-}" == "${2:-}" ]]; then
  exit 0
fi
exit 1
""",
    )
    return (
        repo,
        launcher,
        {
            **os.environ,
            "PATH": f"{fake_bin}:/usr/bin:/bin",
        },
    )


@pytest.mark.parametrize(
    ("arguments", "expected_prepare"),
    [
        ([], "prepare:--auth-mode browser-entra:teams=1"),
        (["--force"], "prepare:--force --auth-mode browser-entra:teams=1"),
        (
            ["--auth-mode", "azure-cli"],
            "prepare:--auth-mode azure-cli:teams=1",
        ),
        (
            ["--auth-mode", "azure-cli", "--force"],
            "prepare:--force --auth-mode azure-cli:teams=1",
        ),
    ],
)
def test_console_web_launcher_prepares_then_starts_full_stack(
    tmp_path: Path,
    arguments: list[str],
    expected_prepare: str,
) -> None:
    repo, launcher, environment = _console_launcher_repo(tmp_path)
    log_path = repo / "launcher.log"
    environment["FDAI_TEST_LOG"] = str(log_path)

    result = subprocess.run(  # noqa: S603 - fixed Bash runs a test-owned script.
        [_BASH, str(launcher), *arguments],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 0
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        expected_prepare,
        f"start:--auth-mode {'azure-cli' if 'azure-cli' in arguments else 'browser-entra'}",
    ]
    assert result.stderr == ""


def test_console_web_launcher_rejects_unknown_arguments(tmp_path: Path) -> None:
    _, launcher, environment = _console_launcher_repo(tmp_path)

    result = subprocess.run(  # noqa: S603 - fixed Bash runs a test-owned script.
        [_BASH, str(launcher), "--unknown"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 2
    assert result.stderr.startswith("Usage: ")


def test_console_web_launcher_rejects_linked_worktree(tmp_path: Path) -> None:
    repo, launcher, environment = _console_launcher_repo(tmp_path)
    fake_bin = tmp_path / "bin"
    _write_executable(
        fake_bin / "git",
        f"""#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  "rev-parse --path-format=absolute --git-dir")
    printf '%s\n' {str(repo / ".git/worktrees/session")!r}
    ;;
  "rev-parse --path-format=absolute --git-common-dir")
    printf '%s\n' {str(repo / ".git")!r}
    ;;
  *)
    exit 99
    ;;
esac
""",
    )

    result = subprocess.run(  # noqa: S603 - fixed Bash runs a test-owned script.
        [_BASH, str(launcher)],
        cwd=tmp_path,
        env={
            **environment,
            "FDAI_TEST_LOG": str(repo / "launcher.log"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 75
    assert "available only from the primary checkout" in result.stderr
    assert not (repo / "launcher.log").exists()


def test_console_web_launcher_rejects_unmanaged_service_port(tmp_path: Path) -> None:
    repo, launcher, environment = _console_launcher_repo(tmp_path)
    environment["FDAI_TEST_LOG"] = str(repo / "launcher.log")
    environment["FDAI_TEST_OCCUPIED_PORT"] = "8011"

    result = subprocess.run(  # noqa: S603 - fixed Bash runs a test-owned script.
        [_BASH, str(launcher)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 75
    assert "services outside the managed launcher" in result.stderr
    assert "document-ingestion-api (port=127.0.0.1:8011)" in result.stderr
    assert not (repo / "launcher.log").exists()


def test_console_web_launcher_allows_managed_service_port(tmp_path: Path) -> None:
    repo, launcher, environment = _console_launcher_repo(tmp_path)
    log_path = repo / "launcher.log"
    environment["FDAI_TEST_LOG"] = str(log_path)
    environment["FDAI_TEST_OCCUPIED_PORT"] = "8011"
    lock_path = repo / ".fdai/logs/document-ingestion-api.log.lock"
    lock_path.parent.mkdir(parents=True)

    with lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(  # noqa: S603 - fixed Bash runs a test-owned script.
            [_BASH, str(launcher)],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )

    assert result.returncode == 0
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        "prepare:--auth-mode browser-entra:teams=1",
        "start:--auth-mode browser-entra",
    ]
    assert result.stderr == ""


def test_design_mocks_launcher_serves_repository_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    launcher = repo / "scripts/deployment/local/start-design-mocks.sh"
    launcher.parent.mkdir(parents=True)
    shutil.copy2(_DESIGN_MOCKS_SCRIPT, launcher)
    log_path = repo / "launcher.log"
    fake_bin = tmp_path / "bin"
    _write_executable(
        fake_bin / "python3",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'cwd=%s\n' "$PWD" > "$FDAI_TEST_LOG"
printf 'args=%s\n' "$*" >> "$FDAI_TEST_LOG"
""",
    )

    result = subprocess.run(  # noqa: S603 - fixed Bash runs a test-owned script.
        [_BASH, str(launcher)],
        cwd=tmp_path,
        env={
            **os.environ,
            "FDAI_TEST_LOG": str(log_path),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 0
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        f"cwd={repo}",
        "args=-u -m http.server 5373 --bind 127.0.0.1",
    ]
    assert result.stderr == ""


def test_design_mocks_launcher_rejects_arguments(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    launcher = repo / "scripts/deployment/local/start-design-mocks.sh"
    launcher.parent.mkdir(parents=True)
    shutil.copy2(_DESIGN_MOCKS_SCRIPT, launcher)

    result = subprocess.run(  # noqa: S603 - fixed Bash runs a test-owned script.
        [_BASH, str(launcher), "--unknown"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )

    assert result.returncode == 2
    assert result.stderr.startswith("Usage: ")


def test_local_web_server_launchers_are_executable() -> None:
    assert os.access(_CONSOLE_WEB_SCRIPT, os.X_OK)
    assert os.access(_DESIGN_MOCKS_SCRIPT, os.X_OK)

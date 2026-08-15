#!/usr/bin/env python3
"""Install or remove the roadmap verification user-systemd timer."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

_UNIT = "fdai-roadmap-verification"
_GIT = shutil.which("git") or "/usr/bin/git"
_SYSTEMCTL = shutil.which("systemctl") or "/usr/bin/systemctl"
_DEFAULT_BRANCH = "roadmap-verification/campaign"


def _quote(value: Path) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _project_root(raw: str | None) -> Path:
    base = Path(raw).resolve() if raw else Path.cwd()
    result = subprocess.run(  # noqa: S603 - fixed git executable and arguments
        [_GIT, "-C", str(base), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return Path(result.stdout.strip())


def _unit_text(project: Path, *, apply: bool) -> tuple[str, str]:
    if not project.is_absolute() or any(character.isspace() for character in str(project)):
        raise ValueError("systemd WorkingDirectory must be an absolute path without whitespace")
    runner = project / "scripts/automation/roadmap_verification_watchdog.py"
    apply_argument = " --apply --integrate" if apply else ""
    service = f"""[Unit]
Description=FDAI roadmap implementation verification cycle

[Service]
Type=oneshot
WorkingDirectory={project}
ExecStart={_quote(Path(sys.executable))} {_quote(runner)}{apply_argument}
Nice=10
IOSchedulingClass=idle
CPUWeight=20
TimeoutStartSec=1h
"""
    timer = f"""[Unit]
Description=Resume FDAI roadmap verification while interactive sessions are idle

[Timer]
OnBootSec=15min
OnUnitInactiveSec=20min
RandomizedDelaySec=3min
Persistent=true
Unit={_UNIT}.service

[Install]
WantedBy=timers.target
"""
    return service, timer


def _campaign_path(project: Path, configured: str | None) -> Path:
    if configured:
        return Path(configured).expanduser().resolve()
    return project.parent / f"{project.name}-roadmap-campaign"


def _link_local_dependencies(project: Path, campaign: Path) -> None:
    for relative in (
        Path(".improve"),
        Path(".venv"),
        Path("resolved-models.json"),
        Path("console/node_modules"),
        Path("cli/node_modules"),
    ):
        source = project / relative
        destination = campaign / relative
        if not source.exists() or destination.exists() or destination.is_symlink():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(source.resolve(), target_is_directory=source.is_dir())


def _git_common_dir(worktree: Path) -> Path:
    result = subprocess.run(  # noqa: S603 - fixed git executable and arguments
        [_GIT, "-C", str(worktree), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    raw = Path(result.stdout.strip())
    return raw.resolve() if raw.is_absolute() else (worktree / raw).resolve()


def _prepare_campaign_worktree(project: Path, campaign: Path, branch: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch) or branch.startswith("-") or ".." in branch:
        raise ValueError("campaign branch contains unsupported characters")
    if campaign.exists():
        result = subprocess.run(  # noqa: S603 - fixed git executable and arguments
            [_GIT, "-C", str(campaign), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or Path(result.stdout.strip()).resolve() != campaign.resolve():
            raise RuntimeError("campaign path exists but is not the expected git worktree")
        if _git_common_dir(project) != _git_common_dir(campaign):
            raise RuntimeError("campaign worktree belongs to another repository")
        current_branch = subprocess.run(  # noqa: S603 - fixed git executable and arguments
            [_GIT, "-C", str(campaign), "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if current_branch != branch:
            raise RuntimeError("campaign worktree has an unexpected branch")
        _link_local_dependencies(project, campaign)
        return campaign

    branch_exists = (
        subprocess.run(  # noqa: S603 - fixed git executable and validated ref
            [_GIT, "-C", str(project), "show-ref", "--verify", f"refs/heads/{branch}"],
            check=False,
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )
    arguments = [_GIT, "-C", str(project), "worktree", "add", "--quiet"]
    if branch_exists:
        arguments.extend([str(campaign), branch])
    else:
        arguments.extend(["-b", branch, str(campaign), "HEAD"])
    subprocess.run(arguments, check=True)  # noqa: S603 - fixed git executable and validated ref
    _link_local_dependencies(project, campaign)
    return campaign


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "remove", "preview"))
    parser.add_argument("--project")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--campaign-path")
    parser.add_argument("--campaign-branch", default=_DEFAULT_BRANCH)
    arguments = parser.parse_args(argv)
    project = _project_root(arguments.project)
    campaign = _campaign_path(project, arguments.campaign_path)
    service, timer = _unit_text(campaign, apply=arguments.apply)
    if arguments.command == "preview":
        print(service)
        print(timer)
        return 0

    unit_dir = Path.home() / ".config/systemd/user"
    service_path = unit_dir / f"{_UNIT}.service"
    timer_path = unit_dir / f"{_UNIT}.timer"
    if arguments.command == "remove":
        subprocess.run(  # noqa: S603 - fixed systemctl executable and unit
            [_SYSTEMCTL, "--user", "disable", "--now", f"{_UNIT}.timer"],
            check=False,
        )
        service_path.unlink(missing_ok=True)
        timer_path.unlink(missing_ok=True)
        subprocess.run(
            [_SYSTEMCTL, "--user", "daemon-reload"],
            check=True,  # noqa: S603
        )
        return 0

    _prepare_campaign_worktree(project, campaign, arguments.campaign_branch)
    unit_dir.mkdir(parents=True, exist_ok=True)
    service_path.write_text(service, encoding="utf-8")
    timer_path.write_text(timer, encoding="utf-8")
    subprocess.run([_SYSTEMCTL, "--user", "daemon-reload"], check=True)  # noqa: S603
    subprocess.run(  # noqa: S603 - fixed systemctl executable and unit
        [_SYSTEMCTL, "--user", "enable", "--now", f"{_UNIT}.timer"],
        check=True,
    )
    print(f"installed {_UNIT}.timer ({'apply' if arguments.apply else 'report'} mode)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Manage the explicit roadmap implementation campaign and its timer cycle."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from install_roadmap_verification_timer import _prepare_campaign_worktree, _project_root, _quote

UNIT = "fdai-roadmap-implementation-campaign"
DEFAULT_BRANCH = "roadmap-implementation/campaign"
SYSTEMCTL = shutil.which("systemctl") or "/usr/bin/systemctl"


def _campaign_path(project: Path, configured: str | None) -> Path:
    if configured:
        return Path(configured).expanduser().resolve()
    return project.parent / f"{project.name}-roadmap-implementation-campaign"


def _unit_text(project: Path, campaign: Path, branch: str) -> tuple[str, str]:
    if any(
        not path.is_absolute() or any(character.isspace() for character in str(path))
        for path in (project, campaign)
    ):
        raise ValueError("systemd paths must be absolute and contain no whitespace")
    runner = project / "scripts/automation/install_roadmap_implementation_campaign.py"
    exec_start = " ".join(
        (
            _quote(Path(sys.executable)),
            _quote(runner),
            "run-cycle",
            "--project",
            _quote(project),
            "--campaign-path",
            _quote(campaign),
            "--campaign-branch",
            _quote(Path(branch)),
        )
    )
    service = f"""[Unit]
Description=FDAI randomized roadmap implementation campaign

[Service]
Type=oneshot
WorkingDirectory={project}
ExecStart={exec_start}
Nice=10
IOSchedulingClass=idle
CPUWeight=20
TimeoutStartSec=2h
"""
    timer = f"""[Unit]
Description=Repeat FDAI roadmap implementation while session capacity is available

[Timer]
OnBootSec=5min
OnUnitInactiveSec=5min
RandomizedDelaySec=2min
Persistent=true
Unit={UNIT}.service

[Install]
WantedBy=timers.target
"""
    return service, timer


def _unit_paths() -> tuple[Path, Path]:
    unit_dir = Path.home() / ".config/systemd/user"
    return unit_dir / f"{UNIT}.service", unit_dir / f"{UNIT}.timer"


def _write_units(service: str, timer: str) -> None:
    service_path, timer_path = _unit_paths()
    service_path.parent.mkdir(parents=True, exist_ok=True)
    service_path.write_text(service, encoding="utf-8")
    timer_path.write_text(timer, encoding="utf-8")
    subprocess.run([SYSTEMCTL, "--user", "daemon-reload"], check=True)  # noqa: S603


def _stop() -> None:
    subprocess.run(  # noqa: S603 - fixed systemctl executable and unit
        [SYSTEMCTL, "--user", "disable", "--now", f"{UNIT}.timer"],
        check=False,
    )


def _status(campaign: Path) -> str:
    states: list[str] = []
    for label, command in (("enabled", "is-enabled"), ("active", "is-active")):
        result = subprocess.run(  # noqa: S603 - fixed systemctl executable and unit
            [SYSTEMCTL, "--user", command, f"{UNIT}.timer"],
            check=False,
            capture_output=True,
            text=True,
        )
        states.append(f"{label}={(result.stdout.strip() or 'unknown')}")
    states.append(f"worktree={'present' if campaign.is_dir() else 'missing'}")
    return ", ".join(states)


def _run_campaign_cycle(project: Path, campaign: Path, branch: str) -> int:
    worktree = _prepare_campaign_worktree(project, campaign, branch)
    runner = worktree / "scripts/automation/roadmap_implementation_campaign.py"
    result = subprocess.run(  # noqa: S603 - repository-owned runner in validated worktree.
        [sys.executable, str(runner), "--max-active-sessions", "2"],
        cwd=worktree,
        check=False,
    )
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("start", "status", "stop", "remove", "preview", "run-cycle"),
    )
    parser.add_argument("--project")
    parser.add_argument("--campaign-path")
    parser.add_argument("--campaign-branch", default=DEFAULT_BRANCH)
    arguments = parser.parse_args(argv)

    project = _project_root(arguments.project)
    campaign = _campaign_path(project, arguments.campaign_path)

    if arguments.command == "status":
        print(f"{UNIT}.timer: {_status(campaign)}")
        return 0
    if arguments.command == "stop":
        _stop()
        print(f"stopped {UNIT}.timer; campaign state is preserved")
        return 0
    if arguments.command == "remove":
        _stop()
        for path in _unit_paths():
            path.unlink(missing_ok=True)
        subprocess.run([SYSTEMCTL, "--user", "daemon-reload"], check=True)  # noqa: S603
        print(f"removed {UNIT} units; campaign worktree and state are preserved")
        return 0
    if arguments.command == "run-cycle":
        return _run_campaign_cycle(project, campaign, arguments.campaign_branch)

    service, timer = _unit_text(project, campaign, arguments.campaign_branch)
    if arguments.command == "preview":
        print(service)
        print(timer)
        return 0

    _prepare_campaign_worktree(project, campaign, arguments.campaign_branch)
    _write_units(service, timer)
    subprocess.run(  # noqa: S603 - fixed systemctl executable and unit
        [SYSTEMCTL, "--user", "enable", "--now", f"{UNIT}.timer"],
        check=True,
    )
    print(f"started {UNIT}.timer with automatic registered-issue discovery")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Start, stop, or remove the explicit roadmap implementation campaign."""

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


def _unit_text(campaign: Path) -> tuple[str, str]:
    if not campaign.is_absolute() or any(character.isspace() for character in str(campaign)):
        raise ValueError("systemd WorkingDirectory must be an absolute path without whitespace")
    runner = campaign / "scripts/automation/roadmap_implementation_campaign.py"
    service = f"""[Unit]
Description=FDAI randomized roadmap implementation campaign

[Service]
Type=oneshot
WorkingDirectory={campaign}
ExecStart={_quote(Path(sys.executable))} {_quote(runner)} --max-active-sessions 2
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


def _status() -> str:
    states: list[str] = []
    for label, command in (("enabled", "is-enabled"), ("active", "is-active")):
        result = subprocess.run(  # noqa: S603 - fixed systemctl executable and unit
            [SYSTEMCTL, "--user", command, f"{UNIT}.timer"],
            check=False,
            capture_output=True,
            text=True,
        )
        states.append(f"{label}={(result.stdout.strip() or 'unknown')}")
    return ", ".join(states)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "status", "stop", "remove", "preview"))
    parser.add_argument("--project")
    parser.add_argument("--campaign-path")
    parser.add_argument("--campaign-branch", default=DEFAULT_BRANCH)
    arguments = parser.parse_args(argv)

    project = _project_root(arguments.project)
    campaign = _campaign_path(project, arguments.campaign_path)

    if arguments.command == "status":
        print(f"{UNIT}.timer: {_status()}")
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

    service, timer = _unit_text(campaign)
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

"""Private-runner Foundation transition transport regressions."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_foundation_transition as transition  # noqa: E402
from fdai_deployment_cli.private_output import write_private_bytes  # noqa: E402


class TransitionTunnel:
    def __init__(self, home: Path, username: str = "runner") -> None:
        self.home = home
        self.username = username
        self.operations: list[str] = []
        self.copied_to: list[str] = []

    def _path(self, remote: str) -> Path:
        prefix = f"/home/{self.username}/"
        assert remote.startswith(prefix)
        return self.home / remote.removeprefix(prefix)

    def ssh(
        self, command: tuple[str, ...], *, timeout: int, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        del timeout, input_text
        if command[0] == "/usr/bin/sha256sum":
            path = self._path(command[1])
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            return subprocess.CompletedProcess(command, 0, f"{digest}  {command[1]}\n", "")
        if command[0] == "/usr/bin/rm":
            self._path(command[-1]).unlink(missing_ok=True)
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ("/usr/bin/python3", command[1]):
            mode = command[2]
            work_id = command[command.index("--work-id") + 1]
            work = self.home / ".fdai-foundation-transition" / work_id[:24]
            work.mkdir(mode=0o700, parents=True, exist_ok=True)
            if mode == "plan":
                self.operations.append("plan")
                _write_remote_plan(work, zero=False)
                marker = f"foundation_transition_plan_complete work_ref={work_id[:24]}"
                return subprocess.CompletedProcess(command, 0, marker + "\n", "")
            if mode == "apply":
                self.operations.append("apply")
                _write_remote_plan(work, zero=True, observation="apply-observation.json")
                marker = f"foundation_transition_verified work_ref={work_id[:24]}"
                return subprocess.CompletedProcess(command, 0, marker + "\n", "")
            if mode == "verify":
                self.operations.append("verify")
                _write_remote_plan(work, zero=True, observation="apply-observation.json")
                marker = f"foundation_transition_verified work_ref={work_id[:24]}"
                return subprocess.CompletedProcess(command, 0, marker + "\n", "")
        raise AssertionError(f"unexpected ssh command: {command}")

    def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
        del timeout
        target = self._path(destination)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o600)
        self.copied_to.append(destination)

    def copy_from(self, source: str, destination: Path, *, timeout: int) -> None:
        del timeout
        shutil.copyfile(self._path(source), destination)
        destination.chmod(0o600)


def _write_remote_plan(
    work: Path, *, zero: bool, observation: str = "plan-observation.json"
) -> None:
    plan = {
        "format_version": "1.2",
        "resource_changes": [
            {
                "address": "azurerm_role_assignment.bootstrap",
                "type": "azurerm_role_assignment",
                "change": {"actions": ["no-op"] if zero else ["update"]},
            }
        ],
    }
    plan_name = "remote-zero-plan.json" if zero else "remote-plan.json"
    (work / plan_name).write_text(json.dumps(plan), encoding="utf-8")
    state_digest = "1" * 64
    plan_json_digest = hashlib.sha256((work / plan_name).read_bytes()).hexdigest()
    value = {
        "schema_version": "fdai.genesis-foundation-transition-observation.v1",
        "state": "verified",
        "work_id": "c" * 64,
        "archive_digest": "a" * 64,
        "helper_digest": "b" * 64,
        "remote_state_digest": state_digest,
        "plan_json_digest": plan_json_digest,
        "plan_digest": "d" * 64,
        "zero_change_verified": zero,
        "mutation_performed": observation == "apply-observation.json",
        "subscription_ready": False,
    }
    (work / observation).write_text(json.dumps(value), encoding="utf-8")


def _kwargs(tmp_path: Path, tunnel: TransitionTunnel) -> dict[str, object]:
    retained = tmp_path / "retained"
    transition_dir = tmp_path / "transition"
    retained.mkdir(mode=0o700)
    transition_dir.mkdir(mode=0o700)
    archive = transition_dir / "foundation-transition-cccccccccccc.tar.gz"
    write_private_bytes(archive, b"archive")
    helper = b"print('helper')\n"
    return {
        "args": argparse.Namespace(timeout_seconds=900),
        "retained": retained,
        "transition": transition_dir,
        "connection": {
            "username": tunnel.username,
            "vm_id": "vm-id",
            "resource_group": "rg",
            "bastion_name": "bas",
        },
        "handoff": {"subscription_id": "sub", "tenant_id": "ten"},
        "state": {
            "account_id": "id",
            "account_name": "acct",
            "container_name": "tfstate",
            "foundation_key": "key",
        },
        "runner": {"client_id": "client", "principal_id": "principal"},
        "ops": {"resource_group_name": "rg"},
        "private_key": tmp_path / "key",
        "known_hosts": tmp_path / "known-hosts",
        "work_id": "c" * 64,
        "archive_digest": hashlib.sha256(b"archive").hexdigest(),
        "helper": helper,
        "helper_digest": hashlib.sha256(helper).hexdigest(),
        "expected_plan_digest": "d" * 64,
    }


def test_remote_plan_ships_helper_and_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    tunnel = TransitionTunnel(tmp_path / "remote")
    monkeypatch.setattr(transition, "BastionTunnel", lambda **_kwargs: _TunnelContext(tunnel))

    result = transition._run_remote("plan", **_kwargs(tmp_path, tunnel))  # noqa: SLF001

    assert tunnel.operations == ["plan"]
    assert any(item.endswith(".py") for item in tunnel.copied_to)
    assert any(item.endswith(".tar.gz") for item in tunnel.copied_to)
    assert result["observation"]["zero_change_verified"] is False


def test_remote_apply_uses_saved_plan_after_local_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    tunnel = TransitionTunnel(tmp_path / "remote")
    monkeypatch.setattr(transition, "BastionTunnel", lambda **_kwargs: _TunnelContext(tunnel))

    result = transition._run_remote("apply", **_kwargs(tmp_path, tunnel))  # noqa: SLF001

    assert tunnel.operations == ["apply"]
    assert result["observation"]["zero_change_verified"] is True
    assert result["observation"]["mutation_performed"] is True


def test_remote_verify_never_applies_after_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    tunnel = TransitionTunnel(tmp_path / "remote")
    monkeypatch.setattr(transition, "BastionTunnel", lambda **_kwargs: _TunnelContext(tunnel))

    result = transition._run_remote("verify", **_kwargs(tmp_path, tunnel))  # noqa: SLF001

    assert tunnel.operations == ["verify"]
    assert "apply" not in tunnel.operations
    assert result["observation"]["zero_change_verified"] is True


class _TunnelContext:
    def __init__(self, tunnel: TransitionTunnel) -> None:
        self.tunnel = tunnel

    def __enter__(self) -> TransitionTunnel:
        return self.tunnel

    def __exit__(self, *_args: object) -> None:
        return None

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fdai_lifecycle_hub import cli, setup_start


def test_start_command_does_not_open_hub_store(tmp_path, monkeypatch):
    observed = []
    monkeypatch.delenv("FDAI_HUB_REMOTE_CONFIG", raising=False)
    monkeypatch.delenv(cli.DATABASE_URL_ENV, raising=False)
    monkeypatch.setattr(setup_start, "start", lambda args: observed.append(args) or 0)
    assert cli.main(["start", "--state-dir", str(tmp_path), "--no-browser"]) == 0
    assert observed[0].state_dir == tmp_path
    assert observed[0].port == 0
    assert observed[0].no_browser


def test_start_reports_local_io_failure_without_private_details(monkeypatch, capsys):
    def unavailable(args):
        raise OSError("private diagnostic detail")

    monkeypatch.delenv("FDAI_HUB_REMOTE_CONFIG", raising=False)
    monkeypatch.setattr(setup_start, "start", unavailable)
    assert cli.main(["start"]) == 1
    diagnostic = capsys.readouterr().err
    assert "private directory access" in diagnostic
    assert "private diagnostic detail" not in diagnostic


def test_launcher_serializes_same_installation_and_recovers_after_exit(tmp_path: Path):
    root = tmp_path / "private"
    with setup_start.launcher_lock(root):
        with pytest.raises(ValueError, match="already running"):
            with setup_start.launcher_lock(root):
                pytest.fail("A second launcher acquired the active lock.")
    with setup_start.launcher_lock(root):
        assert root.stat().st_mode & 0o777 == 0o700


def test_start_rejects_remote_profile_and_invalid_port(tmp_path, monkeypatch):
    args = cli._parser().parse_args(["start", "--state-dir", str(tmp_path)])
    monkeypatch.setenv("FDAI_HUB_REMOTE_CONFIG", "bound-remote-profile")
    with pytest.raises(ValueError, match="customer-local"):
        setup_start.start(args)
    monkeypatch.delenv("FDAI_HUB_REMOTE_CONFIG")
    args.port = -1
    with pytest.raises(ValueError, match="port"):
        setup_start.start(args)


@pytest.mark.parametrize("timeout", [False, True])
def test_shutdown_stops_only_owned_process_group_including_children(monkeypatch, timeout):
    sent = []

    class Worker:
        pid = 12345

        def wait(self, *, timeout):
            if not sent[-1][1] == signal.SIGKILL and timeout == 10 and should_timeout:
                raise subprocess.TimeoutExpired("synthetic-worker", timeout)
            return 0

    should_timeout = timeout
    monkeypatch.setattr(setup_start.os, "killpg", lambda pid, sig: sent.append((pid, sig)))
    setup_start._stop_worker(Worker())
    assert sent == [(12345, signal.SIGTERM), (12345, signal.SIGKILL)]


def test_worker_start_requires_its_fresh_heartbeat(tmp_path, monkeypatch):
    class Worker:
        pid = 12345

        def poll(self):
            return None

    heartbeat = tmp_path / "heartbeat.json"
    heartbeat.write_text(json.dumps({"pid": 12345}))
    setup_start._worker_ready(Worker(), tmp_path, started_ns=heartbeat.stat().st_mtime_ns)
    ticks = iter([0.0, 0.1, 16.0])
    monkeypatch.setattr(setup_start.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(setup_start.time, "sleep", lambda delay: None)
    with pytest.raises(ValueError, match="startup deadline"):
        setup_start._worker_ready(Worker(), tmp_path, started_ns=time.time_ns() + 10**9)


def test_dead_worker_does_not_count_as_startup_ready(tmp_path):
    class Worker:
        pid = 12345

        def poll(self):
            return 1

    with pytest.raises(ValueError, match="executor stopped"):
        setup_start._worker_ready(Worker(), tmp_path, started_ns=0)


def test_sigterm_reaps_the_actual_executor_before_launcher_exits(tmp_path):
    root = Path(__file__).resolve().parents[3]
    state = tmp_path / "setup"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"FDAI_HUB_REMOTE_CONFIG", "FDAI_LIFECYCLE_HUB_DATABASE_URL"}
    }
    environment["PYTHONPATH"] = os.pathsep.join(
        str(root / path)
        for path in (
            "lifecycle/hub/src",
            "packages/deployment-cli/src",
            "packages/service-contracts/src",
        )
    )
    process = subprocess.Popen(  # noqa: S603 - fixed Python entrypoint and isolated test state
        [
            sys.executable,
            "-c",
            "from fdai_lifecycle_hub.cli import main; import sys; sys.exit(main(sys.argv[1:]))",
            "start",
            "--state-dir",
            str(state),
            "--no-browser",
        ],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    worker_pid = None
    try:
        assert process.stdout is not None
        readable, _, _ = select.select([process.stdout], [], [], 20)
        assert readable, "Bootstrap startup exceeded its deadline."
        startup = process.stdout.readline()
        if not startup.startswith(b"Lifecycle Hub Bootstrap: http://127.0.0.1:"):
            _, diagnostic = process.communicate(timeout=5)
            pytest.fail(
                "Bootstrap exited before readiness: " + diagnostic.decode(errors="replace")[-2000:]
            )
        worker_pid = json.loads((state / "heartbeat.json").read_bytes())["pid"]
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=15) == 0
        with pytest.raises(ProcessLookupError):
            os.kill(worker_pid, 0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if worker_pid is not None:
            setup_start._signal_worker_group(worker_pid, signal.SIGKILL)


def test_status_and_stop_subcommands_operate_without_database(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("FDAI_HUB_REMOTE_CONFIG", raising=False)
    monkeypatch.delenv(cli.DATABASE_URL_ENV, raising=False)
    assert cli.main(["status", "--state-dir", str(tmp_path)]) == 0
    status_out = json.loads(capsys.readouterr().out)
    assert status_out["phase"] == "idle"
    (tmp_path / "launch.url").write_text("http://127.0.0.1:8000/setup#session=tok")
    (tmp_path / "session.cookie").write_text("cookie")
    assert cli.main(["stop", "--state-dir", str(tmp_path)]) == 0
    stop_out = json.loads(capsys.readouterr().out)
    assert stop_out["stopped"] is False
    assert not (tmp_path / "launch.url").exists()
    assert not (tmp_path / "session.cookie").exists()

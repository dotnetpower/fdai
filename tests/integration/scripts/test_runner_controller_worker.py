"""Short-lived worker credentials are not CLI arguments or inherited management credentials."""

from __future__ import annotations

import importlib.util
import json
import urllib.error
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "broker_worker", ROOT / "infra/ci-runner-aca/broker-entrypoint.py"
)
assert SPEC is not None and SPEC.loader is not None
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)


def test_worker_uses_one_time_broker_data_and_scrubs_management_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "runner"
    directory.mkdir()
    monkeypatch.setenv(
        "FDAI_RUNNER_BOOTSTRAP",
        json.dumps(
            {
                "controller_url": "https://controller.example.com",
                "worker_id": "worker-one",
                "ticket": "synthetic-ticket",
            }
        ),
    )
    monkeypatch.setenv("IDENTITY_HEADER", "synthetic-management-header")
    monkeypatch.setenv("GITHUB_RUNNER_CREDENTIAL", "synthetic-pat-never-forwarded")
    calls = []

    def request(origin, endpoint, payload):
        calls.append((origin, endpoint, payload))
        return {"encoded_jit_config": "synthetic-jit"} if endpoint == "/bootstrap" else {}

    class Process:
        returncode = 0

        def __init__(self, command, *, cwd, env):
            self.command, self.environment = command, dict(env)
            calls.append(("listener", command, self.environment))

        def poll(self):
            return 0

    real_path = Path
    monkeypatch.setattr(
        WORKER, "Path", lambda path: directory if path == "/opt/actions-runner" else real_path(path)
    )
    monkeypatch.setattr(WORKER, "request", request)
    monkeypatch.setattr(WORKER.subprocess, "Popen", Process)
    assert WORKER.main([]) == 0
    listener = next(row for row in calls if row[0] == "listener")
    assert "synthetic-jit" not in listener[1]
    assert listener[2]["ACTIONS_RUNNER_INPUT_JITCONFIG"] == "synthetic-jit"
    assert "IDENTITY_HEADER" not in listener[2]
    assert "GITHUB_RUNNER_CREDENTIAL" not in listener[2]
    assert calls[-1][1] == "/finished"
    assert "FDAI_RUNNER_BOOTSTRAP" not in WORKER.os.environ


@pytest.mark.parametrize(
    "origin",
    [
        "http://controller.example.com",
        "file:///tmp/worker",
        "https://user:pass@example.com",
        "https://controller.example.com/path",
        "https://controller.example.com?query=x",
    ],
)
def test_worker_never_contacts_an_unapproved_bootstrap_origin(origin: str) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        WORKER.request(origin, "/bootstrap", {})


@pytest.mark.parametrize("failure", ["http_503", "network"])
def test_started_notification_failure_preserves_child_until_natural_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    directory = tmp_path / "runner"
    directory.mkdir()
    monkeypatch.setenv(
        "FDAI_RUNNER_BOOTSTRAP",
        json.dumps(
            {
                "controller_url": "https://controller.example.com",
                "worker_id": "worker-one",
                "ticket": "synthetic-ticket",
            }
        ),
    )
    calls = []

    def request(origin, endpoint, payload):
        calls.append(endpoint)
        if endpoint == "/started":
            if failure == "http_503":
                raise urllib.error.HTTPError(origin, 503, "synthetic-ticket", {}, None)
            raise urllib.error.URLError("synthetic-ticket")
        if endpoint == "/finished":
            assert Process.instance.polls == 4
        return {"encoded_jit_config": "synthetic-jit"} if endpoint == "/bootstrap" else {}

    class Process:
        instance = None

        def __init__(self, *args, **kwargs):
            Process.instance = self
            self.returncode, self.polls = None, 0

        def poll(self):
            self.polls += 1
            if self.polls == 2:
                (directory / ".fdai-job-started").touch()
            if self.polls == 4:
                self.returncode = 0
            return self.returncode

    real_path = Path
    monkeypatch.setattr(
        WORKER, "Path", lambda path: directory if path == "/opt/actions-runner" else real_path(path)
    )
    monkeypatch.setattr(WORKER, "request", request)
    monkeypatch.setattr(WORKER.subprocess, "Popen", Process)
    monkeypatch.setattr(WORKER.time, "sleep", lambda delay: None)
    assert WORKER.main([]) == 0
    assert calls == ["/bootstrap", "/registered", "/started", "/finished"]
    output = capsys.readouterr()
    warning = json.loads(output.out)
    assert warning["child_preserved"] is True and warning["retry"] is False
    assert "synthetic-ticket" not in output.out and "synthetic-jit" not in output.out
    assert output.err == ""


@pytest.mark.parametrize("endpoint", ["/bootstrap", "/registered"])
def test_bootstrap_or_registration_failure_aborts_before_child(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    monkeypatch.setenv(
        "FDAI_RUNNER_BOOTSTRAP",
        json.dumps(
            {
                "controller_url": "https://controller.example.com",
                "worker_id": "worker-one",
                "ticket": "synthetic-ticket",
            }
        ),
    )

    def request(origin, path, payload):
        if path == endpoint:
            raise urllib.error.HTTPError(origin, 503, "unavailable", {}, None)
        return {"encoded_jit_config": "synthetic-jit"}

    child = Mock()
    monkeypatch.setattr(WORKER, "request", request)
    monkeypatch.setattr(WORKER.subprocess, "Popen", child)
    with pytest.raises(urllib.error.HTTPError):
        WORKER.main([])
    child.assert_not_called()

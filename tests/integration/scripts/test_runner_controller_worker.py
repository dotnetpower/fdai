"""Short-lived worker credentials are not CLI arguments or inherited management credentials."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

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

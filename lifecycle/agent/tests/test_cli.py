from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from fdai_lifecycle_agent import cli
from fdai_lifecycle_agent.hub_client import HttpHubClient

if TYPE_CHECKING:
    from conftest import Harness

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
ENVELOPE = {
    "schema": "fdai.lifecycle-effect-envelope.v1",
    "entity_ids": ["core", "operator-api"],
    "regions": ["korea-central"],
    "capability_modes": {"action:scale-service": "enforce"},
    "destructive_allowed": False,
    "max_duration_minutes": 60,
}


def _write_inputs(harness: Harness, root: Path) -> None:
    for kind, artifacts in (
        ("releases", harness.store.releases),
        ("configurations", harness.store.configurations),
    ):
        directory = root / kind
        directory.mkdir(parents=True)
        for digest, artifact in artifacts.items():
            (directory / f"{digest}.json").write_bytes(artifact.payload)
            (directory / f"{digest}.sig").write_bytes(artifact.signature)


def _arguments(harness: Harness, tmp_path: Path, **overrides: str) -> list[str]:
    keys = tmp_path / "keys"
    keys.mkdir(exist_ok=True)
    for name, key in (
        ("hub.pem", harness.hub_keys["hub-key-active"]),
        ("release.pem", harness.release_key),
        ("configuration.pem", harness.configuration_key),
    ):
        (keys / name).write_bytes(harness.public_pem(key))
    inputs = tmp_path / "inputs"
    if not inputs.exists():
        _write_inputs(harness, inputs)
    (tmp_path / "current-state.json").write_text(json.dumps(harness.state_document()))
    (tmp_path / "envelope.json").write_text(json.dumps(ENVELOPE))
    values = {
        "--hub-url": "http://127.0.0.1:8740",
        "--installation-id": "installation-alpha",
        "--state-dir": str(tmp_path / "state"),
        "--hub-public-key": str(keys / "hub.pem"),
        "--hub-key-id": "hub-key-active",
        "--hub-key-epoch": "3",
        "--fencing-generation": "4",
        "--release-public-key": str(keys / "release.pem"),
        "--configuration-public-key": str(keys / "configuration.pem"),
        "--inputs-dir": str(inputs),
        "--current-state": str(tmp_path / "current-state.json"),
        "--envelope": str(tmp_path / "envelope.json"),
    }
    values.update(overrides)
    return ["poll-once", *(item for pair in values.items() for item in pair)]


class FakeHubServer:
    """Serves the harness Plan to the real ``HttpHubClient`` through an httpx mock transport."""

    def __init__(self, harness: Harness) -> None:
        self.harness = harness
        self.reports: list[dict[str, object]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.reports.append({"path": request.url.path, **json.loads(request.content)})
            return httpx.Response(202)
        plan = self.harness.hub.plan
        if plan is None:
            return httpx.Response(204)
        encoded = {
            "signed_payload": base64.b64encode(plan.signed_payload).decode(),
            "signature": base64.b64encode(plan.signature).decode(),
        }
        return httpx.Response(200, json={"plan": encoded})

    def connect(self, url: str, timeout_seconds: float) -> HttpHubClient:
        transport = httpx.MockTransport(self.handle)
        return HttpHubClient(url, timeout_seconds=timeout_seconds, transport=transport)

    def run(self, arguments: list[str]) -> int:
        return cli.main(arguments, clock=lambda: NOW, connect_hub=self.connect)


@pytest.fixture
def hub_server(harness: Harness) -> FakeHubServer:
    return FakeHubServer(harness)


def test_poll_once_admits_signed_plan_end_to_end(
    harness: Harness, hub_server: FakeHubServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.serve(harness.plan())

    exit_code = hub_server.run(_arguments(harness, tmp_path))

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["outcome"] == "dry-run-admitted"
    [report] = hub_server.reports
    assert report["path"] == "/v1/installations/installation-alpha/plans/plan-0008/reports"
    assert report["outcome"] == "dry-run-admitted"
    assert report["exact_plan_digest"] == output["exact_plan_digest"]


def test_poll_once_rejects_unsigned_release_file_end_to_end(
    harness: Harness, hub_server: FakeHubServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.serve(harness.plan())
    _arguments(harness, tmp_path)
    (tmp_path / "inputs" / "releases" / f"{harness.release_digest}.sig").unlink()

    exit_code = hub_server.run(_arguments(harness, tmp_path))

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["reason_code"] == "release_signature_missing"
    assert hub_server.reports[0]["outcome"] == "rejected"


def test_poll_once_without_plan_exits_cleanly(
    harness: Harness, hub_server: FakeHubServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert hub_server.run(_arguments(harness, tmp_path)) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "no-plan"
    assert hub_server.reports == []


@pytest.mark.parametrize(
    ("override", "content", "message"),
    [
        ("--hub-url", None, "Hub URL"),
        ("--envelope", {**ENVELOPE, "scope": "all"}, "envelope fields"),
        ("--envelope", {**ENVELOPE, "capability_modes": {"a": "execute"}}, "mode"),
        ("--envelope", {**ENVELOPE, "max_duration_minutes": 0}, "positive"),
        ("--current-state", {"digest": "x", "entities": {}}, "current state MUST contain"),
        ("--hub-public-key", "not a key", "PEM public key"),
    ],
)
def test_invalid_configuration_exits_before_polling(
    harness: Harness,
    hub_server: FakeHubServer,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    override: str,
    content: object,
    message: str,
) -> None:
    harness.serve(harness.plan())
    if override == "--hub-url":
        arguments = _arguments(harness, tmp_path, **{"--hub-url": "http://hub.test"})
    else:
        target = tmp_path / "override.input"
        target.write_text(content if isinstance(content, str) else json.dumps(content))
        arguments = _arguments(harness, tmp_path, **{override: str(target)})

    exit_code = hub_server.run(arguments)

    assert exit_code == 2
    assert message in capsys.readouterr().err
    assert hub_server.reports == []
    assert not (tmp_path / "state").exists()


def test_unsafe_installation_id_is_a_configuration_error(
    harness: Harness, hub_server: FakeHubServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = hub_server.run(_arguments(harness, tmp_path, **{"--installation-id": "../example"}))

    assert exit_code == 2
    assert "installation_id is not a safe path segment" in capsys.readouterr().err
    assert hub_server.reports == []

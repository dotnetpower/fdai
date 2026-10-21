from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock

import httpx
import pytest

from fdai_lifecycle_agent import cli
from fdai_lifecycle_agent.hub_client import HttpHubClient

if TYPE_CHECKING:
    from conftest import FakeCluster, Harness

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
LOCAL_POLICY = {
    "schema": "fdai.lifecycle-local-policy.v1",
    "entity_ids": ["core", "operator-api"],
    "regions": ["korea-central"],
    "capability_modes": {"action:scale-service": "enforce"},
    "destructive_allowed": False,
    "max_duration_minutes": 60,
    "entity_components": {"core": ["core-control-plane"], "operator-api": ["operator-service"]},
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
    (tmp_path / "local-policy.json").write_text(json.dumps(LOCAL_POLICY))
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
        "--local-policy": str(tmp_path / "local-policy.json"),
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

    def run(self, arguments: list[str], cluster: FakeCluster | None = None) -> int:
        def connect_cluster(context: str, namespace: str) -> FakeCluster:
            assert cluster is not None, "a dry run MUST NOT connect to a cluster"
            assert (context, namespace) == ("kind-fdai", cluster.namespace)
            return cluster

        return cli.main(
            arguments, clock=lambda: NOW, connect_hub=self.connect, connect_cluster=connect_cluster
        )


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


def test_bounded_poll_command_reuses_durable_state_without_printing_receipts(
    harness: Harness, hub_server: FakeHubServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.serve(harness.plan())
    arguments = _arguments(harness, tmp_path)
    arguments[0] = "poll"
    arguments.extend(["--max-polls", "2", "--poll-interval-seconds", "0.001"])
    assert hub_server.run(arguments) == 0
    assert len(hub_server.reports) == 1
    assert capsys.readouterr().out == ""


def test_bounded_poll_stops_after_signed_input_rejection(
    harness: Harness,
    hub_server: FakeHubServer,
    tmp_path: Path,
) -> None:
    harness.serve(harness.plan())
    arguments = _arguments(harness, tmp_path)
    (tmp_path / "inputs" / "releases" / f"{harness.release_digest}.sig").unlink()
    arguments[0] = "poll"
    arguments.extend(["--max-polls", "2", "--poll-interval-seconds", "0.001"])
    assert hub_server.run(arguments) == 1
    assert len(hub_server.reports) == 1


def test_in_cluster_flag_is_wired_to_apply_without_context(
    harness: Harness,
    hub_server: FakeHubServer,
    cluster: FakeCluster,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness.serve(harness.plan())
    arguments = _arguments(harness, tmp_path)
    (tmp_path / "local-policy.json").write_text(json.dumps(APPLY_POLICY))
    seen: list[str] = []

    def connect(namespace: str) -> FakeCluster:
        seen.append(namespace)
        return cluster

    monkeypatch.setattr(cli, "_connect_in_cluster", connect)
    assert (
        hub_server.run([*arguments, "--apply", "--in-cluster", "--namespace", cluster.namespace])
        == 0
    )
    assert seen == [cluster.namespace]
    assert cluster.image("operator-service") is not None


def test_remote_workload_identity_is_wired_and_closed(
    harness: Harness,
    hub_server: FakeHubServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai_lifecycle_agent import remote_auth

    token = Mock(return_value="test-federated")
    credentials = Mock(return_value=token)
    monkeypatch.setattr(remote_auth, "WorkloadIdentityAuthorization", credentials)

    def connect(
        url: str, *, timeout_seconds: float, authorization: Callable[[], str]
    ) -> HttpHubClient:
        def handle(request: httpx.Request) -> httpx.Response:
            assert request.headers["authorization"] == "Bearer test-federated"
            return hub_server.handle(request)

        return HttpHubClient(
            url,
            timeout_seconds=timeout_seconds,
            authorization=authorization,
            transport=httpx.MockTransport(handle),
        )

    monkeypatch.setattr(cli, "HttpHubClient", connect)
    arguments = _arguments(
        harness,
        tmp_path,
        **{
            "--hub-url": "https://hub.example.com",
            "--hub-auth": "workload-identity",
            "--hub-scope": "api://hub-example/.default",
        },
    )
    assert cli.main(arguments, clock=lambda: NOW) == 0
    credentials.assert_called_once_with("api://hub-example/.default")
    token.close.assert_called_once()


def test_stage_input_command_verifies_before_publishing_without_network(
    harness: Harness,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    digest, artifact = next(iter(harness.store.releases.items()))
    document = tmp_path / "release.json"
    signature = tmp_path / "release.sig"
    public_key = tmp_path / "release.pem"
    document.write_bytes(artifact.payload)
    signature.write_bytes(artifact.signature)
    public_key.write_bytes(harness.public_pem(harness.release_key))
    arguments = [
        "stage-input",
        "--kind",
        "release",
        "--digest",
        digest,
        "--document",
        str(document),
        "--signature",
        str(signature),
        "--public-key",
        str(public_key),
        "--inputs-dir",
        str(tmp_path / "staged"),
    ]
    assert cli.main(arguments, connect_hub=lambda *_args: pytest.fail("unexpected network")) == 0
    assert (tmp_path / "staged" / "releases" / f"{digest}.json").read_bytes() == artifact.payload
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("override", "content", "message"),
    [
        ("--hub-url", None, "Hub URL"),
        ("--local-policy", {**LOCAL_POLICY, "scope": "all"}, "local policy fields"),
        ("--local-policy", {**LOCAL_POLICY, "capability_modes": {"a": "execute"}}, "mode"),
        ("--local-policy", {**LOCAL_POLICY, "max_duration_minutes": 0}, "positive"),
        (
            "--local-policy",
            {**LOCAL_POLICY, "entity_components": {"core": ["core-control-plane"]}},
            "at least one Release component",
        ),
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


APPLY_FLAGS = ["--apply", "--kube-context", "kind-fdai", "--namespace", "fdai-demo"]
APPLY_POLICY = {
    **LOCAL_POLICY,
    "component_images": {
        "core-control-plane": "registry.example.test/fdai/core",
        "operator-service": "registry.example.test/fdai/operator",
    },
}


def test_poll_once_applies_end_to_end(
    harness: Harness,
    hub_server: FakeHubServer,
    cluster: FakeCluster,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness.serve(harness.plan())
    arguments = _arguments(harness, tmp_path)
    (tmp_path / "local-policy.json").write_text(json.dumps(APPLY_POLICY))

    exit_code = hub_server.run([*arguments, *APPLY_FLAGS], cluster)

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "applied"
    assert [report.get("outcome") for report in hub_server.reports] == [
        "apply-started",
        "applied",
        None,
    ]
    state = hub_server.reports[-1]
    assert state["path"] == "/v1/installations/installation-alpha/state"
    current = json.loads((tmp_path / "current-state.json").read_text())
    assert current == {key: value for key, value in state.items() if key != "path"}
    assert cluster.image("operator-service") == "registry.example.test/fdai/operator@" + (
        harness.image("operator-service-1.5.0")
    )


@pytest.mark.parametrize(
    ("flags", "policy", "message"),
    [
        (["--apply", "--namespace", "fdai-demo"], APPLY_POLICY, "--kube-context"),
        ([*APPLY_FLAGS[:-1], "Not_A_Namespace"], APPLY_POLICY, "valid Kubernetes namespace"),
        (APPLY_FLAGS, LOCAL_POLICY, "component_images lacks"),
        ([*APPLY_FLAGS, "--health-timeout-seconds", "0"], APPLY_POLICY, "MUST be positive"),
        ([*APPLY_FLAGS, "--health-timeout-seconds", "nan"], APPLY_POLICY, "MUST be positive"),
        ([*APPLY_FLAGS, "--health-timeout-seconds", "inf"], APPLY_POLICY, "MUST be positive"),
        (
            APPLY_FLAGS,
            {**APPLY_POLICY, "component_images": {"core-control-plane": "repo/core:1.0"}},
            "without a tag",
        ),
    ],
)
def test_invalid_apply_configuration_exits_before_polling(
    harness: Harness,
    hub_server: FakeHubServer,
    cluster: FakeCluster,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
    policy: dict[str, object],
    message: str,
) -> None:
    harness.serve(harness.plan())
    arguments = _arguments(harness, tmp_path)
    (tmp_path / "local-policy.json").write_text(json.dumps(policy))

    # argparse exits for a missing flag; the other checks return the same code.
    with pytest.raises(SystemExit) as raised:
        raise SystemExit(hub_server.run([*arguments, *flags], cluster))

    assert raised.value.code == 2
    assert message in capsys.readouterr().err
    assert hub_server.reports == []
    assert cluster.calls == []

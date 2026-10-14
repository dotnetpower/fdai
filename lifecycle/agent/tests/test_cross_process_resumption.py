"""Regression check: a Plan superseded before its apply-started report lands.

A kind-cluster demo run showed the Hub reissuing a Plan for a Release it had just rolled back
(fixed on the Hub side by backdating a failure suppression's `starts_at`). That raised a related
question for this side of the loop: `fdai_lifecycle_hub.planning.plan_next` only reuses an open
Plan when `IssuedPlan.still_valid_for` holds, and `HubStore.recompute` otherwise supersedes it
(`rows.supersede`) regardless of whether the agent ever reported on it. Nothing stops the Hub from
superseding a Plan whose `apply-started` report never landed, for example because the Hub was
briefly unreachable for writes right after the agent admitted and journaled it.

This test drives exactly that hand-off with two real `poll-once` OS processes sharing one
`--state-dir`, against a stub Hub (a real loopback HTTP server, not an in-process transport) and a
real local kind cluster, because an in-process harness would not exercise the on-disk journal and
state files the way two separate agent invocations do. It is a code-review follow-up, not a
reproduction of an observed failure: no bug was reported against the agent itself.

Opt in with ``FDAI_LIFECYCLE_KIND_CONTEXT=kind-<cluster>``, matching ``test_kind_apply.py``.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from conftest import Harness
    from fdai_deployment_cli.lifecycle_plan import LifecyclePlan

CONTEXT = os.environ.get("FDAI_LIFECYCLE_KIND_CONTEXT", "")
INSTALLATION_ID = "installation-alpha"  # matches conftest.py; duplicated, not imported
REPOSITORY = "docker.io/nginxinc/nginx-unprivileged"
V1 = "sha256:65e3e85dbaed8ba248841d9d58a899b6197106c23cb0ff1a132b7bfe0547e4c0"  # 1.27-alpine
V2 = "sha256:7377697a821c131a924a7105fafbe7414db4e9fcc77a6f08f776f33f141ec3f8"  # 1.28-alpine

pytestmark = [
    pytest.mark.skipif(
        not CONTEXT.startswith("kind-") or shutil.which("kind") is None,
        reason="set FDAI_LIFECYCLE_KIND_CONTEXT to a kind context to run",
    ),
    pytest.mark.timeout(300),
]


class _StubHub:
    """A real loopback HTTP server a separate agent process can reach over TCP.

    ``plan`` is the Plan the next ``GET /plan`` serves; the test swaps it between the two agent
    runs to stand in for the Hub superseding it. ``fail_reports`` makes the next N report posts
    fail hard (a plain 500, never retried), so the first run's ``apply-started`` report is
    admitted locally but never reaches ``reported=True``.
    """

    def __init__(self) -> None:
        self.plan: LifecyclePlan | None = None
        self.fail_reports = 0
        self.reports: list[dict[str, object]] = []
        self.states: list[dict[str, object]] = []
        self._lock = threading.Lock()
        handler = self._handler()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        host, port, *_ = self._server.server_address
        return f"http://{host!s}:{port}"

    def close(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._server.server_close()

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib shape
                pass

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
                with stub._lock:
                    plan = stub.plan
                if plan is None:
                    self.send_response(204)
                    self.end_headers()
                    return
                body = json.dumps(
                    {
                        "plan": {
                            "signed_payload": base64.b64encode(plan.signed_payload).decode(),
                            "signature": base64.b64encode(plan.signature).decode(),
                        }
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                if self.path.endswith("/state"):
                    with stub._lock:
                        stub.states.append({"path": self.path, **body})
                    self.send_response(202)
                    self.end_headers()
                    return
                with stub._lock:
                    fail = stub.fail_reports > 0
                    if fail:
                        stub.fail_reports -= 1
                    else:
                        stub.reports.append({"path": self.path, **body})
                self.send_response(500 if fail else 202)
                self.end_headers()

        return Handler


@pytest.fixture
def namespace() -> Iterator[str]:
    from kubernetes import client, config  # type: ignore[import-untyped]

    api_client = config.new_client_from_config(context=CONTEXT)
    core = client.CoreV1Api(api_client)
    name = f"fdai-lifecycle-{uuid.uuid4().hex[:8]}"
    core.create_namespace({"metadata": {"name": name}})
    try:
        yield name
    finally:
        core.delete_namespace(name)
        api_client.close()


def _write_fixtures(harness: Harness, root: Path) -> None:
    keys = root / "keys"
    keys.mkdir()
    for name, key in (
        ("hub.pem", harness.hub_keys["hub-key-active"]),
        ("release.pem", harness.release_key),
        ("configuration.pem", harness.configuration_key),
    ):
        (keys / name).write_bytes(harness.public_pem(key))
    inputs = root / "inputs"
    for kind, artifacts in (
        ("releases", harness.store.releases),
        ("configurations", harness.store.configurations),
    ):
        directory = inputs / kind
        directory.mkdir(parents=True)
        for digest, artifact in artifacts.items():
            (directory / f"{digest}.json").write_bytes(artifact.payload)
            (directory / f"{digest}.sig").write_bytes(artifact.signature)
    (root / "current-state.json").write_text(json.dumps(harness.state_document()))
    (root / "local-policy.json").write_text(
        json.dumps(
            {
                "schema": "fdai.lifecycle-local-policy.v1",
                "entity_ids": ["core"],
                "regions": ["korea-central"],
                "capability_modes": {"action:scale-service": "enforce"},
                "destructive_allowed": False,
                "max_duration_minutes": 60,
                "entity_components": {"core": ["core-control-plane"]},
                "component_images": {"core-control-plane": REPOSITORY},
            }
        )
    )


def _run_poll_once(
    root: Path, hub_url: str, installation_id: str, namespace: str, *, health_timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run ``poll-once --apply`` as a real, separate OS process."""

    agent_src = Path(__file__).resolve().parents[1] / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(agent_src), *(path for path in sys.path if path)]),
    }
    return subprocess.run(  # noqa: S603 - fixed interpreter and test-owned arguments
        [
            sys.executable,
            "-m",
            "fdai_lifecycle_agent.cli",
            "poll-once",
            "--hub-url",
            hub_url,
            "--installation-id",
            installation_id,
            "--state-dir",
            str(root / "state"),
            "--hub-public-key",
            str(root / "keys" / "hub.pem"),
            "--hub-key-id",
            "hub-key-active",
            "--hub-key-epoch",
            "3",
            "--fencing-generation",
            "4",
            "--release-public-key",
            str(root / "keys" / "release.pem"),
            "--configuration-public-key",
            str(root / "keys" / "configuration.pem"),
            "--inputs-dir",
            str(root / "inputs"),
            "--current-state",
            str(root / "current-state.json"),
            "--local-policy",
            str(root / "local-policy.json"),
            "--apply",
            "--kube-context",
            CONTEXT,
            "--namespace",
            namespace,
            "--health-timeout-seconds",
            str(health_timeout),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
    )


def _plan_record(root: Path, plan_id: str) -> dict[str, Any]:
    state = json.loads((root / "state" / "lifecycle-agent-state.json").read_text())
    record: dict[str, Any] = state["plans"][plan_id]
    return record


def test_a_superseded_unreported_plan_is_abandoned_not_misapplied(
    harness: Harness, namespace: str, tmp_path: Path
) -> None:
    # The subprocesses run with the real wall clock, unlike the harness's fixed in-process NOW.
    real_deadline = datetime.now(UTC) + timedelta(minutes=10)
    # The harness's default envelope spans both its sample Entities; this test's local policy
    # manages only "core", so both Plans' own envelope must be narrowed to match.
    envelope = harness.maximum_envelope(entity_ids=frozenset({"core"}), max_duration_minutes=30)
    plan_a = harness.release_plan(
        "1.0.0", V1, sequence=8, expires_at=real_deadline, envelope=envelope
    )
    # Built (and so signed and added to the harness's artifact store) before the fixtures are
    # written, so the inputs directory on disk carries both Releases.
    plan_b = harness.release_plan(
        "1.1.0", V2, sequence=9, expires_at=real_deadline, envelope=envelope
    )
    _write_fixtures(harness, tmp_path)
    stub = _StubHub()
    try:
        stub.plan = plan_a
        stub.fail_reports = 1  # the only report this run attempts: apply-started for Plan A

        first = _run_poll_once(tmp_path, stub.url, INSTALLATION_ID, namespace, health_timeout=60.0)

        assert first.returncode == 1, first.stderr
        first_result = json.loads(first.stdout)
        assert (first_result["outcome"], first_result["reported"]) == ("apply-started", False)
        assert [report["path"] for report in stub.reports] == []  # the 500 was never recorded

        journal = json.loads((tmp_path / "state" / "lifecycle-agent-workload.json").read_text())[
            "journal"
        ]
        assert (journal["plan_id"], journal["phase"]) == (plan_a.plan_id, "prepared")

        stub.plan = plan_b  # the Hub superseded Plan A before its report ever landed

        second = _run_poll_once(
            tmp_path, stub.url, INSTALLATION_ID, namespace, health_timeout=120.0
        )

        assert second.returncode == 0, second.stderr
        second_result = json.loads(second.stdout)
        assert (second_result["outcome"], second_result["reported"]) == ("applied", True)
        assert second_result["plan_id"] == plan_b.plan_id

        # Plan A's record is abandoned, not corrupted: it never advances past apply-started,
        # and Plan B gets its own independent, correctly numbered report sequence.
        a_record = _plan_record(tmp_path, plan_a.plan_id)
        assert (a_record["result"]["outcome"], a_record["reported"], a_record["attempts"]) == (
            "apply-started",
            False,
            1,
        )
        b_record = _plan_record(tmp_path, plan_b.plan_id)
        assert (b_record["result"]["outcome"], b_record["reported"], b_record["attempts"]) == (
            "applied",
            True,
            2,
        )
        reported_paths = [report["path"] for report in stub.reports]
        assert (
            reported_paths
            == [
                f"/v1/installations/{INSTALLATION_ID}/plans/{plan_b.plan_id}/reports",
            ]
            * 2
        )

        # Only Plan B ever reached the cluster; Plan A was never applied.
        from kubernetes import client, config

        api_client = config.new_client_from_config(context=CONTEXT)
        apps = client.AppsV1Api(api_client)
        deployment = apps.read_namespaced_deployment("core-control-plane", namespace)
        api_client.close()
        image = deployment.spec.template.spec.containers[0].image
        assert image == f"{REPOSITORY}@{V2}"
    finally:
        stub.close()

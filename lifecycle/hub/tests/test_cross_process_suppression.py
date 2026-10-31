"""Regression test: a failure hold must survive a hand-off between real OS processes.

A kind-cluster demo run once showed the Hub reissuing a Plan for a Release it had just rolled
back, instead of waiting on the failure suppression. Every existing Hub test either calls
HubStore methods directly or drives fdai_lifecycle_hub.cli.main() in this same interpreter, and
most share one in-memory SQLite connection (conftest.py's store fixture). None of that exercises
the Hub's real topology: a long-running serve process records the rolled-back report, and a
separate, short-lived recompute process must read the resulting suppression back from a real
on-disk database it never held open. This test drives exactly that hand-off with real subprocesses,
repeated several times, because a one-shot run would not have caught the kind-cluster observation.

Root cause confirmed by this test, not hypothesized: the suppression's `starts_at` is the writer
process's own `now`, and `_suppression_decision` requires `starts_at <= reader_now`. Two separate
processes read the host clock independently, so any backward skew between the write and a later
read (observed here as WSL2's periodic Hyper-V timesync correction, "Time jumped backwards" in
`dmesg`) can make a just-written hold briefly invisible to the next recompute, exactly reproducing
the kind-cluster observation. This is a real clock-skew gap in the suppression check itself, not a
SQLite visibility issue; a hardening fix (for example backdating an automatic failure suppression's
`starts_at` by a small grace margin) is tracked separately and is out of this test's scope.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from fdai_lifecycle_hub.domain import Installation, Issued, Planner
from fdai_lifecycle_hub.schemas import settings_json

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
_HUB_SRC = Path(__file__).resolve().parents[1] / "src"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEPLOYMENT_CLI_SRC = _REPO_ROOT / "packages" / "deployment-cli" / "src"
_MODULE = "fdai_lifecycle_hub.cli"
_ITERATIONS = 8
_STARTUP_SECONDS = 10.0

_REPORT_SCRIPT = """
import json, sys, urllib.request
url = sys.argv[1]
for raw in sys.argv[2:]:
    request = urllib.request.Request(
        url,
        data=raw.encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status != 202:
            sys.exit(1)
"""

_BATCH_CLI_SCRIPT = """
import io, json, sys
from contextlib import redirect_stdout
from fdai_lifecycle_hub.cli import main

commands = json.loads(sys.argv[1])
outputs = []
for argv in commands:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(argv)
    if rc != 0:
        sys.exit(rc)
    outputs.append(json.loads(buf.getvalue()))
print(json.dumps(outputs))
"""

_SETUP_ALL_SCRIPT = """
import io, json, sys
from contextlib import redirect_stdout
from fdai_lifecycle_hub.cli import main

def run_cmd(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(argv)
    if rc != 0:
        sys.exit(rc)
    return json.loads(buf.getvalue())

spec = json.loads(sys.argv[1])
run_cmd(["migrate"])
run_cmd(["dev-keygen", spec["hub_key"]])
run_cmd(["dev-keygen", spec["installation_key"]])
issued_by_id = {}
for item in spec["installations"]:
    inst = item["installation_id"]
    pending = run_cmd(["dev-enroll", item["request_path"], "--key", spec["installation_key"]])
    key_id = pending["installation_key_id"]
    run_cmd(["approve", inst, "--approver", "alice", "--installation-key-id", key_id])
    run_cmd(["record-ownership", inst, "core", spec["ownership_path"], "--operator", "bob"])
    run_cmd(["manage", inst, "core", spec["settings_path"], "--operator", "bob"])
    recompute = ["recompute", inst, "--catalog", spec["catalog"], "--key", spec["hub_key"]]
    issued_by_id[inst] = run_cmd(recompute)
print(json.dumps(issued_by_id))
"""


def _subprocess_env(database_url: str) -> dict[str, str]:
    """The environment every spawned process gets: its own PYTHONPATH, nothing shared in memory."""

    extra = os.pathsep.join(str(path) for path in (_HUB_SRC, _DEPLOYMENT_CLI_SRC))
    existing = os.environ.get("PYTHONPATH")
    pythonpath = f"{extra}{os.pathsep}{existing}" if existing else extra
    return os.environ | {"PYTHONPATH": pythonpath, "FDAI_LIFECYCLE_HUB_DATABASE_URL": database_url}


def _hub_batch(env: dict[str, str], *commands: Sequence[str]) -> list[dict[str, Any]]:
    """Run multiple fdai-lifecycle-hub commands in one fresh OS process."""

    result = subprocess.run(  # noqa: S603 - fixed script and arguments.
        [sys.executable, "-c", _BATCH_CLI_SCRIPT, json.dumps([list(cmd) for cmd in commands])],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"fdai-lifecycle-hub batch {commands}: {result.stderr}"
    records: list[dict[str, Any]] = json.loads(result.stdout)
    return records


def _setup_and_issue_all_in_fresh_process(
    env: dict[str, str],
    *,
    tmp_path: Path,
    hub_key: Path,
    installation_key: Path,
    catalog: str,
) -> dict[str, dict[str, Any]]:
    """Migrate, generate keys, and enroll/issue initial Plans in one fresh OS process."""

    installations = []
    for iteration in range(_ITERATIONS):
        installation_id = f"example-{iteration}"
        request = tmp_path / f"enrollment-{iteration}.json"
        request.write_text(json.dumps(_enrollment_template(installation_id)))
        installations.append({"installation_id": installation_id, "request_path": str(request)})
    spec = {
        "hub_key": str(hub_key),
        "installation_key": str(installation_key),
        "ownership_path": str(SAMPLES / "ownership.json"),
        "settings_path": str(SAMPLES / "core-settings.json"),
        "catalog": catalog,
        "installations": installations,
    }
    result = subprocess.run(  # noqa: S603 - fixed script and arguments.
        [sys.executable, "-c", _SETUP_ALL_SCRIPT, json.dumps(spec)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"setup_and_issue_all: {result.stderr}"
    records: dict[str, dict[str, Any]] = json.loads(result.stdout)
    return records


def _wait_healthy(url: str) -> None:
    deadline = time.monotonic() + _STARTUP_SECONDS
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/healthz", timeout=1.0).status_code == 200:
                return
        except httpx.TransportError:
            time.sleep(0.05)
    raise AssertionError(f"the Hub API did not become healthy at {url}")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def _exact_plan_digest(url: str, installation_id: str) -> str:
    """Read the installation's open Plan over HTTP and hash the exact bytes it carries."""

    response = httpx.get(f"{url}/v1/installations/{installation_id}/plan", timeout=5.0)
    assert response.status_code == 200, response.text
    payload = base64.b64decode(response.json()["plan"]["signed_payload"])
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _report_rolled_back_from_a_separate_process(
    url: str, installation_id: str, plan_id: str, exact_plan_digest: str
) -> None:
    """Submit the apply progression from brand-new interpreters, so the commit that adds the
    failure suppression shares no module cache or open connection with whichever process issued
    the Plan or will later recompute it. The Hub's serve process still performs the actual write;
    this only keeps the HTTP callers genuinely separate processes, matching the demo's topology.
    """

    report_url = f"{url}/v1/installations/{installation_id}/plans/{plan_id}/reports"
    reports = (
        {
            "attempt": 1,
            "outcome": "apply-started",
            "reason_code": "apply_started",
            "exact_plan_digest": exact_plan_digest,
            "summary": "cross-process apply started",
            "reported_at": "2026-01-01T00:00:00Z",
        },
        {
            "attempt": 2,
            "outcome": "rolled-back",
            "reason_code": "health_check_failed",
            "exact_plan_digest": exact_plan_digest,
            "summary": "cross-process regression",
            "reported_at": "2026-01-01T00:00:00Z",
        },
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter, script built above.
        [
            sys.executable,
            "-c",
            _REPORT_SCRIPT,
            report_url,
            *(json.dumps(report) for report in reports),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _checks_by_release(record: dict[str, Any]) -> dict[str, list[str]]:
    return {
        check["release_id"]: [block["reason_code"] for block in check["blocks"]]
        for check in record["checks"]
    }


def _enrollment_template(installation_id: str) -> dict[str, Any]:
    template: dict[str, Any] = json.loads((SAMPLES / "enrollment.json").read_bytes())
    template["installation_id"] = installation_id
    # Overlapping daily windows keep the full Plan duration available across local midnight.
    windows = template["settings"]["windows"]
    windows.append({**windows[0], "start": "12:00:00"})
    return template


def test_cross_process_fixture_can_issue_a_full_plan_at_every_minute(
    installation: Installation, planner: Planner
) -> None:
    settings = settings_json.validate_python(_enrollment_template("example")["settings"])
    installation = replace(
        installation, settings=replace(installation.settings, windows=settings.windows)
    )
    midnight = datetime(2026, 10, 15, tzinfo=UTC)
    for minute in range(24 * 60):
        at = midnight + timedelta(minutes=minute)
        outcome = planner(installation, at)
        assert isinstance(outcome, Issued), (at, outcome)
        assert outcome.plan.expires_at - at >= installation.settings.plan_duration


@pytest.mark.timeout(240)
def test_a_fresh_recompute_process_sees_the_rollback_suppression_a_different_process_wrote(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'hub.db'}"
    env = _subprocess_env(database_url)
    hub_key, installation_key = tmp_path / "hub.pem", tmp_path / "installation.pem"
    catalog = str(SAMPLES / "catalog")
    issued_by_id = _setup_and_issue_all_in_fresh_process(
        env,
        tmp_path=tmp_path,
        hub_key=hub_key,
        installation_key=installation_key,
        catalog=catalog,
    )

    port = _free_port()
    server = subprocess.Popen(  # noqa: S603 - fixed module and port.
        [sys.executable, "-m", _MODULE, "serve", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_healthy(url)
        for iteration in range(_ITERATIONS):
            installation_id = f"example-{iteration}"
            recompute = ("recompute", installation_id, "--catalog", catalog, "--key", str(hub_key))

            issued = issued_by_id[installation_id]
            assert (issued["outcome"], issued["target"]) == ("issued", "1.6.0"), (
                iteration,
                issued,
            )
            plan_id = issued["plan_id"]

            digest = _exact_plan_digest(url, installation_id)
            _report_rolled_back_from_a_separate_process(url, installation_id, plan_id, digest)

            waiting, shown = _hub_batch(env, recompute, ("show", installation_id))

            assert (waiting["outcome"], waiting["target"]) == ("waiting", "1.6.0"), (
                iteration,
                waiting,
            )
            assert _checks_by_release(waiting) == {"1.6.0": ["suppression_window_active"]}, (
                iteration,
                waiting,
            )
            assert shown["plan"] is None, (iteration, shown)
            holds = [
                s
                for s in shown["suppressions"]
                if s["scope"] == "entity:core" and s["origin"] == "failure"
            ]
            assert len(holds) == 1, (iteration, shown["suppressions"])
            assert holds[0]["failed_plan_id"] == plan_id, (iteration, holds)
    finally:
        server.terminate()
        server.wait(timeout=10)

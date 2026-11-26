"""Fresh CLI processes over a synthetic loopback wire, not operational/authentication proof."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fdai_deployment_cli.contracts import canonical_digest
from lifecycle.agent.tests.test_configuration_entrypoint import (
    PRIVATE_MARKER,
)
from lifecycle.agent.tests.test_configuration_entrypoint import (
    entrypoint as entrypoint,
)
from lifecycle.agent.tests.test_cross_process_resumption import _StubHub

if TYPE_CHECKING:
    from conftest import Harness

ROOT = Path(__file__).resolve().parents[3]


def _run_cli(module: str, arguments: list[str], private: Path) -> subprocess.CompletedProcess[str]:
    home = private / "empty-home"
    scratch = private / "scratch"
    home.mkdir(mode=0o700, exist_ok=True)
    scratch.mkdir(mode=0o700, exist_ok=True)
    # Inherit no credentials, DSNs, proxies, kubeconfig, or another checkout's PYTHONPATH.
    environment = {
        "PYTHONPATH": os.pathsep.join(
            str(ROOT / relative)
            for relative in (
                "lifecycle/agent/src",
                "packages/deployment-cli/src",
                "packages/service-contracts/src",
            )
        ),
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": str(home),
        "TMPDIR": str(scratch),
        "PATH": str(home / "no-tools"),
    }
    result = subprocess.run(  # noqa: S603 - fixed interpreter and test-owned CLI inputs
        [sys.executable, "-m", module, *arguments],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    output = result.stdout + result.stderr
    private_markers = ["PRIVATE KEY", "PUBLIC KEY", PRIVATE_MARKER, "replicas"]
    for path in private.glob("*.pem"):
        private_markers.extend(
            line for line in path.read_text().splitlines() if not line.startswith("-----")
        )
    if any(marker in output for marker in private_markers):
        pytest.fail("CLI subprocess exposed a key or configuration input")
    assert result.returncode == 0, result.stderr
    return result


@pytest.fixture
def configuration_producer(tmp_path: Path) -> Callable[[list[str]], int]:
    """Use the existing input fixture, but produce its consumed artifact in a fresh process."""

    def produce(arguments: list[str]) -> int:
        private = tmp_path / "private"
        result = _run_cli("fdai_deployment_cli", arguments, private)
        assert json.loads(result.stdout)["verified"] is True
        return result.returncode

    return produce


@pytest.fixture
def wire_hub() -> Iterator[_StubHub]:
    hub = _StubHub()
    try:
        with httpx.Client(trust_env=False, timeout=2.0) as client:
            response = client.get(f"{hub.url}/v1/installations/installation-alpha/plan")
            assert response.status_code == 204
        yield hub
    finally:
        hub.close()
        assert not hub._thread.is_alive()


@pytest.mark.timeout(60)
@pytest.mark.parametrize("wrong_recipient", [False, True])
def test_fresh_producer_and_agent_modules_use_full_revision_wire(
    harness: Harness,
    entrypoint: tuple[list[str], dict[str, Any]],
    wire_hub: _StubHub,
    wrong_recipient: bool,
) -> None:
    arguments, context = entrypoint
    private = Path(context["private"])
    now = datetime.now(UTC)
    harness.current_state = replace(harness.current_state, observed_at=now)
    state = harness.state_document()
    state.pop("digest")
    harness.current_state = replace(harness.current_state, digest=canonical_digest(state))
    (private / "state.json").write_text(json.dumps(harness.state_document()))
    plan = harness.plan(expires_at=now + timedelta(minutes=30))
    wire_hub.plan = plan
    arguments[arguments.index("--hub-url") + 1] = wire_hub.url
    if wrong_recipient:
        (private / "encryption-private.pem").write_bytes(
            X25519PrivateKey.generate().private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    assert "--apply" not in arguments
    result = _run_cli("fdai_lifecycle_agent.cli", arguments, private)
    outcome = json.loads(result.stdout)
    expected = "rejected" if wrong_recipient else "dry-run-admitted"
    assert outcome["outcome"] == expected
    assert outcome["reported"] is True
    assert [report["outcome"] for report in wire_hub.reports] == [expected]
    assert wire_hub.reports[0]["path"] == (
        f"/v1/installations/installation-alpha/plans/{plan.plan_id}/reports"
    )
    assert wire_hub.states == []
    assert not (private / "agent-state" / "lifecycle-agent-workload.json").exists()
    reports = json.dumps(wire_hub.reports)
    assert PRIVATE_MARKER not in reports and "replicas" not in reports
    if wrong_recipient:
        assert outcome["reason_code"] == "configuration_malformed"
        assert wire_hub.reports[0]["exact_plan_digest"] is None
    else:
        assert wire_hub.reports[0]["exact_plan_digest"] is not None
        # A second fresh process reuses durable state without submitting another report.
        replay = _run_cli("fdai_lifecycle_agent.cli", arguments, private)
        assert json.loads(replay.stdout)["outcome"] == "already-reported"
        assert len(wire_hub.reports) == 1

"""Prove application transport spends a single current budget before every operation."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import standalone_application
from fdai_deployment_cli.deadline_transport import DeadlineTransport
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline


@pytest.mark.parametrize("elapsed", [90, 101])
@pytest.mark.parametrize("transfer_failure", [False, True])
def test_application_does_not_reset_budget_after_transfer(
    tmp_path, monkeypatch, elapsed, transfer_failure
):
    clock = [0.0]
    observed = []
    closed = []

    class Tunnel:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            closed.append(True)

        def ssh(self, command, *, timeout, input_text=None):
            if command == ("prepare",):
                clock[0] += elapsed
                if transfer_failure:
                    raise subprocess.TimeoutExpired(["ssh", "private-transfer-marker"], elapsed)
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            observed.append(timeout)
            raise RuntimeError("stop-before-provider")

    module = SimpleNamespace(
        BastionTunnel=Tunnel,
        validate_known_hosts=lambda _path: None,
        validate_ssh_private_key=lambda _path: "key-digest",
    )
    handoff = {
        "runner": {
            "ssh_key_digest": "key-digest",
            "admin_username": "operator",
            "vm_id": "synthetic",
        },
        "access": {"bastion_name": "synthetic"},
        "ops": {"resource_group_name": "synthetic"},
        "subscription_id": "00000000-0000-0000-0000-000000000001",
    }
    monkeypatch.setattr(standalone_application, "_private_json", lambda *_args: handoff)
    monkeypatch.setattr(standalone_application, "_import_bastion", lambda _path: module)
    monkeypatch.setattr(standalone_application, "archive_verified_kit", lambda *_args: "a" * 64)
    monkeypatch.setattr(standalone_application, "_replace_private_json", lambda *_args: None)
    monkeypatch.setattr(
        standalone_application,
        "_prepare_remote",
        lambda tunnel, **_kwargs: tunnel.ssh(("prepare",), timeout=300),
    )
    monkeypatch.setattr(standalone_application, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    prepared = SimpleNamespace(
        root=tmp_path,
        ssh_private_key=tmp_path / "key-path-only",
        target_binding="b" * 64,
        source_commit="c" * 40,
        kit_manifest_digest="d" * 64,
    )
    expected = ValueError if transfer_failure else RuntimeError if elapsed < 100 else TimeoutError
    with pytest.raises(expected, match="stop-before-provider|remaining budget|managed-host"):
        standalone_application.deploy_standalone_application(
            kit=SimpleNamespace(),
            prepared=prepared,
            foundation_status={"foundation_report": {"foundation_plan": {"plan_ref": "plan"}}},
            entra_bindings={},
            scripts=tmp_path,
            license_signing_key=None,
            trial_token=None,
            timeout_seconds=100,
        )
    assert observed == ([10] if elapsed < 100 and not transfer_failure else [])
    assert closed == [True]
    assert not (tmp_path / "standalone-application-receipt.json").exists()


def test_deadline_transport_preserves_payload_and_clamps_each_operation(tmp_path):
    clock = [0.0]
    calls = []

    def ssh(command, **kwargs):
        calls.append((command, kwargs))
        clock[0] += 20
        return subprocess.CompletedProcess(command, 0, stdout="unchanged", stderr="")

    def copy(source, destination, **kwargs):
        calls.append((source, destination, kwargs))
        clock[0] += 20

    deadline = DeploymentDeadline(100, clock=lambda: clock[0])
    transport = DeadlineTransport(SimpleNamespace(ssh=ssh, copy_to=copy), deadline)
    result = transport.ssh(("exact", "command"), timeout=500, input_text="synthetic-input")
    transport.copy_to(tmp_path / "source", "unchanged-destination", timeout=300)
    assert result.stdout == "unchanged"
    assert calls == [
        (("exact", "command"), {"timeout": 100, "input_text": "synthetic-input"}),
        (tmp_path / "source", "unchanged-destination", {"timeout": 80}),
    ]
    clock[0] = 100
    with pytest.raises(TimeoutError, match="remaining budget"):
        transport.ssh(("never",), timeout=300)
    with pytest.raises(TimeoutError, match="remaining budget"):
        transport.copy_to(tmp_path / "never", "never", timeout=300)
    assert len(calls) == 2


@pytest.mark.parametrize("operation", ["ssh", "copy_to"])
def test_transport_timeout_never_exposes_private_command(tmp_path, operation):
    def failed(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["ssh", "/private-key-path-marker", "private-target"], 10)

    transport = DeadlineTransport(
        SimpleNamespace(ssh=failed, copy_to=failed), DeploymentDeadline(100)
    )
    with pytest.raises(ValueError, match="managed-host") as error:
        if operation == "ssh":
            transport.ssh(("exact",), timeout=10)
        else:
            transport.copy_to(tmp_path / "input", "destination", timeout=10)
    assert "private-" not in str(error.value)

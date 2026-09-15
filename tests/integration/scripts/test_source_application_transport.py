"""Source host transfer requires original evidence and never retries an ambiguous copy."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

import source_application_transport as transport  # noqa: E402
import source_genesis  # noqa: E402
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest  # noqa: E402
from fdai_deployment_cli.private_output import write_private_bytes  # noqa: E402
from fdai_deployment_cli.target import compute_target_binding  # noqa: E402


@pytest.fixture
def source_transfer(tmp_path, monkeypatch):
    foundation_root = tmp_path / "foundation"
    directory = foundation_root / "foundation-plan-attempt-1"
    directory.mkdir(mode=0o700, parents=True)
    foundation_root.chmod(0o700)
    source_commit = "a" * 40
    tenant = "00000000-0000-0000-0000-000000000001"
    subscription = "00000000-0000-0000-0000-000000000002"
    binding = compute_target_binding(tenant_id=tenant, subscription_id=subscription)
    known_hosts = b"synthetic pinned host key"
    write_private_bytes(directory / "runner-known-hosts", known_hosts)
    handoff = {
        "tenant_id": tenant,
        "subscription_id": subscription,
        "source_commit": source_commit,
        "runner": {
            "admin_username": "example",
            "execution_transport": "manual",
            "vm_id": "synthetic-vm",
            "ssh_key_digest": "b" * 64,
            "parallelism": 1,
        },
        "access": {"method": "bastion", "bastion_name": "example"},
        "ops": {"resource_group_name": "example"},
    }
    write_private_bytes(directory / "foundation-private-handoff.json", canonical_bytes(handoff))

    def retain(filename, schema, fields):
        receipt = {
            "schema_version": schema,
            "source_commit": source_commit,
            "target_binding": binding,
            **fields,
        }
        receipt["receipt_digest"] = canonical_digest(receipt)
        write_private_bytes(directory / filename, canonical_bytes(receipt))
        return receipt

    foundation = retain(
        "foundation-apply-receipt.json",
        "fdai.genesis-foundation-apply-receipt.v1",
        {
            "handoff_digest": canonical_digest(handoff),
            "effect_verified": True,
        },
    )
    enrollment = retain(
        "runner-enrollment-receipt.json",
        "fdai.genesis-runner-enrollment-receipt.v1",
        {
            "foundation_receipt_digest": foundation["receipt_digest"],
            "handoff_digest": foundation["handoff_digest"],
            "effect_verified": True,
            "identity_attested": True,
            "host_key_digest": hashlib.sha256(known_hosts).hexdigest(),
        },
    )
    state = retain(
        "foundation-state-handoff-receipt.json",
        "fdai.genesis-foundation-state-handoff-receipt.v1",
        {
            "state": "verified",
            "foundation_receipt_digest": foundation["receipt_digest"],
            "enrollment_receipt_digest": enrollment["receipt_digest"],
            **{
                key: True
                for key in (
                    "effect_verified",
                    "runner_attested",
                    "remote_backend_authority_verified",
                    "zero_change_verified",
                    "remote_transient_deleted",
                    "local_state_deleted",
                )
            },
        },
    )
    local = {
        "schema_version": "fdai.source-transport-receipt.v1",
        "source_commit": source_commit,
        "archive_digest": "c" * 64,
        "snapshot_digest": "d" * 64,
        "provenance": "operator-selected-source",
        "release_signature_verified": False,
        "apply_authorized": False,
        "deployment_ready": False,
        "mutation_performed": False,
    }
    arguments = dict(
        foundation_root=foundation_root,
        snapshot=tmp_path / "snapshot",
        snapshot_digest="d" * 64,
        source_commit=source_commit,
        target_binding=binding,
        report={"foundation_plan": {"plan_ref": directory.name}, "state_handoff": state},
        timeout_seconds=300,
    )
    calls = []
    failure = {"stage": ""}

    class Tunnel:
        def __init__(self, **kwargs):
            assert kwargs["trust_new_host_key"] is False
            assert (
                kwargs["host_key_alias"]
                == "fdai-genesis-" + hashlib.sha256(b"synthetic-vm").hexdigest()[:16]
            )
            calls.append("connect")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            calls.append("closed")

        def copy_to(self, source, destination, *, timeout):
            assert (tmp_path / "source-host-transfer-claim.json").exists()
            calls.append("copy")
            if failure["stage"] == "copy":
                raise OSError("copy interrupted")

        def ssh(self, command, *, timeout, input_text=None):
            calls.append(command)
            assert 0 < timeout <= 300
            if command[0] == "sha256sum":
                output = f"{'0' * 64 if failure['stage'] == 'hash' else 'e' * 64}  {command[-1]}\n"
            elif command[0] == "python3":
                output = json.dumps(
                    {
                        **local,
                        **({"deployment_ready": True} if failure["stage"] == "receipt" else {}),
                    }
                )
            else:
                output = ""
            return subprocess.CompletedProcess(command, 0, output, "")

    def attest(*_args, **_kwargs):
        calls.append("attest")
        if failure["stage"] == "attest":
            raise ValueError("attestation failed")

    monkeypatch.setattr(transport, "BastionTunnel", Tunnel)
    monkeypatch.setattr(transport, "_attest_runner", attest)
    monkeypatch.setattr(transport, "validate_known_hosts", lambda *_args: None)
    monkeypatch.setattr(transport, "validate_ssh_private_key", lambda *_args: "b" * 64)
    monkeypatch.setattr(
        transport,
        "verify_source_snapshot",
        lambda *_args, **_kwargs: {"source_commit": source_commit},
    )
    monkeypatch.setattr(
        transport,
        "prepare_source_transport",
        lambda *_args, **_kwargs: {
            **local,
            "archive_ref": "source-transfer.tar",
            "state": "prepared",
            "remote_transfer_verified": False,
            "receipt_digest": "f" * 64,
        },
    )
    monkeypatch.setattr(transport, "prepare_source_receiver", lambda *_args, **_kwargs: "e" * 64)
    return arguments, calls, failure, directory


def test_source_transfer_verifies_host_and_recovers_without_copy(source_transfer):
    arguments, calls, _, _ = source_transfer
    receipt = transport.transfer_application_source(**arguments)
    assert receipt["remote_transfer_verified"] is True
    assert receipt["deployment_ready"] is False
    assert calls.index("attest") < calls.index("copy")
    assert calls.count("copy") == 2
    calls.clear()
    assert transport.transfer_application_source(**arguments) == receipt
    assert "copy" not in calls
    assert any(isinstance(command, tuple) and "--verify-existing" in command for command in calls)
    assert not any(isinstance(command, tuple) and command[0] == "mkdir" for command in calls)


@pytest.mark.parametrize("stage", ["attest", "copy", "hash", "receipt"])
def test_source_transfer_failure_never_records_success(source_transfer, stage):
    arguments, calls, failure, _ = source_transfer
    failure["stage"] = stage
    with pytest.raises(ValueError):
        transport.transfer_application_source(**arguments)
    work = arguments["foundation_root"].parent
    assert not (work / "source-host-transfer-receipt.json").exists()
    assert calls[-1] == "closed"
    if stage in {"attest", "hash"}:
        assert not any(isinstance(command, tuple) and command[0] == "python3" for command in calls)
    if stage == "attest":
        assert not (work / "source-host-transfer-claim.json").exists()
        assert "copy" not in calls


def test_interrupted_source_copy_is_never_repeated(source_transfer):
    arguments, calls, failure, _ = source_transfer
    failure["stage"] = "copy"
    with pytest.raises(ValueError):
        transport.transfer_application_source(**arguments)
    calls.clear()
    failure["stage"] = "hash"
    with pytest.raises(ValueError, match="bootstrap hash differs"):
        transport.transfer_application_source(**arguments)
    assert "copy" not in calls
    assert not any(isinstance(command, tuple) and command[0] == "mkdir" for command in calls)


@pytest.mark.parametrize("stage", ["runner-image-apply", "application-plan", "application-failure"])
def test_source_coordinator_transfers_only_at_application_boundary(
    source_transfer, monkeypatch, stage
):
    arguments, _, _, directory = source_transfer
    handoff = json.loads((directory / "foundation-private-handoff.json").read_bytes())
    args = SimpleNamespace(
        **{
            "target_binding": arguments["target_binding"],
            "region": "eastus",
            "timeout_seconds": 1800,
            "approval_file": None,
            "source_snapshot": arguments["snapshot"],
            "source_snapshot_digest": arguments["snapshot_digest"],
            "terraform": directory / "terraform",
        }
    )
    source = SimpleNamespace(root=ROOT, commit=arguments["source_commit"], reverify=Mock())
    store = SimpleNamespace(
        foundation_report=arguments["report"],
        mutation_performed=True,
        attempt=1,
        target_binding="f" * 64,
        payload={},
        remaining_seconds=lambda: 300,
    )

    def update(**values):
        store.payload.update(
            {
                "current_stage": values["stage"],
                "reason_code": values.get("reason_code", ""),
                "next_action": values.get("next_action", ""),
            }
        )

    store.update = update
    checks = Mock()
    checks.capture.side_effect = lambda command, *_args, **_kwargs: (
        "https://github.com/example/fdai.git" if command[0] == "git" else "[]"
    )
    coordinator = Mock()
    coordinator.run.side_effect = source_genesis.PrivateExecutionWaitError(
        "application-plan" if stage.startswith("application") else stage, "review", "review"
    )
    receiver = Mock(return_value={"remote_transfer_verified": True})
    if stage == "application-failure":
        receiver.side_effect = ValueError("source transfer failed")
    monkeypatch.setattr(
        source_genesis,
        "active_azure_target",
        lambda: SimpleNamespace(
            tenant_id=handoff["tenant_id"],
            subscription_id=handoff["subscription_id"],
        ),
    )
    monkeypatch.setattr(
        source_genesis,
        "load_profile",
        lambda *_args: SimpleNamespace(
            target_binding=arguments["target_binding"],
            region="eastus",
            environment="dev",
            connectivity="online",
            transport="manual",
        ),
    )
    monkeypatch.setattr(source_genesis, "StatusStore", lambda **_kwargs: store)
    monkeypatch.setattr(source_genesis, "GenesisChecks", lambda *_args: checks)
    monkeypatch.setattr(source_genesis, "load_genesis_approval", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        source_genesis,
        "reconcile_resource_providers",
        lambda **_kwargs: SimpleNamespace(
            state="ready",
            to_mapping=lambda: {"state": "ready"},
        ),
    )
    monkeypatch.setattr(
        source_genesis, "PrivateExecutionCoordinator", lambda **_kwargs: coordinator
    )
    monkeypatch.setattr(transport, "transfer_application_source", receiver)
    if stage == "application-failure":
        with pytest.raises(ValueError, match="source transfer failed"):
            source_genesis._advance_locked(args, source, arguments["foundation_root"], "f" * 64)
        assert store.payload["reason_code"] == "source_application_transfer_failed"
    else:
        result = source_genesis._advance_locked(
            args, source, arguments["foundation_root"], "f" * 64
        )
        assert result["deployment_ready"] is False
        assert ("source_host_transfer" in result) == (stage == "application-plan")
    assert receiver.call_count == int(stage.startswith("application"))
    checks.verify_source.assert_called_once()


@pytest.mark.parametrize(
    "filename",
    [
        "foundation-private-handoff.json",
        "foundation-apply-receipt.json",
        "runner-enrollment-receipt.json",
        "foundation-state-handoff-receipt.json",
        "runner-known-hosts",
    ],
)
def test_source_transfer_rejects_changed_original_evidence_before_connection(
    source_transfer, filename
):
    arguments, calls, _, directory = source_transfer
    (directory / filename).write_bytes(b"changed")
    with pytest.raises(ValueError):
        transport.transfer_application_source(**arguments)
    assert "connect" not in calls

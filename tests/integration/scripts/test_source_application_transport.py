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
def source_recovery_run(tmp_path, monkeypatch):
    import source_recovery as recovery_runner
    from fdai_deployment_cli import source_recovery as admission
    from fdai_deployment_cli.contracts import ProvisionProfile
    from fdai_deployment_cli.profile import write_profile
    from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile

    tmp_path.chmod(0o700)
    work = tmp_path / "run"
    original = work / "foundation/foundation-plan-attempt-3"
    original.mkdir(mode=0o700, parents=True)
    work.chmod(0o700)
    original.parent.chmod(0o700)
    (original.parent / "source-execution.lock").touch(mode=0o600)
    recovery = work / "foundation-recovery-attempt-1"
    recovery.mkdir(mode=0o700)
    snapshot = {"source_commit": "a" * 40, "source_tree": "b" * 40}
    profile = RuntimeDeploymentProfile.create(
        runtime_platform="aks", database_placement="postgres-flex"
    )
    intent = {
        "schema_version": "fdai.source-deployment-intent.v1",
        "source": snapshot,
        "source_input_digest": canonical_digest(snapshot),
        "runtime_profile": profile.to_mapping(),
        "environment": "dev",
        "region": "koreacentral",
        "monthly_cost_ceiling": 500,
    }
    write_private_bytes(work / "source-intent.json", canonical_bytes(intent))
    preparation = {
        "schema_version": "fdai.source-deployment-preparation.v1",
        "state": "prepared",
        "provenance": "operator-selected-source",
        "release_signature_verified": False,
        "apply_authorized": False,
        "mutation_performed": False,
        "deployment_ready": False,
        "subscription_ready": False,
        "source_commit": snapshot["source_commit"],
        "source_input_digest": canonical_digest(snapshot),
        "source_snapshot_digest": "c" * 64,
        "intent_digest": canonical_digest(intent),
        "runtime_profile_digest": profile.digest,
    }
    preparation["receipt_digest"] = canonical_digest(preparation)
    write_private_bytes(work / "source-preparation.json", canonical_bytes(preparation))
    marker = {
        "source_commit": snapshot["source_commit"],
        "source_input_digest": canonical_digest(snapshot),
        "target_binding": "d" * 64,
        "run_binding": "e" * 64,
    }
    marker["receipt_digest"] = canonical_digest(marker)
    write_private_bytes(original.parent / "source-genesis.json", canonical_bytes(marker))
    write_profile(
        original.parent / "profile.json",
        ProvisionProfile(
            environment="dev",
            region="koreacentral",
            target_binding="d" * 64,
            connectivity="online",
            host="managed-vm",
            transport="manual",
            access_method="bastion",
            shadow_only=True,
            approval_quorum=1,
            monthly_cost_ceiling=500,
        ),
    )
    status = {"foundation_report": {"foundation_plan": {"plan_ref": original.name}}}
    write_private_bytes(original.parent / "status.json", canonical_bytes(status))
    review = {
        "schema_version": "fdai.foundation-recovery-review.v1",
        "source_commit": "a" * 40,
        "target_binding": "d" * 64,
    }
    review["review_digest"] = canonical_digest(review)
    write_private_bytes(recovery / "recovery-review.json", canonical_bytes(review))
    monkeypatch.setattr(admission, "verify_source_snapshot", lambda *_args, **_kwargs: snapshot)
    source = SimpleNamespace(root=tmp_path, commit="f" * 40, reverify=Mock())
    monkeypatch.setattr(recovery_runner, "inspect_source", lambda *_args: source)
    monkeypatch.setattr(admission, "inspect_source", lambda *_args: source)
    monkeypatch.setattr(
        recovery_runner,
        "load_recovery_evidence",
        lambda **_kwargs: SimpleNamespace(handoff={"run_digest": "e" * 64}),
    )
    monkeypatch.setattr(
        recovery_runner.GenesisChecks,
        "capture",
        lambda *_args, **_kwargs: "https://github.com/example/repository.git",
    )
    args = SimpleNamespace(
        work_dir=work,
        recovery_directory=recovery,
        runtime_profile_digest=profile.digest,
        region="koreacentral",
        monthly_cost_ceiling=500,
        timeout_seconds=14400,
        approval_file=None,
    )
    return args, source, profile


@pytest.mark.parametrize(
    "stage", ["needs-apply", "needs-enrollment", "enroll", "needs-state", "migrate", "completed"]
)
@pytest.mark.parametrize("image_defect", [None, "source", "incomplete", "ready"])
def test_source_recovery_retains_application_source_and_never_repeats_effects(
    source_recovery_run, monkeypatch, stage, image_defect
):
    from datetime import UTC, datetime, timedelta

    import source_recovery as recovery_runner

    args, source, profile = source_recovery_run
    recovery = args.recovery_directory
    original_status = (args.work_dir / "foundation/status.json").read_bytes()
    receipt = {"receipt_digest": "1" * 64}
    enrolled = {"schema_version": "fdai.genesis-runner-enrollment-receipt.v1", "state": "attested"}
    enrolled["receipt_digest"] = canonical_digest(enrolled)
    if stage != "needs-apply":
        write_private_bytes(recovery / "recovery-apply-receipt.json", canonical_bytes(receipt))
    if stage in {"needs-state", "migrate", "completed"}:
        write_private_bytes(recovery / "runner-enrollment-claim.json", canonical_bytes({}))
        write_private_bytes(recovery / "runner-enrollment-receipt.json", canonical_bytes(enrolled))
    if stage == "completed":
        write_private_bytes(recovery / "foundation-state-handoff-claim.json", canonical_bytes({}))
    if stage in {"enroll", "migrate"}:
        now = datetime.now(UTC).replace(microsecond=0)
        approval_stage = "runner-enrollment" if stage == "enroll" else "foundation-state"
        evidence = {"foundation_receipt_digest": "1" * 64}
        if stage == "migrate":
            evidence["enrollment_receipt_digest"] = enrolled["receipt_digest"]
        authority = {
            "schema_version": "fdai.genesis-approval.v1",
            "approved": True,
            "stage": approval_stage,
            "run_binding": "1" * 64,
            "source_commit": source.commit,
            "actor_digest": "2" * 64,
            "evidence": evidence,
            "approved_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=30)).isoformat(),
        }
        args.approval_file = recovery / "approval.json"
        write_private_bytes(args.approval_file, canonical_bytes(authority))
    calls = []

    def enroll(arguments):
        calls.append(("enroll", arguments.resume_verification))
        assert arguments.foundation_recovery_directory == recovery
        assert arguments.original_source_snapshot == args.work_dir / "source-snapshot"
        return enrolled

    def migrate(arguments):
        calls.append(("migrate", arguments.resume_verification))
        assert arguments.source_snapshot == args.work_dir / "source-snapshot"
        assert arguments.expected_enrollment_receipt_digest == enrolled["receipt_digest"]
        return {"receipt_digest": "3" * 64}

    monkeypatch.setattr(recovery_runner.enrollment_command, "_execute", enroll)
    monkeypatch.setattr(recovery_runner.state_command, "_execute", migrate)
    monkeypatch.setattr(
        recovery_runner, "prepare_recovery_migration", lambda *_args, **_kwargs: Mock()
    )
    transfers = []
    monkeypatch.setattr(
        recovery_runner,
        "transfer_application_source",
        lambda **kwargs: transfers.append(kwargs) or {"remote_transfer_verified": True},
    )
    image_calls = []

    def prepare_images(snapshot, destination, **kwargs):
        assert transfers
        assert snapshot == args.work_dir / "source-snapshot"
        assert destination == args.work_dir / "source-images"
        assert kwargs["snapshot_digest"] == "c" * 64
        assert 0 < kwargs["timeout_seconds"] <= args.timeout_seconds
        image_calls.append(snapshot)
        inventory = {
            "schema_version": "fdai.source-images.v1",
            "state": "built",
            "source_commit": source.commit if image_defect == "source" else "a" * 40,
            "snapshot_digest": "c" * 64,
            "provenance": "operator-selected-source",
            "services": {}
            if image_defect == "incomplete"
            else dict.fromkeys(recovery_runner.RUNTIME_SERVICES, {}),
            "registry_published": False,
            "dependency_images_verified": False,
            "apply_authorized": False,
            "deployment_ready": image_defect == "ready",
            "mutation_performed": False,
        }
        inventory["receipt_digest"] = canonical_digest(inventory)
        return inventory

    monkeypatch.setattr(recovery_runner, "build_source_images", prepare_images)
    if image_defect is not None and stage in {"migrate", "completed"}:
        with pytest.raises(ValueError, match="original application snapshot"):
            recovery_runner.resume(args)
        assert not list(recovery.glob("source-recovery-progress-*.json"))
        return
    result = recovery_runner.resume(args)
    assert result["source_commit"] == "a" * 40
    assert result["execution_source_commit"] == source.commit
    assert result["deployment_ready"] is False
    assert result["release_signature_verified"] is False
    assert (args.work_dir / "foundation/status.json").read_bytes() == original_status
    expected_calls = {
        "needs-apply": [],
        "needs-enrollment": [],
        "enroll": [("enroll", False)],
        "needs-state": [("enroll", True)],
        "migrate": [("enroll", True), ("migrate", False)],
        "completed": [("migrate", True)],
    }
    assert calls == expected_calls[stage]
    assert len(transfers) == (1 if stage in {"migrate", "completed"} else 0)
    if transfers:
        assert transfers[0]["source_commit"] == "a" * 40
        assert transfers[0]["snapshot"] == args.work_dir / "source-snapshot"
        assert image_calls == [args.work_dir / "source-snapshot"]
        assert result["source_images"]["source_commit"] == "a" * 40
        assert result["source_images"]["registry_published"] is False
    else:
        assert not image_calls
    assert result["stage"] == (
        "application-plan"
        if stage in {"migrate", "completed"}
        else "foundation-apply"
        if stage == "needs-apply"
        else "runner-enrollment"
        if stage == "needs-enrollment"
        else "foundation-state"
    )


@pytest.mark.parametrize(
    "field,value",
    [("region", "westus2"), ("monthly_cost_ceiling", 501), ("runtime_profile_digest", "0" * 64)],
)
def test_source_recovery_rejects_changed_original_settings(
    source_recovery_run, monkeypatch, field, value
):
    import source_recovery as recovery_runner

    args, _, _ = source_recovery_run
    setattr(args, field, value)
    monkeypatch.setattr(
        recovery_runner.enrollment_command, "_execute", lambda *_: pytest.fail("no effects")
    )
    with pytest.raises(ValueError, match="original installation settings"):
        recovery_runner.resume(args)


@pytest.mark.parametrize("tamper", [False, True])
def test_public_recovery_keeps_original_run_instead_of_preparing_new_source(
    source_recovery_run, monkeypatch, tamper
):
    import source_recovery as recovery_runner
    from fdai_deployment_cli import source_azure

    args, source, profile = source_recovery_run
    monkeypatch.setattr(
        source_azure,
        "prepare_source_deployment",
        lambda **_: pytest.fail("must not prepare or rewrite original source"),
    )

    def capture(command, root, environment, timeout):
        assert Path(command[1]).name == "source_recovery.py"
        assert root == source.root
        assert environment["PYTHONPATH"] == str(source.root / "packages/deployment-cli/src")
        assert 0 < timeout <= args.timeout_seconds
        result = recovery_runner.resume(args)
        if tamper:
            result["execution_source_commit"] = "0" * 40
            result["receipt_digest"] = canonical_digest(
                {key: value for key, value in result.items() if key != "receipt_digest"}
            )
        return result

    monkeypatch.setattr(source_azure, "_capture", capture)
    parameters = dict(
        source_root=source.root,
        work_dir=args.work_dir,
        foundation_recovery_directory=args.recovery_directory,
        runtime_profile=profile,
        region=args.region,
        monthly_cost_ceiling=args.monthly_cost_ceiling,
        timeout_seconds=args.timeout_seconds,
    )
    if tamper:
        with pytest.raises(ValueError, match="different execution context"):
            source_azure.plan_source_installation(**parameters)
    else:
        result = source_azure.plan_source_installation(**parameters)
        assert result["source_commit"] == "a" * 40
        assert result["execution_source_commit"] == "f" * 40
        assert result["stage"] == "foundation-apply"


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


@pytest.mark.parametrize("mismatch", [False, True])
def test_recovered_transfer_never_fabricates_ordinary_foundation(source_transfer, mismatch):
    arguments, calls, _, directory = source_transfer
    foundation_path = directory / "foundation-apply-receipt.json"
    handoff_path = directory / "foundation-private-handoff.json"
    foundation, handoff = (
        json.loads(foundation_path.read_bytes()),
        json.loads(handoff_path.read_bytes()),
    )
    foundation_path.unlink()
    handoff_path.unlink()
    context = SimpleNamespace(
        original_directory=directory,
        directory=directory,
        foundation=foundation,
        recovered=SimpleNamespace(
            receipt=foundation, handoff=handoff, target_binding=arguments["target_binding"]
        ),
        verify_configuration=Mock(),
        validate_record=Mock(),
    )
    if mismatch:
        context.recovered.target_binding = "0" * 64
        with pytest.raises(ValueError, match="recovery context differs"):
            transport.transfer_application_source(**arguments, recovery=context)
        assert not calls
        return
    result = transport.transfer_application_source(**arguments, recovery=context)
    assert result["remote_transfer_verified"] is True
    assert result["source_commit"] == arguments["source_commit"]
    assert not foundation_path.exists()
    assert not handoff_path.exists()
    context.validate_record.assert_called_once()


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

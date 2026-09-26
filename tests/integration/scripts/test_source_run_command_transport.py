from __future__ import annotations

import hashlib
import json
import os
import ssl
import stat
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

import run_command_authority as authority  # noqa: E402
import run_command_transfer as implementation  # noqa: E402
import source_run_command_authority as authority_cli  # noqa: E402
import source_run_command_transport as transport  # noqa: E402
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest  # noqa: E402
from fdai_deployment_cli.private_output import write_private_bytes  # noqa: E402
from fdai_deployment_cli.target import compute_target_binding  # noqa: E402
from run_command_private_relay import PrivateRelay, _anonymous_file  # noqa: E402


@pytest.fixture(autouse=True)
def _approved_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        implementation,
        "validate_transport_authority",
        lambda **_kwargs: "f" * 64,
    )
    monkeypatch.setattr(
        implementation,
        "validate_delegated_transport_authority",
        lambda **_kwargs: "f" * 64,
    )
    monkeypatch.setattr(
        implementation,
        "require_approval_current",
        lambda *_args, **_kwargs: None,
    )


def _transfer_execution_bundle(**kwargs: Any) -> dict[str, object]:
    return transport.transfer_execution_bundle(
        **kwargs,
        profile={"schema_version": "test-profile"},
        approval={"schema_version": "test-approval"},
    )


def _parameters() -> dict[str, object]:
    return {
        "bundle_digest": "a" * 64,
        "bundle_size": 4096,
        "claim_digest": "d" * 64,
        "file_count": 9,
        "inventory_digest": "c" * 64,
        "operation_id": "historical-aks-recovery",
        "recovery_mode": "fresh",
        "receiver_digest": "b" * 64,
        "relay_certificate_digest": "e" * 64,
        "relay_host": "10.10.0.4",
        "relay_port": 58443,
    }


def _target() -> dict[str, object]:
    return {
        "schema_version": "fdai.run-command-private-relay-target.v1",
        "subscription_id": "00000000-0000-0000-0000-000000000002",
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "resource_group": "rg-example",
        "vm_name": "vm-example",
        "vm_resource_id": (
            "/subscriptions/00000000-0000-0000-0000-000000000002/"
            "resourceGroups/rg-example/providers/Microsoft.Compute/virtualMachines/vm-example"
        ),
        "identity_client_id": "00000000-0000-0000-0000-000000000003",
        "identity_principal_id": "00000000-0000-0000-0000-000000000004",
        "relay_private_ip": "10.10.0.4",
        "relay_port": 58443,
        "host_private_ip": "10.20.0.5",
        "target_binding": "d" * 64,
    }


def _authority_inputs() -> tuple[dict[str, object], dict[str, object], dict[str, object], datetime]:
    tenant = "00000000-0000-0000-0000-000000000001"
    subscription = "00000000-0000-0000-0000-000000000002"
    target = _target()
    target["target_binding"] = compute_target_binding(
        tenant_id=tenant, subscription_id=subscription
    )
    profile = {
        "schema_version": "fdai.provision-profile.v1",
        "environment": "dev",
        "region": "westus2",
        "target_binding": target["target_binding"],
        "connectivity": "online",
        "host": "existing-host",
        "transport": "manual",
        "access_method": "run_command",
        "shadow_only": True,
        "approval_quorum": 1,
        "monthly_cost_ceiling": 0,
    }
    moment = datetime(2026, 9, 19, 12, tzinfo=UTC)
    document: dict[str, object] = {
        "schema_version": "fdai.run-command-private-relay-approval.v1",
        "decision": "approved",
        "target_binding": target["target_binding"],
        "target_digest": canonical_digest(target),
        "profile_digest": canonical_digest(profile),
        "operation_id": "historical-aks-recovery",
        "bundle_receipt_digest": "e" * 64,
        "receiver_digest": "b" * 64,
        "actor_digest": hashlib.sha256(
            f"{target['target_binding']}:operator@example.com".encode()
        ).hexdigest(),
        "approved_at": moment.isoformat(),
        "expires_at": (moment + timedelta(minutes=30)).isoformat(),
    }
    document["approval_digest"] = canonical_digest(document)
    return target, profile, document, moment + timedelta(minutes=1)


def _authority_capture(command: tuple[str, ...], **_kwargs: object) -> str:
    if command[:3] == ("az", "account", "show"):
        return json.dumps(
            {
                "subscription_id": "00000000-0000-0000-0000-000000000002",
                "tenant_id": "00000000-0000-0000-0000-000000000001",
                "user_name": "operator@example.com",
                "user_type": "user",
            }
        )
    return json.dumps(
        {
            "id": (
                "/subscriptions/00000000-0000-0000-0000-000000000002/"
                "resourceGroups/rg-example/providers/Microsoft.Compute/"
                "virtualMachines/vm-example"
            ),
            "private_ips": "10.20.0.5",
            "identities": {
                "/subscriptions/example/resourceGroups/example/providers/"
                "Microsoft.ManagedIdentity/userAssignedIdentities/example": {
                    "clientId": "00000000-0000-0000-0000-000000000003",
                    "principalId": "00000000-0000-0000-0000-000000000004",
                }
            },
        }
    )


def _executor_authority_capture(command: tuple[str, ...], **_kwargs: object) -> str:
    if command[:3] == ("az", "account", "show"):
        return json.dumps(
            {
                "subscription_id": "00000000-0000-0000-0000-000000000002",
                "tenant_id": "00000000-0000-0000-0000-000000000001",
                "user_type": "servicePrincipal",
            }
        )
    if command[:3] == ("az", "account", "get-access-token"):
        header = "eyJhbGciOiJub25lIn0"
        payload = "eyJvaWQiOiIwMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAwMDAwMDQifQ"
        return f"{header}.{payload}.signature"
    return _authority_capture(command, **_kwargs)


def _host_result(bundle_digest: str = "a" * 64, claim_digest: str = "d" * 64) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": "fdai.run-command-bundle-host-result.v1",
        "state": "verified",
        "operation_id": "historical-aks-recovery",
        "bundle_digest": bundle_digest,
        "claim_digest": claim_digest,
        "file_count": 9,
        "inventory_digest": "c" * 64,
        "mutation_performed": False,
    }
    result["receipt_digest"] = canonical_digest(result)
    return result


def _transfer_inputs(tmp_path: Path) -> tuple[Path, Path, dict[str, object], Path, str]:
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    bundle = tmp_path / "bundle.tar.gz"
    bundle.write_bytes(b"bundle")
    bundle.chmod(0o600)
    bundle_digest = hashlib.sha256(b"bundle").hexdigest()
    receiver = tmp_path / "receiver.pyz"
    receiver.write_bytes(b"receiver")
    receiver.chmod(0o600)
    bundle_receipt: dict[str, object] = {
        "schema_version": "fdai.execution-bundle-receipt.v1",
        "state": "prepared",
        "operation_id": "historical-aks-recovery",
        "bundle_digest": bundle_digest,
        "bundle_size": len(b"bundle"),
        "file_count": 9,
        "inventory_digest": "c" * 64,
        "apply_authorized": False,
        "deployment_ready": False,
        "mutation_performed": False,
    }
    bundle_receipt["receipt_digest"] = canonical_digest(bundle_receipt)
    return work, bundle, bundle_receipt, receiver, hashlib.sha256(b"receiver").hexdigest()


def _command_response() -> str:
    return json.dumps(
        {
            "value": [
                {
                    "code": "ComponentStatus/StdOut/succeeded",
                    "level": "Info",
                    "message": "FDAI_RUN_COMMAND_COMPLETED=true",
                },
                {
                    "code": "ComponentStatus/StdErr/succeeded",
                    "level": "Info",
                    "message": "",
                },
            ]
        }
    )


class _FakeRelay:
    certificate_digest = "e" * 64

    def __init__(self, content: bytes, work: Path) -> None:
        self.content = content
        self.work = work
        self.started = False
        self.closed = False

    def start(self) -> None:
        assert (self.work / "run-command-bundle-transfer-claim.json").is_file()
        assert any(self.work.glob("run-command-bundle-*-claim.json"))
        self.started = True

    def result(self) -> bytes:
        assert self.started
        return self.content

    def close(self) -> None:
        self.closed = True


def _fake_relay_factory(work: Path, bundle_digest: str) -> Any:
    def factory(**_kwargs: object) -> _FakeRelay:
        claim = json.loads((work / "run-command-bundle-transfer-claim.json").read_text())
        result = _host_result(bundle_digest, canonical_digest(claim))
        return _FakeRelay(canonical_bytes(result), work)

    return factory


def test_run_command_uses_fixed_script_and_allowlisted_parameters() -> None:
    command = transport.build_run_command(
        vm_resource_id=str(_target()["vm_resource_id"]),
        parameters=_parameters(),
    )

    script_index = command.index("--scripts") + 1
    parameter_index = command.index("--parameters") + 1
    assert command[script_index] == transport.POWERSHELL_BOOTSTRAP
    assert set(command[parameter_index:]) == {
        f"{name}={value}" for name, value in _parameters().items()
    }
    serialized = " ".join(command[parameter_index:]).casefold()
    assert "token" not in serialized
    assert "password" not in serialized
    assert "storage" not in serialized
    assert "blob" not in serialized
    assert "169.254.169.254" not in transport.POWERSHELL_BOOTSTRAP
    assert "--cacert" in transport.POWERSHELL_BOOTSTRAP
    assert "FDAI_RELAY_CERTIFICATE_DIGEST" in transport.POWERSHELL_BOOTSTRAP
    assert 'test ! -L "$root"' in transport.POWERSHELL_BOOTSTRAP
    assert "-printf '%f\\n'" in transport.POWERSHELL_BOOTSTRAP


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("relay_host", "10.10.0.4; curl example.invalid"),
        ("operation_id", "value; curl example.invalid"),
        ("token", "secret"),
        ("script", "Write-Output injected"),
    ],
)
def test_run_command_rejects_non_allowlisted_or_hostile_parameters(field: str, value: str) -> None:
    parameters = _parameters()
    parameters[field] = value

    with pytest.raises(ValueError, match="parameter|relay"):
        transport.build_run_command(
            vm_resource_id=str(_target()["vm_resource_id"]),
            parameters=parameters,
        )


def test_transport_authority_binds_profile_actor_and_live_vm() -> None:
    target, profile, approval, now = _authority_inputs()

    digest = authority.validate_transport_authority(
        target=target,
        profile_value=profile,
        approval=approval,
        operation_id="historical-aks-recovery",
        bundle_receipt_digest="e" * 64,
        receiver_digest="b" * 64,
        capture=_authority_capture,
        deadline=authority.DeploymentDeadline(600),
        now=now,
    )

    assert digest == approval["approval_digest"]


def test_transport_authority_receipt_delegates_to_exact_managed_identity() -> None:
    target, profile, approval, now = _authority_inputs()
    receipt = authority.capture_transport_authority(
        target=target,
        profile_value=profile,
        approval=approval,
        operation_id="historical-aks-recovery",
        bundle_receipt_digest="e" * 64,
        receiver_digest="b" * 64,
        capture=_authority_capture,
        deadline=authority.DeploymentDeadline(600),
        now=now,
    )

    digest = authority.validate_delegated_transport_authority(
        target=target,
        profile_value=profile,
        approval=approval,
        authority_receipt=receipt,
        operation_id="historical-aks-recovery",
        bundle_receipt_digest="e" * 64,
        receiver_digest="b" * 64,
        capture=_executor_authority_capture,
        deadline=authority.DeploymentDeadline(600),
        now=now,
    )

    assert digest == approval["approval_digest"]
    assert receipt["human_actor_verified"] is True
    assert receipt["vm_readback_verified"] is True
    assert receipt["mutation_performed"] is False


@pytest.mark.parametrize("drift", ["payload", "executor"])
def test_delegated_transport_authority_rejects_drift_before_effect(drift: str) -> None:
    target, profile, approval, now = _authority_inputs()
    receipt = authority.capture_transport_authority(
        target=target,
        profile_value=profile,
        approval=approval,
        operation_id="historical-aks-recovery",
        bundle_receipt_digest="e" * 64,
        receiver_digest="b" * 64,
        capture=_authority_capture,
        deadline=authority.DeploymentDeadline(600),
        now=now,
    )
    bundle_receipt_digest = "9" * 64 if drift == "payload" else "e" * 64

    def capture(command: tuple[str, ...], **kwargs: object) -> str:
        if drift == "executor" and command[:3] == ("az", "account", "get-access-token"):
            header = "eyJhbGciOiJub25lIn0"
            payload = "eyJvaWQiOiIwMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAwMDAwMDkifQ"
            return f"{header}.{payload}.signature"
        return _executor_authority_capture(command, **kwargs)

    with pytest.raises(ValueError, match="authority|executor|approval"):
        authority.validate_delegated_transport_authority(
            target=target,
            profile_value=profile,
            approval=approval,
            authority_receipt=receipt,
            operation_id="historical-aks-recovery",
            bundle_receipt_digest=bundle_receipt_digest,
            receiver_digest="b" * 64,
            capture=capture,
            deadline=authority.DeploymentDeadline(600),
            now=now,
        )


def test_transport_authority_rejects_target_drift_before_readback() -> None:
    target, profile, approval, now = _authority_inputs()
    target["host_private_ip"] = "10.20.0.6"

    with pytest.raises(ValueError, match="approval"):
        authority.validate_transport_authority(
            target=target,
            profile_value=profile,
            approval=approval,
            operation_id="historical-aks-recovery",
            bundle_receipt_digest="e" * 64,
            receiver_digest="b" * 64,
            capture=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("drift must fail before Azure readback")
            ),
            deadline=authority.DeploymentDeadline(600),
            now=now,
        )


def test_transport_authority_rejects_bundle_receipt_drift_before_readback() -> None:
    target, profile, approval, now = _authority_inputs()

    with pytest.raises(ValueError, match="approval"):
        authority.validate_transport_authority(
            target=target,
            profile_value=profile,
            approval=approval,
            operation_id="historical-aks-recovery",
            bundle_receipt_digest="9" * 64,
            receiver_digest="b" * 64,
            capture=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("payload drift must fail before Azure readback")
            ),
            deadline=authority.DeploymentDeadline(600),
            now=now,
        )


def test_transport_authority_rejects_non_dev_quorum_profile() -> None:
    target, profile, approval, now = _authority_inputs()
    profile["environment"] = "prod"
    profile["approval_quorum"] = 2

    with pytest.raises(ValueError, match="profile"):
        authority.validate_transport_authority(
            target=target,
            profile_value=profile,
            approval=approval,
            operation_id="historical-aks-recovery",
            bundle_receipt_digest="e" * 64,
            receiver_digest="b" * 64,
            capture=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("non-dev profile must fail before Azure readback")
            ),
            deadline=authority.DeploymentDeadline(600),
            now=now,
        )


def test_transport_authority_uses_shared_deadline() -> None:
    target, profile, approval, now = _authority_inputs()
    timeouts: list[int] = []

    def capture(command: tuple[str, ...], *, timeout: int) -> str:
        timeouts.append(timeout)
        return _authority_capture(command, timeout=timeout)

    authority.validate_transport_authority(
        target=target,
        profile_value=profile,
        approval=approval,
        operation_id="historical-aks-recovery",
        bundle_receipt_digest="e" * 64,
        receiver_digest="b" * 64,
        capture=capture,
        deadline=authority.DeploymentDeadline(5),
        now=now,
    )

    assert len(timeouts) == 2
    assert all(1 <= timeout <= 5 for timeout in timeouts)


def test_transport_rejects_approval_expired_at_effect_boundary() -> None:
    _target_value, _profile, approval, now = _authority_inputs()

    with pytest.raises(ValueError, match="expired"):
        authority.require_approval_current(
            approval,
            now=now + timedelta(hours=1),
        )


def test_private_relay_serves_exact_files_and_accepts_one_result(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.tar.gz"
    bundle.write_bytes(b"bundle")
    bundle.chmod(0o600)
    receiver = tmp_path / "receiver.pyz"
    receiver.write_bytes(b"receiver")
    receiver.chmod(0o600)
    result = canonical_bytes(_host_result())
    relay = PrivateRelay(
        relay_host="127.0.0.1",
        relay_port=0,
        allowed_source="127.0.0.1",
        operation_id="historical-aks-recovery",
        bundle=bundle,
        bundle_digest=hashlib.sha256(b"bundle").hexdigest(),
        receiver=receiver,
        receiver_digest=hashlib.sha256(b"receiver").hexdigest(),
    )
    relay.start()
    base = f"https://127.0.0.1:{relay.port}/historical-aks-recovery"
    unverified = ssl.create_default_context()
    unverified.check_hostname = False
    unverified.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(  # noqa: S310 - fixed loopback TLS relay
            f"{base}/certificate.pem", context=unverified, timeout=5
        ) as response:
            certificate = response.read()
        assert hashlib.sha256(certificate).hexdigest() == relay.certificate_digest
        certificate_path = tmp_path / "relay-certificate.pem"
        certificate_path.write_bytes(certificate)
        certificate_path.chmod(0o600)
        verified = ssl.create_default_context(cafile=str(certificate_path))
        with urllib.request.urlopen(  # noqa: S310 - fixed loopback TLS relay
            f"{base}/receiver.pyz", context=verified, timeout=5
        ) as response:
            assert response.read() == b"receiver"
        with urllib.request.urlopen(  # noqa: S310 - fixed loopback TLS relay
            f"{base}/bundle.tar.gz", context=verified, timeout=5
        ) as response:
            assert response.read() == b"bundle"
        request = urllib.request.Request(  # noqa: S310 - fixed loopback TLS relay
            f"{base}/host-result.json",
            data=result,
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(  # noqa: S310 - fixed loopback TLS relay
            request, context=verified, timeout=5
        ) as response:
            assert response.status == 204
        assert relay.result() == result
    finally:
        relay.close()


def test_private_relay_verify_mode_requires_no_bundle_download(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.tar.gz"
    bundle.write_bytes(b"bundle")
    bundle.chmod(0o600)
    receiver = tmp_path / "receiver.pyz"
    receiver.write_bytes(b"receiver")
    receiver.chmod(0o600)
    result = canonical_bytes(_host_result())
    relay = PrivateRelay(
        relay_host="127.0.0.1",
        relay_port=0,
        allowed_source="127.0.0.1",
        operation_id="historical-aks-recovery",
        bundle=bundle,
        bundle_digest=hashlib.sha256(b"bundle").hexdigest(),
        receiver=receiver,
        receiver_digest=hashlib.sha256(b"receiver").hexdigest(),
        require_bundle=False,
    )
    relay.start()
    base = f"https://127.0.0.1:{relay.port}/historical-aks-recovery"
    unverified = ssl.create_default_context()
    unverified.check_hostname = False
    unverified.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(  # noqa: S310 - fixed loopback TLS relay
            f"{base}/certificate.pem", context=unverified, timeout=5
        ) as response:
            certificate = response.read()
        certificate_path = tmp_path / "verify-certificate.pem"
        certificate_path.write_bytes(certificate)
        certificate_path.chmod(0o600)
        verified = ssl.create_default_context(cafile=str(certificate_path))
        with urllib.request.urlopen(  # noqa: S310 - fixed loopback TLS relay
            f"{base}/receiver.pyz", context=verified, timeout=5
        ) as response:
            assert response.read() == b"receiver"
        request = urllib.request.Request(  # noqa: S310 - fixed loopback TLS relay
            f"{base}/host-result.json",
            data=result,
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(  # noqa: S310 - fixed loopback TLS relay
            request, context=verified, timeout=5
        ) as response:
            assert response.status == 204
        assert relay.result() == result
    finally:
        relay.close()


def test_private_relay_anonymous_file_falls_back_without_memfd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(os, "memfd_create", raising=False)

    descriptor = _anonymous_file("fdai-relay-test")
    try:
        details = os.fstat(descriptor)
        assert stat.S_ISREG(details.st_mode)
        assert stat.S_IMODE(details.st_mode) == 0o600
        assert details.st_nlink == 0
        assert os.get_inheritable(descriptor) is False
    finally:
        os.close(descriptor)


def test_host_result_binds_exact_bundle_and_operation() -> None:
    result = _host_result()
    validated = transport.validate_host_result(
        canonical_bytes(result),
        operation_id="historical-aks-recovery",
        bundle_digest="a" * 64,
        claim_digest="d" * 64,
        file_count=9,
        inventory_digest="c" * 64,
    )
    assert validated == result


def test_transfer_claims_before_relay_and_creates_no_cloud_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, bundle, receipt, receiver, receiver_digest = _transfer_inputs(tmp_path)
    commands: list[tuple[str, ...]] = []

    def capture(command: tuple[str, ...], **_kwargs: object) -> str:
        commands.append(command)
        assert (work / "run-command-bundle-transfer-claim.json").is_file()
        assert (work / "run-command-bundle-invocation-claim.json").is_file()
        return _command_response()

    monkeypatch.setattr(transport, "_capture", capture)
    monkeypatch.setattr(
        transport,
        "_relay_factory",
        _fake_relay_factory(work, str(receipt["bundle_digest"])),
    )

    result = _transfer_execution_bundle(
        work_dir=work,
        bundle=bundle,
        bundle_receipt=receipt,
        receiver=receiver,
        receiver_digest=receiver_digest,
        target=_target(),
        timeout_seconds=600,
    )

    assert result["state"] == "verified"
    assert result["cloud_artifact_residue_created"] is False
    assert result["relay_tls_pinned"] is True
    assert result["relay_source_address_verified"] is True
    assert result["host_download_cleanup_verified"] is True
    assert len(commands) == 1
    assert commands[0][:4] == ("az", "vm", "run-command", "invoke")
    assert not any("storage" in part or "blob" in part for part in commands[0])


def test_transfer_uses_delegated_authority_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, bundle, receipt, receiver, receiver_digest = _transfer_inputs(tmp_path)
    observed: list[dict[str, object]] = []

    def delegated(**kwargs: object) -> str:
        observed.append(kwargs)
        return "f" * 64

    monkeypatch.setattr(implementation, "validate_delegated_transport_authority", delegated)
    monkeypatch.setattr(
        implementation,
        "validate_transport_authority",
        lambda **_kwargs: pytest.fail("delegated receipt must not use local actor validation"),
    )
    monkeypatch.setattr(transport, "_capture", lambda *_args, **_kwargs: _command_response())
    monkeypatch.setattr(
        transport,
        "_relay_factory",
        _fake_relay_factory(work, str(receipt["bundle_digest"])),
    )
    authority_receipt = {
        "schema_version": "fdai.test-authority-receipt.v1",
        "receipt_digest": "8" * 64,
    }

    result = _transfer_execution_bundle(
        work_dir=work,
        bundle=bundle,
        bundle_receipt=receipt,
        receiver=receiver,
        receiver_digest=receiver_digest,
        target=_target(),
        authority_receipt=authority_receipt,
        timeout_seconds=600,
    )

    assert result["state"] == "verified"
    assert observed[0]["authority_receipt"] is authority_receipt
    claim = json.loads((work / "run-command-bundle-transfer-claim.json").read_text())
    assert claim["schema_version"] == "fdai.run-command-private-relay-transfer-claim.v2"
    assert claim["authority_receipt_digest"] == authority_receipt["receipt_digest"]


def test_authority_cli_derives_immutable_artifact_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _work, _bundle, bundle_receipt, receiver, receiver_digest = _transfer_inputs(tmp_path)
    target, profile, approval, _now = _authority_inputs()
    paths = {
        "target": tmp_path / "target.json",
        "profile": tmp_path / "profile.json",
        "approval": tmp_path / "approval.json",
        "bundle_receipt": tmp_path / "bundle-receipt.json",
    }
    for name, value in (
        ("target", target),
        ("profile", profile),
        ("approval", approval),
        ("bundle_receipt", bundle_receipt),
    ):
        write_private_bytes(paths[name], canonical_bytes(value))
    observed: list[dict[str, object]] = []

    def capture(**kwargs: object) -> dict[str, object]:
        observed.append(kwargs)
        return {"schema_version": "fdai.test-authority-receipt.v1"}

    monkeypatch.setattr(authority_cli, "capture_transport_authority", capture)
    output = tmp_path / "authority-receipt.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "source_run_command_authority.py",
            "--target",
            str(paths["target"]),
            "--profile",
            str(paths["profile"]),
            "--approval",
            str(paths["approval"]),
            "--bundle-receipt",
            str(paths["bundle_receipt"]),
            "--receiver",
            str(receiver),
            "--output",
            str(output),
        ],
    )

    assert authority_cli.main() == 0
    assert observed[0]["operation_id"] == bundle_receipt["operation_id"]
    assert observed[0]["bundle_receipt_digest"] == bundle_receipt["receipt_digest"]
    assert observed[0]["receiver_digest"] == receiver_digest
    assert output.stat().st_mode & 0o077 == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == (
        "fdai.test-authority-receipt.v1"
    )


def test_transfer_work_directory_allows_only_one_active_coordinator(
    tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    first = implementation._private_directory(work)
    implementation._acquire_work_lock(first)
    second = implementation._private_directory(work)
    try:
        with pytest.raises(ValueError, match="already active"):
            implementation._acquire_work_lock(second)
    finally:
        implementation.fcntl.flock(first, implementation.fcntl.LOCK_UN)
        implementation.os.close(first)
        implementation.os.close(second)


def test_pre_effect_claim_syncs_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    synced_types: list[str] = []
    original_fsync = implementation.os.fsync

    def fsync(descriptor: int) -> None:
        details = implementation.os.fstat(descriptor)
        synced_types.append("directory" if stat.S_ISDIR(details.st_mode) else "file")
        original_fsync(descriptor)

    monkeypatch.setattr(implementation.os, "fsync", fsync)
    directory = implementation._private_directory(work)
    try:
        implementation._write_durable_private(directory, "claim.json", b"{}")
    finally:
        implementation.os.close(directory)

    assert synced_types[-1] == "directory"


def test_transfer_lock_survives_work_directory_replacement(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    retained_descriptor = implementation._private_directory(work)
    implementation._acquire_work_lock(retained_descriptor)
    moved = tmp_path / "moved"
    work.rename(moved)
    alias_descriptor = implementation._private_directory(moved)
    try:
        with pytest.raises(ValueError, match="already active"):
            implementation._acquire_work_lock(alias_descriptor)
        work.mkdir(mode=0o700)
        with pytest.raises(ValueError, match="identity changed"):
            implementation._require_work_directory_identity(work, retained_descriptor)
    finally:
        implementation.fcntl.flock(retained_descriptor, implementation.fcntl.LOCK_UN)
        implementation.os.close(alias_descriptor)
        implementation.os.close(retained_descriptor)


def test_verification_bootstrap_removes_only_download_transients() -> None:
    script = transport.POWERSHELL_BOOTSTRAP
    verify_branch = script.index('if [ "$FDAI_RECOVERY_MODE" = verify ]; then')
    transient_removal = script.index('rm -f "$certificate"', verify_branch)
    absence_check = script.index('for transient in "$certificate"', transient_removal)

    assert verify_branch < transient_removal < absence_check
    assert 'rm -rf "$root/execution"' not in script
    root_sync = script.index("descriptor=os.open(sys.argv[1]", absence_check)
    completed = script.index("FDAI_RUN_COMMAND_COMPLETED=true", root_sync)
    assert absence_check < root_sync < completed
    fresh_branch = script.index('if [ "$FDAI_RECOVERY_MODE" = fresh ]; then', absence_check)
    verify_branch_body = script.index("else", fresh_branch)
    branch_end = script.index("fi", verify_branch_body)
    assert "download bundle.tar.gz" in script[fresh_branch:verify_branch_body]
    assert "download bundle.tar.gz" not in script[verify_branch_body:branch_end]
    assert "--verify-existing" in script[verify_branch_body:branch_end]


def test_completed_transfer_reconstructs_receipt_without_reinvocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, bundle, receipt, receiver, receiver_digest = _transfer_inputs(tmp_path)
    monkeypatch.setattr(transport, "_capture", lambda *_args, **_kwargs: _command_response())
    monkeypatch.setattr(
        transport,
        "_relay_factory",
        _fake_relay_factory(work, str(receipt["bundle_digest"])),
    )
    first = _transfer_execution_bundle(
        work_dir=work,
        bundle=bundle,
        bundle_receipt=receipt,
        receiver=receiver,
        receiver_digest=receiver_digest,
        target=_target(),
        timeout_seconds=600,
    )

    def forbidden(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("completed transfer must not invoke another effect")

    monkeypatch.setattr(transport, "_capture", forbidden)
    monkeypatch.setattr(transport, "_relay_factory", forbidden)
    second = _transfer_execution_bundle(
        work_dir=work,
        bundle=bundle,
        bundle_receipt=receipt,
        receiver=receiver,
        receiver_digest=receiver_digest,
        target=_target(),
        timeout_seconds=600,
    )
    assert second == first


def test_ambiguous_fresh_invocation_recovers_once_in_verify_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, bundle, receipt, receiver, receiver_digest = _transfer_inputs(tmp_path)
    monkeypatch.setattr(
        transport,
        "_relay_factory",
        _fake_relay_factory(work, str(receipt["bundle_digest"])),
    )

    def fail_fresh(*_args: object, **_kwargs: object) -> str:
        raise ValueError("ambiguous invocation")

    monkeypatch.setattr(transport, "_capture", fail_fresh)
    with pytest.raises(ValueError, match="ambiguous invocation"):
        _transfer_execution_bundle(
            work_dir=work,
            bundle=bundle,
            bundle_receipt=receipt,
            receiver=receiver,
            receiver_digest=receiver_digest,
            target=_target(),
            timeout_seconds=600,
        )

    commands: list[tuple[str, ...]] = []

    def capture_verify(command: tuple[str, ...], **_kwargs: object) -> str:
        commands.append(command)
        assert "recovery_mode=verify" in command
        assert (work / "run-command-bundle-recovery-claim.json").is_file()
        return _command_response()

    monkeypatch.setattr(transport, "_capture", capture_verify)
    result = _transfer_execution_bundle(
        work_dir=work,
        bundle=bundle,
        bundle_receipt=receipt,
        receiver=receiver,
        receiver_digest=receiver_digest,
        target=_target(),
        timeout_seconds=600,
    )
    assert result["state"] == "verified"
    assert len(commands) == 1


def test_malformed_result_is_quarantined_before_verify_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, bundle, receipt, receiver, receiver_digest = _transfer_inputs(tmp_path)
    monkeypatch.setattr(
        transport,
        "_relay_factory",
        _fake_relay_factory(work, str(receipt["bundle_digest"])),
    )
    monkeypatch.setattr(
        transport,
        "_capture",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("ambiguous")),
    )
    with pytest.raises(ValueError, match="ambiguous"):
        _transfer_execution_bundle(
            work_dir=work,
            bundle=bundle,
            bundle_receipt=receipt,
            receiver=receiver,
            receiver_digest=receiver_digest,
            target=_target(),
            timeout_seconds=600,
        )
    write_private_bytes(work / "run-command-host-result.json", b"{}")
    monkeypatch.setattr(transport, "_capture", lambda *_args, **_kwargs: _command_response())

    result = _transfer_execution_bundle(
        work_dir=work,
        bundle=bundle,
        bundle_receipt=receipt,
        receiver=receiver,
        receiver_digest=receiver_digest,
        target=_target(),
        timeout_seconds=600,
    )
    assert result["state"] == "verified"
    assert len(list(work.glob("run-command-host-result.invalid-*.json"))) == 1


def test_recovery_claim_prevents_a_second_verification_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, bundle, receipt, receiver, receiver_digest = _transfer_inputs(tmp_path)
    monkeypatch.setattr(
        transport,
        "_relay_factory",
        _fake_relay_factory(work, str(receipt["bundle_digest"])),
    )
    monkeypatch.setattr(
        transport,
        "_capture",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("ambiguous")),
    )
    for _attempt in range(2):
        with pytest.raises(ValueError, match="ambiguous"):
            _transfer_execution_bundle(
                work_dir=work,
                bundle=bundle,
                bundle_receipt=receipt,
                receiver=receiver,
                receiver_digest=receiver_digest,
                target=_target(),
                timeout_seconds=600,
            )

    def forbidden(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("claimed recovery must not be repeated")

    monkeypatch.setattr(transport, "_capture", forbidden)
    monkeypatch.setattr(transport, "_relay_factory", forbidden)
    with pytest.raises(ValueError, match="recovery is already claimed"):
        _transfer_execution_bundle(
            work_dir=work,
            bundle=bundle,
            bundle_receipt=receipt,
            receiver=receiver,
            receiver_digest=receiver_digest,
            target=_target(),
            timeout_seconds=600,
        )


def test_transfer_claim_binds_target_coordinates() -> None:
    parameters = _parameters()
    first = transport.transfer_claim(
        parameters=parameters,
        target=_target(),
        bundle_receipt_digest="e" * 64,
        approval_digest="f" * 64,
        profile_digest="1" * 64,
    )
    changed = _target()
    changed["host_private_ip"] = "10.20.0.6"
    second = transport.transfer_claim(
        parameters=parameters,
        target=changed,
        bundle_receipt_digest="e" * 64,
        approval_digest="f" * 64,
        profile_digest="1" * 64,
    )
    assert first["target_digest"] != second["target_digest"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("relay_private_ip", "169.254.1.1"),
        ("host_private_ip", "192.0.2.10"),
        ("host_private_ip", "10.10.0.4"),
    ],
)
def test_target_rejects_non_rfc1918_or_same_host_addresses(field: str, value: str) -> None:
    target = _target()
    target[field] = value

    with pytest.raises(ValueError, match="target|relay"):
        transport.transfer_parameters(
            operation_id="historical-aks-recovery",
            bundle_digest="a" * 64,
            bundle_size=4096,
            receiver_digest="b" * 64,
            file_count=9,
            inventory_digest="c" * 64,
            target=target,
        )


def test_forged_retained_receipt_cannot_bypass_invocation_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, bundle, receipt, receiver, receiver_digest = _transfer_inputs(tmp_path)
    parameters = transport.transfer_parameters(
        operation_id="historical-aks-recovery",
        bundle_digest=str(receipt["bundle_digest"]),
        bundle_size=len(b"bundle"),
        receiver_digest=receiver_digest,
        file_count=9,
        inventory_digest="c" * 64,
        target=_target(),
    )
    claim = transport.transfer_claim(
        parameters=parameters,
        target=_target(),
        bundle_receipt_digest=str(receipt["receipt_digest"]),
        approval_digest="f" * 64,
        profile_digest=canonical_digest({"schema_version": "test-profile"}),
    )
    write_private_bytes(work / "run-command-bundle-transfer-claim.json", canonical_bytes(claim))
    forged: dict[str, object] = {
        "schema_version": "fdai.run-command-private-relay-transfer-receipt.v1",
        "state": "verified",
    }
    forged["receipt_digest"] = canonical_digest(forged)
    write_private_bytes(work / "run-command-bundle-transfer-receipt.json", canonical_bytes(forged))
    monkeypatch.setattr(
        transport,
        "_capture",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no effect")),
    )

    with pytest.raises(ValueError, match="stopped before invocation"):
        _transfer_execution_bundle(
            work_dir=work,
            bundle=bundle,
            bundle_receipt=receipt,
            receiver=receiver,
            receiver_digest=receiver_digest,
            target=_target(),
            timeout_seconds=600,
        )

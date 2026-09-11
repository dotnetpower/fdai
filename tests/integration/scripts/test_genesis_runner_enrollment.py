"""Private Bastion runner enrollment and attestation regressions."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import TracebackType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_bastion as bastion_transport  # noqa: E402
import genesis_runner_enrollment as enrollment  # noqa: E402
from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest  # noqa: E402
from fdai_deployment_cli.private_output import write_private_output  # noqa: E402
from fdai_deployment_cli.profile import write_profile  # noqa: E402
from fdai_deployment_cli.target import compute_target_binding  # noqa: E402

SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
TENANT = "00000000-0000-0000-0000-000000000002"
BINDING = compute_target_binding(tenant_id=TENANT, subscription_id=SUBSCRIPTION)
SOURCE = "a" * 40
HANDOFF_DIGEST = "b" * 64
SSH_DIGEST = "c" * 64
TOOLCHAIN_DIGEST = "d" * 64
TOKEN = "synthetic-short-lived-registration-material"


def _private_json(path: Path, value: dict[str, object]) -> None:
    write_private_output(path, json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _profile(path: Path) -> None:
    write_profile(
        path,
        ProvisionProfile(
            environment="dev",
            region="koreacentral",
            target_binding=BINDING,
            connectivity="online",
            host="managed-vm",
            transport="manual",
            access_method="bastion",
            shadow_only=True,
            approval_quorum=1,
            monthly_cost_ceiling=500,
        ),
    )


def _handoff() -> dict[str, object]:
    vm_name = "vm-runner-example-dev-krc"
    ops_group = "rg-example-ops-krc"
    return {
        "terraform_root": "infra/genesis-foundation",
        "source_commit": SOURCE,
        "run_digest": "e" * 64,
        "subscription_id": SUBSCRIPTION,
        "tenant_id": TENANT,
        "region": "koreacentral",
        "app_resource_group": {"id": "synthetic-app-group"},
        "ops": {"resource_group_name": ops_group},
        "state": {"account_id": "synthetic-state-account"},
        "runner": {
            "vm_name": vm_name,
            "vm_id": (
                f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{ops_group}/"
                f"providers/Microsoft.Compute/virtualMachines/{vm_name}"
            ),
            "admin_username": "fdairunner",
            "parallelism": 2,
            "ssh_key_digest": SSH_DIGEST,
            "bootstrap_mode": "offline",
            "source_image_id": "synthetic-image",
            "toolchain_digest": TOOLCHAIN_DIGEST,
            "public_egress": True,
            "identity_id": "synthetic-identity",
            "client_id": "00000000-0000-0000-0000-000000000003",
            "principal_id": "00000000-0000-0000-0000-000000000004",
            "role_manifest": {},
        },
        "access": {
            "method": "bastion",
            "bastion_name": "bas-runner-example-dev-krc",
            "bastion_id": (
                f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{ops_group}/"
                "providers/Microsoft.Network/bastionHosts/bas-runner-example-dev-krc"
            ),
        },
    }


def _foundation_receipt(handoff: dict[str, object]) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "fdai.genesis-foundation-apply-receipt.v1",
        "state": "applied",
        "review_digest": "1" * 64,
        "plan_digest": "2" * 64,
        "target_binding": BINDING,
        "source_commit": SOURCE,
        "state_digest": "3" * 64,
        "state_ref": "foundation-apply-bundle/root/terraform.tfstate",
        "handoff_digest": canonical_digest(handoff),
        "control_plane_readback_verified": True,
        "zero_change_verified": True,
        "remote_backend_authority_verified": False,
        "runner_attested": False,
        "mutation_performed": True,
        "subscription_ready": False,
        "completed_at": "2026-09-10T00:00:00+00:00",
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    return receipt


def _runner_records() -> list[dict[str, object]]:
    labels = ["fdai-deploy", "fdai-deploy-candidate", "self-hosted"]
    return [
        {
            "name": "vm-runner-example-dev-krc",
            "status": "online",
            "busy": False,
            "labels": labels,
        },
        {
            "name": "vm-runner-example-dev-krc-2",
            "status": "online",
            "busy": False,
            "labels": labels,
        },
    ]


class FakeTunnel:
    calls: list[tuple[tuple[str, ...], str | None]] = []
    known_hosts: Path

    def __init__(self, **kwargs: object) -> None:
        self.known_hosts = Path(str(kwargs["known_hosts"]))

    def __enter__(self) -> FakeTunnel:
        self.known_hosts.write_text("synthetic-host-key\n", encoding="utf-8")
        self.known_hosts.chmod(0o600)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    def ssh(
        self,
        remote_arguments: tuple[str, ...],
        *,
        timeout: int,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del timeout
        self.calls.append((remote_arguments, input_text))
        if remote_arguments[0] == "/usr/bin/test":
            return subprocess.CompletedProcess(remote_arguments, 0, "", "")
        if remote_arguments[0].endswith("fdai-enroll-runner"):
            claim = self.known_hosts.parent / enrollment.CLAIM_NAME
            assert claim.is_file()
            assert input_text == TOKEN + "\n"
            slot = remote_arguments[remote_arguments.index("--slot") + 1]
            name = remote_arguments[remote_arguments.index("--runner-name") + 1]
            return subprocess.CompletedProcess(
                remote_arguments,
                0,
                f"enrollment_complete slot={slot} runner_name={name}\n",
                "",
            )
        return subprocess.CompletedProcess(
            remote_arguments, 0, "attestation_complete slots=2\n", ""
        )


def _prepare(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    tmp_path.chmod(0o700)
    plan = tmp_path / "plan"
    plan.mkdir(mode=0o700)
    profile = tmp_path / "profile.json"
    _profile(profile)
    handoff = _handoff()
    receipt = _foundation_receipt(handoff)
    _private_json(plan / enrollment.HANDOFF_NAME, handoff)
    _private_json(plan / enrollment.FOUNDATION_RECEIPT_NAME, receipt)
    return plan, profile, receipt


def _arguments(plan: Path, profile: Path, receipt: dict[str, object], *extra: str) -> list[str]:
    return [
        "--foundation-plan-directory",
        str(plan),
        "--profile",
        str(profile),
        "--repository",
        "example/repository",
        "--ssh-private-key",
        str(plan.parent / "id_ed25519"),
        "--expected-foundation-receipt-digest",
        str(receipt["receipt_digest"]),
        "--timeout-seconds",
        "300",
        "--output",
        "json",
        *extra,
    ]


def _mock_boundaries(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    FakeTunnel.calls = []
    capture_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(enrollment, "BastionTunnel", FakeTunnel)
    monkeypatch.setattr(enrollment, "validate_ssh_private_key", lambda _: SSH_DIGEST)
    monkeypatch.setattr(enrollment.GenesisChecks, "verify_target", lambda *a, **kw: None)
    monkeypatch.setattr(enrollment.GenesisChecks, "verify_source", lambda *a, **kw: None)
    monkeypatch.setattr(enrollment, "_list_runners", lambda _: [])
    monkeypatch.setattr(enrollment, "_wait_for_runners", lambda *a, **kw: _runner_records())

    def capture(command: tuple[str, ...], **_: object) -> str:
        capture_calls.append(command)
        if command[2:4] == ("user", "--jq"):
            return "operator\n"
        if "registration-token" in command[4]:
            return TOKEN + "\n"
        raise AssertionError(command)

    monkeypatch.setattr(enrollment, "_capture", capture)
    return capture_calls


def test_enrollment_claims_before_stdin_only_token_effect_and_attests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, profile, receipt = _prepare(tmp_path)
    capture_calls = _mock_boundaries(monkeypatch)

    assert enrollment.main(_arguments(plan, profile, receipt, "--approve")) == 0

    claim = json.loads((plan / enrollment.CLAIM_NAME).read_text(encoding="utf-8"))
    result = json.loads((plan / enrollment.RECEIPT_NAME).read_text(encoding="utf-8"))
    assert claim["state"] == "enrolling"
    assert claim["mutation_performed"] is False
    assert result["state"] == "attested"
    assert result["identity_attested"] is True
    assert result["github_readback_verified"] is True
    assert result["claim_digest"] == canonical_digest(claim)
    assert result["actor_digest"] == claim["actor_digest"]
    assert len([call for call, _ in FakeTunnel.calls if "fdai-enroll-runner" in call[0]]) == 2
    assert all(
        input_text == TOKEN + "\n"
        for call, input_text in FakeTunnel.calls
        if "fdai-enroll-runner" in call[0]
    )
    all_arguments = "\n".join(" ".join(call) for call in capture_calls)
    all_arguments += "\n" + "\n".join(" ".join(call) for call, _ in FakeTunnel.calls)
    assert TOKEN not in all_arguments
    assert TOKEN not in (plan / enrollment.CLAIM_NAME).read_text(encoding="utf-8")
    assert TOKEN not in (plan / enrollment.RECEIPT_NAME).read_text(encoding="utf-8")


def test_resume_is_verification_only_and_never_mints_or_resends_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, profile, receipt = _prepare(tmp_path)
    _mock_boundaries(monkeypatch)
    assert enrollment.main(_arguments(plan, profile, receipt, "--approve")) == 0
    (plan / enrollment.RECEIPT_NAME).unlink()
    FakeTunnel.calls = []

    def no_capture(*args: object, **kwargs: object) -> str:
        pytest.fail("verification resume must not mint a token or read a GitHub actor")

    monkeypatch.setattr(enrollment, "_capture", no_capture)
    assert enrollment.main(_arguments(plan, profile, receipt, "--resume-verification")) == 0
    assert all("fdai-enroll-runner" not in call[0] for call, _ in FakeTunnel.calls)
    assert any("fdai-attest-runner" in call[0] for call, _ in FakeTunnel.calls)


def test_completed_receipt_rechecks_bastion_attestation_and_github_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, profile, receipt = _prepare(tmp_path)
    _mock_boundaries(monkeypatch)
    assert enrollment.main(_arguments(plan, profile, receipt, "--approve")) == 0
    FakeTunnel.calls = []

    def no_capture(*args: object, **kwargs: object) -> str:
        pytest.fail("terminal receipt verification must not mint a token or read an actor")

    monkeypatch.setattr(enrollment, "_capture", no_capture)
    assert enrollment.main(_arguments(plan, profile, receipt, "--approve")) == 0

    assert all("fdai-enroll-runner" not in call[0] for call, _ in FakeTunnel.calls)
    assert [call for call, _ in FakeTunnel.calls if "fdai-attest-runner" in call[0]]


def test_completed_receipt_rejects_changed_host_key_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, profile, receipt = _prepare(tmp_path)
    _mock_boundaries(monkeypatch)
    assert enrollment.main(_arguments(plan, profile, receipt, "--approve")) == 0
    known_hosts = plan / enrollment.KNOWN_HOSTS_NAME
    known_hosts.write_text("different-host-key\n", encoding="utf-8")
    known_hosts.chmod(0o600)
    FakeTunnel.calls = []

    assert enrollment.main(_arguments(plan, profile, receipt, "--approve")) == 3
    assert FakeTunnel.calls == []


def test_completed_receipt_rejects_changed_actor_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, profile, receipt = _prepare(tmp_path)
    _mock_boundaries(monkeypatch)
    assert enrollment.main(_arguments(plan, profile, receipt, "--approve")) == 0
    claim_path = plan / enrollment.CLAIM_NAME
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    claim["actor_digest"] = "9" * 64
    claim_path.unlink()
    _private_json(claim_path, claim)
    FakeTunnel.calls = []

    assert enrollment.main(_arguments(plan, profile, receipt, "--approve")) == 3
    assert FakeTunnel.calls == []


def test_enrollment_rejects_private_key_not_bound_to_foundation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, profile, receipt = _prepare(tmp_path)
    monkeypatch.setattr(enrollment, "validate_ssh_private_key", lambda _: "9" * 64)

    assert enrollment.main(_arguments(plan, profile, receipt, "--approve")) == 3
    assert not (plan / enrollment.CLAIM_NAME).exists()


def test_image_enrollment_helper_has_no_token_argument_or_legacy_transport() -> None:
    helper = (ROOT / "infra/genesis-runner-image/enroll-runner.sh").read_text(encoding="utf-8")
    command = (SCRIPT_DIR / "genesis_runner_enrollment.py").read_text(encoding="utf-8")

    assert "ACTIONS_RUNNER_INPUT_TOKEN" in helper
    assert "config.sh" in helper
    assert "--token" not in helper
    assert "run-command" not in command
    assert 'input_text=token + "\\n"' in command
    assert "registration-token" in command
    assert "remove-token" not in command


def test_bastion_transport_keeps_private_input_out_of_ssh_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    private_key = tmp_path / "id_ed25519"
    known_hosts = tmp_path / "known_hosts"
    private_key.write_text("synthetic-private-key", encoding="utf-8")
    known_hosts.write_text("synthetic-host-key", encoding="utf-8")
    private_key.chmod(0o600)
    known_hosts.chmod(0o600)
    observed: dict[str, object] = {}

    def run(arguments: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["arguments"] = arguments
        observed["input_text"] = kwargs.get("input_text")
        return subprocess.CompletedProcess(arguments, 0, "ok\n", "")

    monkeypatch.setattr(bastion_transport, "run_with_heartbeat", run)
    tunnel = bastion_transport.BastionTunnel(
        subscription_id=SUBSCRIPTION,
        resource_group="rg-example-ops-krc",
        bastion_name="bas-example",
        vm_id="synthetic-vm-id",
        username="fdairunner",
        private_key=private_key,
        known_hosts=known_hosts,
        host_key_alias="fdai-genesis-example",
        cwd=tmp_path,
        timeout=300,
        trust_new_host_key=False,
    )
    tunnel.port = 50022

    result = tunnel.ssh(
        ("/usr/local/sbin/example", "--mode", "verify"),
        timeout=60,
        input_text=TOKEN,
    )

    arguments = observed["arguments"]
    assert isinstance(arguments, tuple)
    assert result.returncode == 0
    assert observed["input_text"] == TOKEN
    assert TOKEN not in arguments
    assert "StrictHostKeyChecking=yes" in arguments
    assert "HostKeyAlias=fdai-genesis-example" in arguments
    assert "PasswordAuthentication=no" in arguments


def test_new_enrollment_entrypoints_remain_python_310_compatible() -> None:
    for path in (
        SCRIPT_DIR / "genesis_bastion.py",
        SCRIPT_DIR / "genesis_runner_enrollment.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "from datetime import UTC" not in source
        compile(source, str(path), "exec")

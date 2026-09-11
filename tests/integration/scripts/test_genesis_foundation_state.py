"""Claim-safe local-to-private Foundation state handoff regressions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType, SimpleNamespace, TracebackType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_foundation_state as state_command  # noqa: E402
from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest  # noqa: E402
from fdai_deployment_cli.private_output import write_private_output  # noqa: E402
from fdai_deployment_cli.profile import write_profile  # noqa: E402
from fdai_deployment_cli.target import compute_target_binding  # noqa: E402
from genesis_foundation_state_archive import create_foundation_state_archive  # noqa: E402

SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
TENANT = "00000000-0000-0000-0000-000000000002"
BINDING = compute_target_binding(tenant_id=TENANT, subscription_id=SUBSCRIPTION)
SOURCE = "a" * 40
ARCHIVE_DIGEST = hashlib.sha256(b"archive").hexdigest()


def _remote_module() -> ModuleType:
    path = ROOT / "infra/genesis-runner-image/migrate-foundation-state.py"
    spec = importlib.util.spec_from_file_location("fdai_remote_state_handoff", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _private_json(path: Path, value: dict[str, object]) -> None:
    write_private_output(path, json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _state_inputs() -> tuple[dict[str, object], dict[str, object]]:
    state: dict[str, object] = {
        "version": 4,
        "terraform_version": "1.9.8",
        "lineage": "00000000-0000-0000-0000-000000000009",
        "serial": 7,
        "outputs": {},
        "resources": [
            {
                "mode": "managed",
                "type": "terraform_data",
                "name": "ownership",
                "instances": [{"attributes": {"id": "opaque-resource-id"}}],
            }
        ],
    }
    attributes = {"id": "opaque-resource-id"}
    plan: dict[str, object] = {
        "format_version": "1.2",
        "terraform_version": "1.9.8",
        "complete": True,
        "errored": False,
        "applyable": False,
        "prior_state": {
            "values": {
                "root_module": {
                    "resources": [
                        {
                            "address": "terraform_data.ownership",
                            "mode": "managed",
                            "values": attributes,
                        }
                    ]
                }
            }
        },
        "resource_changes": [
            {
                "address": "terraform_data.ownership",
                "change": {
                    "actions": ["no-op"],
                    "before": attributes,
                    "after": deepcopy(attributes),
                },
            }
        ],
        "output_changes": {},
        "checks": [{"status": "pass"}],
    }
    return state, plan


def test_private_archive_preserves_exact_state_and_executable_provider(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    root = tmp_path / "root"
    mirror = tmp_path / "mirror"
    root.mkdir(mode=0o700)
    provider_dir = mirror / "registry.terraform.io/hashicorp/azurerm/4.81.0/linux_amd64"
    provider_dir.mkdir(mode=0o700, parents=True)
    state, _ = _state_inputs()
    state_path = root / "terraform.tfstate"
    _private_json(state_path, state)
    (root / "main.tf").write_text('terraform { backend "azurerm" {} }\n', encoding="utf-8")
    (root / "main.tf").chmod(0o600)
    provider = provider_dir / "terraform-provider-azurerm_v4.81.0_x5"
    provider.write_text("provider", encoding="utf-8")
    provider.chmod(0o700)
    variables = tmp_path / "variables.json"
    _private_json(variables, {"env": "dev"})
    state_digest = hashlib.sha256(state_path.read_bytes()).hexdigest()
    archive = tmp_path / "handoff.tar.gz"

    result = create_foundation_state_archive(
        terraform_root=root,
        provider_mirror=mirror,
        variables_file=variables,
        destination=archive,
        source_commit=SOURCE,
        expected_state_digest=state_digest,
    )

    assert result["archive_digest"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert archive.stat().st_mode & 0o777 == 0o600
    remote = _remote_module()
    extracted = tmp_path / "extracted"
    extracted.mkdir(mode=0o700)
    copied_archive = tmp_path / "remote.tar.gz"
    copied_archive.write_bytes(archive.read_bytes())
    copied_archive.chmod(0o600)
    assert remote._extract_archive(copied_archive, extracted) == result["archive_digest"]
    remote._verify_tree(extracted, migrated=False)
    assert (extracted / "root/terraform.tfstate").read_bytes() == state_path.read_bytes()
    assert (extracted / provider.relative_to(tmp_path)).stat().st_mode & 0o777 == 0o700


def test_remote_backend_authority_requires_blob_protection_and_entra_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = _remote_module()
    captures = iter(
        (
            b'{"public":"Disabled","key":false,"tls":"TLS1_2"}',
            b'{"versioning":true,"blobDelete":true,"containerDelete":true}',
        )
    )
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(remote, "_capture", lambda *a, **kw: next(captures))
    monkeypatch.setattr(
        remote,
        "_run",
        lambda command, **kwargs: calls.append(command),
    )
    args = SimpleNamespace(
        state_account_id="/subscriptions/example/resourceGroups/example/providers/Microsoft.Storage/storageAccounts/example",
        account_name="example",
        container_name="tfstate",
        backend_key="ops/genesis-foundation/dev.tfstate",
    )

    remote._verify_backend(args, {})

    assert len(calls) == 1
    assert calls[0][1:4] == ("storage", "blob", "show")
    assert "--auth-mode" in calls[0]
    assert calls[0][calls[0].index("--auth-mode") + 1] == "login"

    failed = iter(
        (
            b'{"public":"Disabled","key":false,"tls":"TLS1_2"}',
            b'{"versioning":false,"blobDelete":true,"containerDelete":true}',
        )
    )
    monkeypatch.setattr(remote, "_capture", lambda *a, **kw: next(failed))
    with pytest.raises(ValueError, match="Blob protection"):
        remote._verify_backend(args, {})


def test_remote_completed_authority_observation_is_read_only_and_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = _remote_module()
    monkeypatch.setenv("HOME", str(tmp_path))
    work_id = "a" * 64
    archive_digest = "b" * 64
    state, _ = _state_inputs()
    state_bytes = json.dumps(state, indent=2).encode()
    cleanup = tmp_path / ".fdai-state-handoff" / f"cleanup-{work_id[:24]}.json"
    cleanup.parent.mkdir(mode=0o700)
    _private_json(
        cleanup,
        {
            "schema_version": "fdai.genesis-foundation-remote-state-cleanup.v1",
            "work_id": work_id,
            "archive_digest": archive_digest,
            "raw_transient_deleted": True,
        },
    )
    calls: list[tuple[str, ...]] = []
    verified: list[str] = []
    monkeypatch.setattr(remote, "_terraform_environment", lambda *a, **kw: {})
    monkeypatch.setattr(remote, "_managed_identity_login", lambda *a, **kw: None)
    monkeypatch.setattr(remote, "_run", lambda command, **kw: calls.append(command))
    monkeypatch.setattr(remote, "_capture", lambda *a, **kw: state_bytes)
    monkeypatch.setattr(remote, "_verify_backend", lambda *a, **kw: verified.append("backend"))
    args = SimpleNamespace(
        work_id=work_id,
        archive_digest=archive_digest,
        expected_state_digest=canonical_digest(state),
        resource_group="rg-example-ops-krc",
        account_name="examplegenesis",
        container_name="tfstate",
        backend_key="ops/genesis-foundation/dev.tfstate",
        client_id="00000000-0000-0000-0000-000000000003",
        subscription_id=SUBSCRIPTION,
        tenant_id=TENANT,
        archive=tmp_path / f".fdai-transfer-{work_id[:24]}.tar.gz",
    )

    remote._observe_remote_authority(args, cleanup)

    assert any("init" in command for command in calls)
    assert all("migrate-state" not in command for command in calls)
    assert verified == ["backend"]
    assert not (tmp_path / ".fdai-state-observe" / work_id[:24]).exists()


def test_remote_cleanup_marker_cannot_hide_raw_residue(tmp_path: Path) -> None:
    remote = _remote_module()
    tmp_path.chmod(0o700)
    work_id = "a" * 64
    archive_digest = "b" * 64
    base = tmp_path / ".fdai-state-handoff"
    base.mkdir(mode=0o700)
    work = base / work_id[:24]
    work.mkdir(mode=0o700)
    marker = base / f"cleanup-{work_id[:24]}.json"
    _private_json(
        marker,
        {
            "schema_version": "fdai.genesis-foundation-remote-state-cleanup.v1",
            "work_id": work_id,
            "archive_digest": archive_digest,
            "raw_transient_deleted": True,
        },
    )
    args = SimpleNamespace(
        work_id=work_id,
        archive_digest=archive_digest,
        archive=tmp_path / f".fdai-transfer-{work_id[:24]}.tar.gz",
    )

    with pytest.raises(ValueError, match="cleanup residue remains"):
        remote._cleanup_remote_state(args, base, work, marker)


def test_remote_cleanup_resumes_after_intent_without_false_completion(tmp_path: Path) -> None:
    remote = _remote_module()
    tmp_path.chmod(0o700)
    work_id = "a" * 64
    archive_digest = "b" * 64
    base = tmp_path / ".fdai-state-handoff"
    base.mkdir(mode=0o700)
    work = base / work_id[:24]
    work.mkdir(mode=0o700)
    archive = tmp_path / f".fdai-transfer-{work_id[:24]}.tar.gz"
    archive.write_bytes(b"transient")
    archive.chmod(0o600)
    intent = base / f"cleanup-intent-{work_id[:24]}.json"
    _private_json(
        intent,
        {
            "schema_version": "fdai.genesis-foundation-remote-state-cleanup-intent.v1",
            "work_id": work_id,
            "archive_digest": archive_digest,
            "cleanup_authorized": True,
        },
    )
    marker = base / f"cleanup-{work_id[:24]}.json"
    args = SimpleNamespace(
        work_id=work_id,
        archive_digest=archive_digest,
        archive=archive,
    )

    remote._cleanup_remote_state(args, base, work, marker)

    assert not work.exists()
    assert not archive.exists()
    assert not intent.exists()
    assert json.loads(marker.read_text(encoding="utf-8"))["raw_transient_deleted"] is True


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


def _prepare(tmp_path: Path) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
    tmp_path.chmod(0o700)
    directory = tmp_path / "plan"
    directory.mkdir(mode=0o700)
    profile = tmp_path / "profile.json"
    _profile(profile)
    state, plan = _state_inputs()
    state_dir = directory / "foundation-apply-bundle/bundle/infra/genesis-foundation"
    state_dir.mkdir(mode=0o700, parents=True)
    state_path = state_dir / "terraform.tfstate"
    _private_json(state_path, state)
    state_digest = hashlib.sha256(state_path.read_bytes()).hexdigest()
    handoff: dict[str, object] = {
        "terraform_root": "infra/genesis-foundation",
        "source_commit": SOURCE,
        "run_digest": "1" * 64,
        "subscription_id": SUBSCRIPTION,
        "tenant_id": TENANT,
        "region": "koreacentral",
        "app_resource_group": {"id": "synthetic-app-group"},
        "ops": {"resource_group_name": "rg-example-ops-krc"},
        "state": {
            "account_id": (
                f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-example-ops-krc/"
                "providers/Microsoft.Storage/storageAccounts/examplegenesis"
            ),
            "account_name": "examplegenesis",
            "container_name": "tfstate",
            "foundation_key": "ops/genesis-foundation/dev.tfstate",
        },
        "runner": {
            "vm_name": "vm-runner-example-dev-krc",
            "vm_id": (
                f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-example-ops-krc/"
                "providers/Microsoft.Compute/virtualMachines/vm-runner-example-dev-krc"
            ),
            "admin_username": "fdairunner",
            "ssh_key_digest": "2" * 64,
            "client_id": "00000000-0000-0000-0000-000000000003",
            "principal_id": "00000000-0000-0000-0000-000000000004",
        },
        "access": {"method": "bastion", "bastion_name": "bas-example"},
    }
    foundation: dict[str, object] = {
        "schema_version": "fdai.genesis-foundation-apply-receipt.v1",
        "state": "applied",
        "review_digest": "3" * 64,
        "plan_digest": "4" * 64,
        "target_binding": BINDING,
        "source_commit": SOURCE,
        "state_digest": state_digest,
        "state_ref": "foundation-apply-bundle/bundle/infra/genesis-foundation/terraform.tfstate",
        "handoff_digest": canonical_digest(handoff),
        "control_plane_readback_verified": True,
        "zero_change_verified": True,
        "remote_backend_authority_verified": False,
        "runner_attested": False,
        "mutation_performed": True,
        "subscription_ready": False,
        "completed_at": "2026-09-10T00:00:00+00:00",
    }
    foundation["receipt_digest"] = canonical_digest(foundation)
    enrollment: dict[str, object] = {
        "schema_version": "fdai.genesis-runner-enrollment-receipt.v1",
        "state": "attested",
        "foundation_receipt_digest": foundation["receipt_digest"],
        "handoff_digest": foundation["handoff_digest"],
        "target_binding": BINDING,
        "source_commit": SOURCE,
        "identity_attested": True,
        "services_attested": True,
        "github_readback_verified": True,
        "effect_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    enrollment["receipt_digest"] = canonical_digest(enrollment)
    _private_json(directory / state_command.foundation_apply.HANDOFF_NAME, handoff)
    _private_json(directory / state_command.foundation_apply.RECEIPT_NAME, foundation)
    _private_json(directory / state_command.ENROLLMENT_RECEIPT_NAME, enrollment)
    known_hosts = directory / state_command.KNOWN_HOSTS_NAME
    known_hosts.write_text("synthetic-host-key\n", encoding="utf-8")
    known_hosts.chmod(0o600)
    return directory, profile, foundation, {"state": state, "plan": plan}


class FakeTunnel:
    fail_migration = False
    calls: list[tuple[str, ...]] = []
    copied: list[str] = []
    evidence: dict[str, object]
    directory: Path

    def __init__(self, **kwargs: object) -> None:
        self.directory = Path(str(kwargs["cwd"]))

    def __enter__(self) -> FakeTunnel:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    def ssh(
        self, remote_arguments: tuple[str, ...], *, timeout: int, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        del timeout
        assert input_text is None
        self.calls.append(remote_arguments)
        if remote_arguments[0] == "/usr/bin/test":
            return subprocess.CompletedProcess(remote_arguments, 0, "", "")
        mode = remote_arguments[1]
        work_id = remote_arguments[remote_arguments.index("--work-id") + 1]
        if mode == "migrate" and self.fail_migration:
            return subprocess.CompletedProcess(remote_arguments, 3, "", "")
        if mode in {"migrate", "verify"}:
            return subprocess.CompletedProcess(
                remote_arguments, 0, f"state_handoff_complete work_ref={work_id[:24]}\n", ""
            )
        if mode == "observe":
            return subprocess.CompletedProcess(
                remote_arguments,
                0,
                f"state_handoff_observation_complete work_ref={work_id[:24]}\n",
                "",
            )
        return subprocess.CompletedProcess(
            remote_arguments,
            0,
            f"state_handoff_cleanup_complete work_ref={work_id[:24]}\n",
            "",
        )

    def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
        del source, timeout
        assert (self.directory / state_command.CLAIM_NAME).is_file()
        self.copied.append(destination)

    def copy_from(self, source: str, destination: Path, *, timeout: int) -> None:
        del timeout
        state = self.evidence["state"]
        plan = self.evidence["plan"]
        if source.endswith("remote-state.json"):
            payload = json.dumps(state, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        elif source.endswith("remote-plan.json"):
            payload = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        else:
            claim = json.loads(
                (self.directory / state_command.CLAIM_NAME).read_text(encoding="utf-8")
            )
            state_bytes = json.dumps(state, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            plan_bytes = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            payload = (
                json.dumps(
                    {
                        "schema_version": "fdai.genesis-foundation-remote-state-observation.v1",
                        "state": "verified",
                        "work_id": claim["work_id"],
                        "archive_digest": claim["archive_digest"],
                        "remote_state_digest": hashlib.sha256(state_bytes).hexdigest(),
                        "remote_plan_digest": hashlib.sha256(plan_bytes).hexdigest(),
                        "managed_identity_verified": True,
                        "backend_protection_verified": True,
                        "backend_blob_verified": True,
                        "zero_change_verified": True,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                + b"\n"
            )
        destination.write_bytes(payload)
        destination.chmod(0o600)


def _arguments(
    directory: Path,
    profile: Path,
    foundation: dict[str, object],
    *extra: str,
) -> list[str]:
    enrollment = json.loads(
        (directory / state_command.ENROLLMENT_RECEIPT_NAME).read_text(encoding="utf-8")
    )
    return [
        "--foundation-plan-directory",
        str(directory),
        "--profile",
        str(profile),
        "--variables-file",
        str(directory / "variables.json"),
        "--offline-kit",
        str(directory / "kit"),
        "--release-root",
        str(directory / "release.pub"),
        "--bundle-public-key",
        str(directory / "bundle.pub"),
        "--repository",
        "example/repository",
        "--ssh-private-key",
        str(directory / "id_ed25519"),
        "--expected-foundation-receipt-digest",
        str(foundation["receipt_digest"]),
        "--expected-enrollment-receipt-digest",
        str(enrollment["receipt_digest"]),
        "--timeout-seconds",
        "900",
        "--output",
        "json",
        *extra,
    ]


def _mock_boundaries(
    monkeypatch: pytest.MonkeyPatch, directory: Path, evidence: dict[str, object]
) -> None:
    FakeTunnel.calls = []
    FakeTunnel.copied = []
    FakeTunnel.evidence = evidence
    monkeypatch.setattr(state_command, "BastionTunnel", FakeTunnel)
    monkeypatch.setattr(state_command, "validate_ssh_private_key", lambda _: "2" * 64)
    monkeypatch.setattr(state_command.GenesisChecks, "verify_target", lambda *a, **kw: None)
    monkeypatch.setattr(state_command.GenesisChecks, "verify_source", lambda *a, **kw: None)
    monkeypatch.setattr(
        state_command.GenesisChecks,
        "capture",
        lambda *a, **kw: '{"type":"user","name":"operator@example.com"}',
    )

    def archive(**kwargs: object) -> dict[str, object]:
        destination = Path(str(kwargs["archive"]))
        destination.write_bytes(b"archive")
        destination.chmod(0o600)
        return {"archive_digest": ARCHIVE_DIGEST}

    monkeypatch.setattr(state_command, "_prepare_archive", archive)


def test_state_handoff_claims_before_transfer_compares_and_cleans_raw_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, profile, foundation, evidence = _prepare(tmp_path)
    _mock_boundaries(monkeypatch, directory, evidence)

    assert state_command.main(_arguments(directory, profile, foundation, "--approve")) == 0

    claim = json.loads((directory / state_command.CLAIM_NAME).read_text(encoding="utf-8"))
    authority = json.loads((directory / state_command.AUTHORITY_NAME).read_text(encoding="utf-8"))
    receipt = json.loads((directory / state_command.RECEIPT_NAME).read_text(encoding="utf-8"))
    assert claim["mutation_performed"] is False
    assert (
        claim["actor_digest"]
        == hashlib.sha256(f"{BINDING}:operator@example.com".encode()).hexdigest()
    )
    assert authority["claim_digest"] == canonical_digest(claim)
    assert authority["actor_digest"] == claim["actor_digest"]
    assert receipt["claim_digest"] == canonical_digest(claim)
    assert receipt["actor_digest"] == claim["actor_digest"]
    assert authority["remote_backend_authority_verified"] is True
    assert receipt["local_state_deleted"] is True
    assert receipt["remote_transient_deleted"] is True
    assert FakeTunnel.copied
    modes = [call[1] for call in FakeTunnel.calls if "fdai-migrate" in call[0]]
    assert modes == ["migrate", "cleanup"]
    state_path = directory / str(foundation["state_ref"])
    assert not state_path.exists()
    assert not any(directory.glob("remote-state-*.json"))
    assert not any(directory.glob("remote-plan-*.json"))


def test_state_handoff_requires_an_authenticated_human_operator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, profile, foundation, evidence = _prepare(tmp_path)
    _mock_boundaries(monkeypatch, directory, evidence)
    monkeypatch.setattr(
        state_command.GenesisChecks,
        "capture",
        lambda *a, **kw: '{"type":"servicePrincipal","name":"executor"}',
    )

    assert state_command.main(_arguments(directory, profile, foundation, "--approve")) == 3
    assert not (directory / state_command.CLAIM_NAME).exists()
    assert not FakeTunnel.copied


def test_ambiguous_migration_resumes_verification_without_transfer_or_remigration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, profile, foundation, evidence = _prepare(tmp_path)
    _mock_boundaries(monkeypatch, directory, evidence)
    FakeTunnel.fail_migration = True
    assert state_command.main(_arguments(directory, profile, foundation, "--approve")) == 3
    assert (directory / state_command.CLAIM_NAME).is_file()
    assert (directory / str(foundation["state_ref"])).is_file()

    FakeTunnel.fail_migration = False
    FakeTunnel.calls = []
    FakeTunnel.copied = []
    arguments = _arguments(directory, profile, foundation, "--resume-verification")
    assert state_command.main(arguments) == 0
    modes = [call[1] for call in FakeTunnel.calls if "fdai-migrate" in call[0]]
    assert modes == ["verify", "cleanup"]
    assert not FakeTunnel.copied


def test_completed_handoff_reobserves_remote_authority_without_repeating_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, profile, foundation, evidence = _prepare(tmp_path)
    _mock_boundaries(monkeypatch, directory, evidence)
    assert state_command.main(_arguments(directory, profile, foundation, "--approve")) == 0
    FakeTunnel.calls = []
    FakeTunnel.copied = []

    assert state_command.main(_arguments(directory, profile, foundation, "--approve")) == 0

    modes = [call[1] for call in FakeTunnel.calls if "fdai-migrate" in call[0]]
    assert modes == ["observe"]
    assert not FakeTunnel.copied


def test_completed_handoff_requires_its_immutable_actor_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, profile, foundation, evidence = _prepare(tmp_path)
    _mock_boundaries(monkeypatch, directory, evidence)
    assert state_command.main(_arguments(directory, profile, foundation, "--approve")) == 0
    (directory / state_command.CLAIM_NAME).unlink()
    FakeTunnel.calls = []

    assert state_command.main(_arguments(directory, profile, foundation, "--approve")) == 3
    assert FakeTunnel.calls == []


def test_new_state_handoff_entrypoints_remain_python_310_compatible() -> None:
    paths = (
        SCRIPT_DIR / "genesis_foundation_state.py",
        SCRIPT_DIR / "genesis_foundation_state_contract.py",
        SCRIPT_DIR / "genesis_foundation_state_archive.py",
        ROOT / "infra/genesis-runner-image/migrate-foundation-state.py",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "from datetime import UTC" not in source
        compile(source, str(path), "exec")

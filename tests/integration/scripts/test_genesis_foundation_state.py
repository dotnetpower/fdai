"""Claim-safe local-to-private Foundation state handoff regressions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace, TracebackType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_foundation_state as state_command  # noqa: E402
import genesis_foundation_state_archive as state_archive  # noqa: E402
import genesis_foundation_state_support_repair as support_repair  # noqa: E402
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


def _write_runner_support(root: Path) -> Path:
    support = root / "genesis-runner-image"
    support.mkdir(mode=0o700)
    for name in (
        "attest-runner.sh",
        "customize-runner-image.sh.tftpl",
        "enroll-runner.sh",
        "migrate-foundation-state.py",
        "toolchain.json",
    ):
        (support / name).write_text(f"{name}\n", encoding="utf-8")
    return support


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


def test_runner_support_contract_covers_every_foundation_reference() -> None:
    source = (ROOT / "infra/genesis-foundation/main.tf").read_text(encoding="utf-8")
    referenced = set(re.findall(r"\.\./genesis-runner-image/([A-Za-z0-9._-]+)", source))
    remote = _remote_module()

    assert referenced == set(state_archive.RUNNER_SUPPORT_FILES)
    assert referenced == remote._SUPPORT_REPAIR_FILES


class SupportRepairTunnel:
    def __init__(self, home: Path, username: str) -> None:
        self.home = home
        self.username = username
        self.copied: list[str] = []

    def _path(self, remote: str) -> Path:
        prefix = f"/home/{self.username}/"
        assert remote.startswith(prefix)
        return self.home / remote.removeprefix(prefix)

    def ssh(
        self, remote_arguments: tuple[str, ...], *, timeout: int, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        del timeout
        assert input_text is None
        assert not any(
            character in argument for argument in remote_arguments for character in "|;&><`$"
        )
        command = remote_arguments[0]
        if command == "/usr/bin/stat":
            path = self._path(remote_arguments[-1])
            try:
                details = path.lstat()
            except FileNotFoundError:
                return subprocess.CompletedProcess(remote_arguments, 1, "", "")
            kind = (
                "regular file"
                if stat.S_ISREG(details.st_mode)
                else "directory"
                if stat.S_ISDIR(details.st_mode)
                else "symbolic link"
            )
            mode = f"{stat.S_IMODE(details.st_mode):o}"
            if "%h" in remote_arguments[1]:
                output = f"{kind},{details.st_nlink},{mode},{self.username}\n"
            else:
                output = f"{kind},{mode},{self.username}\n"
            return subprocess.CompletedProcess(remote_arguments, 0, output, "")
        if command == "/usr/bin/sha256sum":
            path = self._path(remote_arguments[1])
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            return subprocess.CompletedProcess(
                remote_arguments, 0, f"{digest}  {remote_arguments[1]}\n", ""
            )
        if command == "/usr/bin/mkdir":
            self._path(remote_arguments[-1]).mkdir(mode=0o700)
            return subprocess.CompletedProcess(remote_arguments, 0, "", "")
        if command == "/usr/bin/ln":
            source = self._path(remote_arguments[1])
            destination = self._path(remote_arguments[2])
            try:
                os.link(source, destination)
            except FileExistsError:
                return subprocess.CompletedProcess(remote_arguments, 1, "", "")
            return subprocess.CompletedProcess(remote_arguments, 0, "", "")
        if command == "/usr/bin/chmod":
            self._path(remote_arguments[2]).chmod(int(remote_arguments[1], 8))
            return subprocess.CompletedProcess(remote_arguments, 0, "", "")
        if command == "/usr/bin/rm":
            self._path(remote_arguments[-1]).unlink(missing_ok=True)
            return subprocess.CompletedProcess(remote_arguments, 0, "", "")
        raise AssertionError(f"unexpected remote command: {remote_arguments}")

    def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
        del timeout
        target = self._path(destination)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o600)
        self.copied.append(destination)

    def copy_from(self, source: str, destination: Path, *, timeout: int) -> None:
        del timeout
        shutil.copyfile(self._path(source), destination)
        destination.chmod(0o600)


def test_claimed_incomplete_archive_repairs_support_before_verification(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    username = "runner"
    home = tmp_path / "remote"
    home.mkdir(mode=0o700)
    work_id = "c" * 64
    archive_digest = "b" * 64
    remote_work = f"/home/{username}/.fdai-state-handoff/{work_id[:24]}"
    work = home / ".fdai-state-handoff" / work_id[:24]
    root = work / "root"
    root.mkdir(mode=0o700, parents=True)
    work.chmod(0o700)
    root_file = root / "main.tf"
    root_file.write_text("terraform {}\n", encoding="utf-8")
    root_file.chmod(0o600)
    state = b'{"lineage":"synthetic","version":4}\n'
    local_state = work / "local-state.json"
    local_state.write_bytes(state)
    local_state.chmod(0o600)
    files = {
        "root/main.tf": {
            "sha256": hashlib.sha256(root_file.read_bytes()).hexdigest(),
            "executable": False,
        },
        "root/terraform.tfstate": {
            "sha256": hashlib.sha256(state).hexdigest(),
            "executable": False,
        },
    }
    manifest = {
        "schema_version": "fdai.genesis-foundation-state-archive.v1",
        "source_commit": SOURCE,
        "state_digest": hashlib.sha256(state).hexdigest(),
        "files": files,
    }
    manifest["manifest_digest"] = canonical_digest(manifest)
    _private_json(work / "manifest.json", manifest)

    directory = tmp_path / "recovery"
    directory.mkdir(mode=0o700)
    (directory / "source/infra").mkdir(mode=0o700, parents=True)
    _write_runner_support(directory / "source/infra")
    current_source = tmp_path / "current-source"
    current_support = current_source / "infra/genesis-runner-image"
    current_support.mkdir(mode=0o700, parents=True)
    shutil.copyfile(
        ROOT / "infra/genesis-runner-image/migrate-foundation-state.py",
        current_support / "migrate-foundation-state.py",
    )

    class Recovery:
        def __init__(self) -> None:
            self.directory = directory
            self.source = SimpleNamespace(commit="7" * 40, root=current_source)
            self.approvals = 0
            self.verifications = 0

        def verify_configuration(self) -> None:
            self.verifications += 1

        def require_approval(self) -> str:
            self.approvals += 1
            return "8" * 64

    recovery = Recovery()
    tunnel = SupportRepairTunnel(home, username)
    state_claim = {
        "schema_version": "fdai.genesis-foundation-state-handoff-claim.v1",
        "migration_source_commit": "6" * 40,
    }

    program, repair_digest = support_repair.repair_claimed_support(
        tunnel,
        recovery=recovery,
        state_claim=state_claim,
        directory=directory,
        remote_work=remote_work,
        username=username,
        work_id=work_id,
        archive_digest=archive_digest,
        timeout=900,
    )

    assert program == (
        "/usr/bin/python3",
        f"{remote_work}/{support_repair.REMOTE_VERIFIER_RELATIVE}",
    )
    assert (
        repair_digest
        == json.loads((directory / support_repair.SUPPORT_REPAIR_MANIFEST_NAME).read_bytes())[
            "manifest_digest"
        ]
    )
    assert recovery.approvals == 1
    assert len(tunnel.copied) == len(state_archive.RUNNER_SUPPORT_FILES) + 2
    assert (work / "genesis-runner-image/migrate-foundation-state.py").read_text(
        encoding="utf-8"
    ) == "migrate-foundation-state.py\n"
    assert (work / support_repair.REMOTE_VERIFIER_RELATIVE).read_bytes() == (
        ROOT / "infra/genesis-runner-image/migrate-foundation-state.py"
    ).read_bytes()
    assert (directory / support_repair.SUPPORT_REPAIR_CLAIM_NAME).is_file()
    assert (directory / support_repair.SUPPORT_REPAIR_RECEIPT_NAME).is_file()
    remote = _remote_module()
    arguments = SimpleNamespace(
        work_id=work_id,
        archive_digest=archive_digest,
        support_repair_digest=repair_digest,
    )
    repair_files = remote._support_repair_files(work, arguments)
    remote._verify_tree(work, migrated=True, repair_files=repair_files)
    with pytest.raises(ValueError, match="support repair manifest is invalid"):
        remote._support_repair_files(
            work,
            SimpleNamespace(
                work_id=work_id,
                archive_digest=archive_digest,
                support_repair_digest="0" * 64,
            ),
        )

    copied = list(tunnel.copied)
    assert support_repair.retained_repair_source_commit(directory) == "7" * 40
    recovery.source = SimpleNamespace(commit="9" * 40, root=current_source)
    assert support_repair.repair_claimed_support(
        tunnel,
        recovery=recovery,
        state_claim=state_claim,
        directory=directory,
        remote_work=remote_work,
        username=username,
        work_id=work_id,
        archive_digest=archive_digest,
        timeout=900,
    ) == (program, repair_digest)
    assert tunnel.copied == copied
    assert recovery.approvals == 1


def test_support_repair_refuses_to_replace_a_different_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    directory = tmp_path / "recovery"
    (directory / "source/infra").mkdir(mode=0o700, parents=True)
    directory.chmod(0o700)
    _write_runner_support(directory / "source/infra")
    actual = {name: None for name in state_archive.RUNNER_SUPPORT_FILES}
    actual[state_archive.RUNNER_SUPPORT_FILES[0]] = support_repair.RemoteFile("0" * 64, False)
    monkeypatch.setattr(
        support_repair,
        "_inspect_remote_support",
        lambda *args, **kwargs: support_repair.RemoteSupportStatus({}, actual, None, None),
    )

    class Recovery:
        def __init__(self) -> None:
            self.directory = directory
            self.source = SimpleNamespace(commit="7" * 40, root=directory / "source")
            self.approvals = 0

        def verify_configuration(self) -> None:
            pass

        def require_approval(self) -> str:
            self.approvals += 1
            return "8" * 64

    recovery = Recovery()
    tunnel = SupportRepairTunnel(tmp_path / "remote", "runner")
    with pytest.raises(ValueError, match="existing remote support file differs"):
        support_repair.repair_claimed_support(
            tunnel,
            recovery=recovery,
            state_claim={"migration_source_commit": "6" * 40},
            directory=directory,
            remote_work="/home/runner/.fdai-state-handoff/" + "c" * 24,
            username="runner",
            work_id="c" * 64,
            archive_digest="b" * 64,
            timeout=900,
        )
    assert recovery.approvals == 0
    assert not (directory / support_repair.SUPPORT_REPAIR_CLAIM_NAME).exists()


def test_legacy_authority_reuses_its_bound_remote_observation(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    work_id = "c" * 64
    observation = {
        "schema_version": "fdai.genesis-foundation-remote-state-observation.v1",
        "state": "verified",
        "work_id": work_id,
        "remote_state_digest": "d" * 64,
    }
    _private_json(tmp_path / f"remote-observation-{work_id[:12]}.json", observation)
    authority = {"observation_digest": canonical_digest(observation)}

    assert (
        state_command._authority_remote_state_digest(tmp_path, authority=authority, work_id=work_id)
        == "d" * 64
    )


@pytest.mark.parametrize("local_first", [False, True])
@pytest.mark.parametrize("separate_state", [False, True])
def test_private_archive_preserves_exact_state_and_executable_provider(
    tmp_path: Path,
    local_first: bool,
    separate_state: bool,
) -> None:
    tmp_path.chmod(0o700)
    root = tmp_path / "root"
    mirror = tmp_path / "mirror"
    root.mkdir(mode=0o700)
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir(mode=0o700)
    (bootstrap / "main.tf").write_text('module "identity" { source = "../modules/identity" }\n')
    modules = tmp_path / "modules/identity"
    modules.mkdir(mode=0o700, parents=True)
    (modules / "main.tf").write_text("terraform {}\n")
    runner_support = _write_runner_support(tmp_path)
    provider_dir = mirror / "registry.terraform.io/hashicorp/azurerm/4.81.0/linux_amd64"
    provider_dir.mkdir(mode=0o700, parents=True)
    state, _ = _state_inputs()
    state_path = (tmp_path if separate_state else root) / "terraform.tfstate"
    _private_json(state_path, state)
    (root / "main.tf").write_text(
        "terraform {}\n" if local_first else 'terraform { backend "azurerm" {} }\n',
        encoding="utf-8",
    )
    (root / "main.tf").chmod(0o600)
    if local_first:
        template = ROOT / "infra/genesis-foundation/backend.azurerm.tf.example"
        (root / template.name).write_bytes(template.read_bytes())
        (root / template.name).chmod(0o600)
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
        original_state=state_path if separate_state else None,
    )

    assert result["archive_digest"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert hashlib.sha256(state_path.read_bytes()).hexdigest() == state_digest
    if separate_state:
        assert not (root / "terraform.tfstate").exists()
    assert archive.stat().st_mode & 0o777 == 0o600
    remote = _remote_module()
    extracted = tmp_path / "extracted"
    extracted.mkdir(mode=0o700)
    copied_archive = tmp_path / "remote.tar.gz"
    copied_archive.write_bytes(archive.read_bytes())
    copied_archive.chmod(0o600)
    assert remote._extract_archive(copied_archive, extracted) == result["archive_digest"]
    remote._verify_tree(extracted, migrated=False)
    if local_first:
        assert (extracted / "root/backend.azurerm.tf").read_bytes() == template.read_bytes()
        assert not (root / "backend.azurerm.tf").exists()
        manifest = json.loads((extracted / "manifest.json").read_text())
        assert "root/backend.azurerm.tf" in manifest["files"]
    assert (extracted / "root/terraform.tfstate").read_bytes() == state_path.read_bytes()
    assert (extracted / "bootstrap/main.tf").read_bytes() == (bootstrap / "main.tf").read_bytes()
    assert (extracted / "modules/identity/main.tf").read_bytes() == (
        modules / "main.tf"
    ).read_bytes()
    for name in (
        "attest-runner.sh",
        "customize-runner-image.sh.tftpl",
        "enroll-runner.sh",
        "migrate-foundation-state.py",
        "toolchain.json",
    ):
        assert (extracted / "genesis-runner-image" / name).read_bytes() == (
            runner_support / name
        ).read_bytes()
    assert (extracted / provider.relative_to(tmp_path)).stat().st_mode & 0o777 == 0o700


def test_private_archive_requires_complete_runner_support(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    state, _ = _state_inputs()
    state_path = root / "terraform.tfstate"
    _private_json(state_path, state)
    (root / "main.tf").write_text("terraform {}\n", encoding="utf-8")
    mirror = tmp_path / "mirror"
    mirror.mkdir(mode=0o700)
    variables = tmp_path / "variables.json"
    _private_json(variables, {"env": "dev"})
    runner_support = tmp_path / "genesis-runner-image"
    runner_support.mkdir(mode=0o700)

    with pytest.raises(FileNotFoundError):
        create_foundation_state_archive(
            terraform_root=root,
            provider_mirror=mirror,
            variables_file=variables,
            destination=tmp_path / "handoff.tar.gz",
            source_commit=SOURCE,
            expected_state_digest=hashlib.sha256(state_path.read_bytes()).hexdigest(),
        )


@pytest.mark.parametrize("defect", ["digest", "second-state", "state-change"])
def test_separate_original_state_archive_rejects_ambiguous_ownership(tmp_path, monkeypatch, defect):
    import genesis_foundation_state_archive as archive_module

    tmp_path.chmod(0o700)
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    mirror = tmp_path / "mirror"
    mirror.mkdir(mode=0o700)
    (root / "main.tf").write_text("terraform {}\n")
    state, _ = _state_inputs()
    original_state = tmp_path / "terraform.tfstate"
    _private_json(original_state, state)
    expected_digest = hashlib.sha256(original_state.read_bytes()).hexdigest()
    variables = tmp_path / "variables.json"
    _private_json(variables, {"env": "dev"})
    _write_runner_support(tmp_path)
    if defect == "digest":
        expected_digest = "0" * 64
    elif defect == "second-state":
        _private_json(root / "terraform.tfstate", state)
    else:
        manifest = archive_module._file_manifest

        def change_state(stage):
            original_state.write_text("changed\n")
            return manifest(stage)

        monkeypatch.setattr(archive_module, "_file_manifest", change_state)
    destination = tmp_path / "handoff.tar.gz"
    with pytest.raises(
        ValueError, match="does not match|second state owner|original state changed"
    ):
        create_foundation_state_archive(
            terraform_root=root,
            provider_mirror=mirror,
            variables_file=variables,
            destination=destination,
            source_commit=SOURCE,
            expected_state_digest=expected_digest,
            original_state=original_state,
        )
    assert not destination.exists()


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
    _write_runner_support(state_dir.parent)
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
        self.calls.append(remote_arguments)
        if remote_arguments[:2] == ("/usr/bin/python3", "-"):
            assert input_text is not None
            assert "--expected-remote-state-digest" in remote_arguments
            assert "expected-remote-state-digest" in input_text
            mode = remote_arguments[2]
        else:
            assert input_text is None
            mode = remote_arguments[1] if len(remote_arguments) > 1 else ""
        if remote_arguments[0] == "/usr/local/sbin/fdai-attest-runner":
            return subprocess.CompletedProcess(
                remote_arguments, 0, "attestation_complete transport=manual slots=2\n", ""
            )
        if remote_arguments[0] == "/usr/bin/test":
            return subprocess.CompletedProcess(remote_arguments, 0, "", "")
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
    monkeypatch.setattr(
        state_command,
        "repair_claimed_support",
        lambda *args, **kwargs: (support_repair.INSTALLED_MIGRATION_PROGRAM, None),
    )

    def archive(**kwargs: object) -> dict[str, object]:
        destination = Path(str(kwargs["archive"]))
        destination.write_bytes(b"archive")
        destination.chmod(0o600)
        return {"archive_digest": ARCHIVE_DIGEST}

    monkeypatch.setattr(state_command, "_prepare_archive", archive)


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "missing-approval",
        "wrong-stage",
        "changed-config",
        "changed-host-key",
        "failed-effect",
        "wrong-actor",
        "wrong-source",
    ],
)
def test_recovered_state_uses_original_owner_and_exact_approval(tmp_path, monkeypatch, defect):
    import genesis_foundation_recovery_state as recovery_state
    from genesis_foundation_recovery_handoff import RecoveryHandoff

    original, profile, prior, evidence = _prepare(tmp_path)
    _mock_boundaries(monkeypatch, original, evidence)
    monkeypatch.setattr(FakeTunnel, "fail_migration", defect == "failed-effect")
    source_state = (
        original / "foundation-apply-bundle/source/infra/genesis-foundation/terraform.tfstate"
    )
    source_state.parent.mkdir(mode=0o700, parents=True)
    (original / prior["state_ref"]).rename(source_state)
    (tmp_path / "source-execution.lock").touch(mode=0o600)
    directory = tmp_path / "recovery"
    directory.mkdir(mode=0o700)
    configuration = directory / "source/infra/genesis-foundation"
    configuration.mkdir(mode=0o700, parents=True)
    _write_runner_support(configuration.parent)
    (configuration / "main.tf").write_text("terraform {}\n")
    (directory / "terraform-data/providers").mkdir(mode=0o700, parents=True)
    provider = directory / "terraform-data/providers/provider"
    provider.write_bytes(b"synthetic-provider")
    provider.chmod(0o700)
    _private_json(directory / "recovery-variables.json", {"env": "dev"})
    review = {
        "configuration_digest": recovery_state.image._execution_tree_digest(directory / "source"),
        "provider_digest": recovery_state.image._execution_tree_digest(
            directory / "terraform-data"
        ),
        "variables_digest": canonical_digest({"env": "dev"}),
        "original_lineage_digest": canonical_digest({"lineage": evidence["state"]["lineage"]}),
    }
    review["review_digest"] = canonical_digest(review)
    _private_json(directory / "recovery-review.json", review)
    handoff = json.loads((original / state_command.foundation_apply.HANDOFF_NAME).read_bytes())
    handoff["runner"].update(parallelism=2, execution_transport="manual", toolchain_digest="a" * 64)
    recovered_receipt = {
        "receipt_digest": "5" * 64,
        "review_digest": review["review_digest"],
        "source_commit": SOURCE,
        "execution_source_commit": "6" * 40,
        "state_digest": prior["state_digest"],
        "handoff_digest": canonical_digest(handoff),
    }
    recovered = RecoveryHandoff(recovered_receipt, handoff, BINDING)
    monkeypatch.setattr(recovery_state, "load_recovery_evidence", lambda **_kwargs: recovered)
    migration_source = ["7" * 40]
    monkeypatch.setattr(
        recovery_state,
        "inspect_source",
        lambda *_args: SimpleNamespace(commit=migration_source[0], reverify=lambda: None),
    )
    monkeypatch.setattr(recovery_state, "current_actor_digest", lambda _binding: "8" * 64)
    known_hosts = directory / state_command.KNOWN_HOSTS_NAME
    known_hosts.write_text("synthetic-host-key\n")
    known_hosts.chmod(0o600)
    enrollment_command = recovery_state.enrollment_command
    names = enrollment_command._runner_names(handoff["runner"]["vm_name"], 2)
    repository_digest = hashlib.sha256(f"manual:{BINDING}".encode()).hexdigest()
    claim = enrollment_command._create_claim(
        foundation=recovered.foundation_reference,
        repository_digest=repository_digest,
        expected_names=names,
        actor_digest="8" * 64,
        host_key_digest=hashlib.sha256(known_hosts.read_bytes()).hexdigest(),
    )
    claim["enrollment_source_commit"] = "9" * 40
    _private_json(directory / enrollment_command.CLAIM_NAME, claim)
    enrolled = {
        "schema_version": "fdai.genesis-runner-enrollment-receipt.v1",
        "state": "attested",
        **recovered.foundation_reference,
        "foundation_receipt_digest": recovered_receipt["receipt_digest"],
        "foundation_evidence_schema": "fdai.foundation-recovery-receipt.v1",
        "enrollment_source_commit": "9" * 40,
        "repository_digest": repository_digest,
        "runner_names": names,
        "runner_count": 2,
        "runner_set_digest": enrollment_command._runner_set_digest(
            enrollment_command._manual_host_set(names)
        ),
        "claim_digest": canonical_digest(claim),
        "actor_digest": claim["actor_digest"],
        "host_key_digest": claim["host_key_digest"],
        "toolchain_digest": "a" * 64,
        "identity_attested": True,
        "services_attested": True,
        "github_readback_verified": False,
        "manual_host_readback_verified": True,
        "effect_verified": True,
        "mutation_performed": False,
        "subscription_ready": False,
    }
    enrolled.pop("receipt_digest")
    enrolled["receipt_digest"] = canonical_digest(enrolled)
    _private_json(directory / enrollment_command.RECEIPT_NAME, enrolled)
    now = datetime.now(UTC).replace(microsecond=0)
    approval = {
        "schema_version": "fdai.genesis-approval.v1",
        "approved": True,
        "run_binding": recovered_receipt["receipt_digest"],
        "source_commit": "7" * 40,
        "stage": "foundation-state",
        "actor_digest": "8" * 64,
        "evidence": {
            "foundation_receipt_digest": recovered_receipt["receipt_digest"],
            "enrollment_receipt_digest": enrolled["receipt_digest"],
        },
        "approved_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=30)).isoformat(),
    }
    if defect == "wrong-stage":
        approval.update(
            stage="runner-enrollment",
            evidence={"foundation_receipt_digest": recovered_receipt["receipt_digest"]},
        )
    if defect == "wrong-actor":
        approval["actor_digest"] = "0" * 64
    elif defect == "wrong-source":
        approval["source_commit"] = "0" * 40
    approval_path = tmp_path / "migration-approval.json"
    _private_json(approval_path, approval)
    if defect == "changed-config":
        (configuration / "main.tf").write_text("changed\n")
    elif defect == "changed-host-key":
        known_hosts.write_text("changed\n")
    arguments = [
        "--foundation-plan-directory",
        str(original),
        "--profile",
        str(profile),
        "--variables-file",
        str(directory / "recovery-variables.json"),
        "--source-snapshot",
        str(tmp_path / "snapshot"),
        "--source-snapshot-digest",
        "b" * 64,
        "--terraform",
        str(tmp_path / "terraform"),
        "--repository",
        "example/repository",
        "--ssh-private-key",
        str(tmp_path / "id_ed25519"),
        "--expected-foundation-receipt-digest",
        str(recovered_receipt["receipt_digest"]),
        "--expected-enrollment-receipt-digest",
        str(enrolled["receipt_digest"]),
        "--foundation-recovery-directory",
        str(directory),
        "--timeout-seconds",
        "900",
    ]
    approved = arguments + ["--approve"]
    if defect != "missing-approval":
        approved += ["--recovery-approval-file", str(approval_path)]
    first = state_command.main(approved)
    if defect in {
        "missing-approval",
        "wrong-stage",
        "changed-config",
        "changed-host-key",
        "wrong-actor",
        "wrong-source",
    }:
        assert first == 3
        assert not FakeTunnel.calls
        assert source_state.exists()
        assert not (directory / state_command.CLAIM_NAME).exists()
        return
    if defect == "failed-effect":
        assert first == 3
        assert source_state.exists()
        FakeTunnel.fail_migration = False
        assert state_command.main(approved) == 3
        migration_source[0] = "d" * 40
        assert state_command.main(arguments + ["--resume-verification"]) == 0
    else:
        assert first == 0
    assert len(FakeTunnel.copied) == 1
    assert not source_state.exists()
    assert not (configuration / "terraform.tfstate").exists()
    result = json.loads((directory / state_command.RECEIPT_NAME).read_bytes())
    assert result["migration_source_commit"] == migration_source[0]
    assert result["foundation_receipt_digest"] == recovered_receipt["receipt_digest"]
    assert result["actor_digest"] == approval["actor_digest"]
    assert result["zero_change_verified"] is True
    assert result["local_state_deleted"] is True
    assert any(command[0] == "/usr/local/sbin/fdai-attest-runner" for command in FakeTunnel.calls)
    assert (
        json.loads((original / state_command.foundation_apply.RECEIPT_NAME).read_bytes()) == prior
    )
    migration_source[0] = "e" * 40
    FakeTunnel.calls = []
    assert state_command.main(arguments + ["--resume-verification"]) == 0
    assert len(FakeTunnel.copied) == 1
    assert [command[:3] for command in FakeTunnel.calls] == [("/usr/bin/python3", "-", "observe")]
    authority_path = directory / state_command.AUTHORITY_NAME
    authority = json.loads(authority_path.read_bytes())
    authority["zero_change_verified"] = False
    authority["authority_digest"] = canonical_digest(
        {key: value for key, value in authority.items() if key != "authority_digest"}
    )
    authority_path.write_text(json.dumps(authority))
    FakeTunnel.calls = []
    assert state_command.main(arguments + ["--resume-verification"]) == 3
    assert not FakeTunnel.calls


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

    assert [call[:3] for call in FakeTunnel.calls] == [("/usr/bin/python3", "-", "observe")]
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
        SCRIPT_DIR / "genesis_foundation_state_support_repair.py",
        ROOT / "infra/genesis-runner-image/migrate-foundation-state.py",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "from datetime import UTC" not in source
        compile(source, str(path), "exec")

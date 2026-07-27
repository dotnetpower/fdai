"""Tests for planning the app layer from a signed offline kit."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai.deployment_cli.cli import main
from fdai.deployment_cli.provision_plan import (
    CLI_CONFIG_NAME,
    PLAN_FILE_NAME,
    PLAN_JSON_NAME,
    CommandResult,
    ProvisionPlanError,
    ProvisionPlanResult,
    run_provision_plan,
    summarize_highlighted_changes,
)

_PLATFORM = "linux-x86_64"
_VERSION = "0.1.5"

_TERRAFORM_STUB = """#!/usr/bin/env bash
set -eu
command="$1"
shift
case "$command" in
  init)
    printf '%s\\n' "$TF_CLI_CONFIG_FILE" > "$ARM_RECORD_DIR/init-config"
    printf '%s\\n' "$TF_DATA_DIR" > "$ARM_RECORD_DIR/init-data-dir"
    printf '%s\\n' "$@" > "$ARM_RECORD_DIR/init-args"
    ;;
  plan)
    for argument in "$@"; do
      case "$argument" in
        -out=*) printf 'binary-plan-bytes' > "${argument#-out=}" ;;
      esac
    done
    printf '%s\\n' "$@" > "$ARM_RECORD_DIR/plan-args"
    ;;
  show)
    cat "$ARM_PLAN_JSON_SOURCE"
    ;;
esac
"""

_PLAN_JSON = json.dumps(
    {
        "format_version": "1.2",
        "resource_changes": [
            {"type": "azurerm_storage_account", "change": {"actions": ["create"]}},
            {"type": "azurerm_key_vault", "change": {"actions": ["delete"]}},
            {"type": "azurerm_subnet", "change": {"actions": ["delete", "create"]}},
            {"type": "azurerm_role_assignment", "change": {"actions": ["update"]}},
            {"type": "azurerm_role_assignment", "change": {"actions": ["no-op"]}},
        ],
    }
)


@contextmanager
def _patched_environment(values: Mapping[str, str]) -> Iterator[None]:
    """Replace the process environment so the CLI default path is exercised."""
    original = dict(os.environ)
    os.environ.clear()
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _public_key(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _write_kit(root: Path, *, terraform: bytes = b"terraform") -> bytes:
    artifacts = {
        f"python/fdai-{_VERSION}-py3-none-any.whl": b"wheel",
        f"deployment/fdai-deployment-bundle-{_VERSION}.tar.gz": b"bundle",
        "terraform/terraform": terraform,
        "terraform/providers/registry.terraform.io/hashicorp/azurerm/provider": b"provider",
        "bin/opa": b"opa",
        "sbom/offline-kit.cdx.json": b"{}",
    }
    for relative, content in artifacts.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    binary = root / "terraform/terraform"
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    manifest = {
        "schema_version": "fdai.deployment.offline-kit.v1",
        "kit_version": _VERSION,
        "cli_version": _VERSION,
        "bundle_version": _VERSION,
        "platform_tag": _PLATFORM,
        "python_wheel": f"python/fdai-{_VERSION}-py3-none-any.whl",
        "deployment_bundle": f"deployment/fdai-deployment-bundle-{_VERSION}.tar.gz",
        "terraform_binary": "terraform/terraform",
        "provider_mirror_prefix": "terraform/providers",
        "opa_binary": "bin/opa",
        "sbom_path": "sbom/offline-kit.cdx.json",
        "files": {
            path: hashlib.sha256(content).hexdigest() for path, content in sorted(artifacts.items())
        },
    }
    manifest_bytes = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    )
    private_key = Ed25519PrivateKey.generate()
    (root / "offline-kit.json").write_bytes(manifest_bytes)
    (root / "offline-kit.json.sig").write_bytes(private_key.sign(manifest_bytes))
    return _public_key(private_key)


def _write_infra(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "main.tf").write_text('resource "null_resource" "example" {}\n', encoding="utf-8")
    return root


class _RecordingRunner:
    """Collect every invocation instead of executing Terraform."""

    def __init__(self, *, plan_exit: int = 0, show_stdout: str = _PLAN_JSON) -> None:
        self.calls: list[tuple[tuple[str, ...], Path, dict[str, str]]] = []
        self._plan_exit = plan_exit
        self._show_stdout = show_stdout

    def __call__(
        self,
        command: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        timeout: int,
    ) -> CommandResult:
        self.calls.append((tuple(command), cwd, dict(env)))
        if command[1] == "plan":
            for argument in command:
                if argument.startswith("-out="):
                    Path(argument.removeprefix("-out=")).write_bytes(b"binary-plan-bytes")
            return CommandResult(returncode=self._plan_exit, stdout="", stderr="planning failed")
        if command[1] == "show":
            return CommandResult(returncode=0, stdout=self._show_stdout, stderr="")
        return CommandResult(returncode=0, stdout="", stderr="")


def _plan(tmp_path: Path, release_root: bytes, **overrides: object) -> ProvisionPlanResult:
    arguments: dict[str, object] = {
        "kit_root": tmp_path / "kit",
        "infra_dir": tmp_path / "infra",
        "work_dir": tmp_path / "work",
        "release_root_pem": release_root,
        "cli_version": _VERSION,
        "platform_tag": _PLATFORM,
        "environ": {},
    }
    arguments.update(overrides)
    return run_provision_plan(**arguments)  # type: ignore[arg-type]


def test_plans_from_verified_kit_with_pinned_mirror(tmp_path: Path) -> None:
    release_root = _write_kit(tmp_path / "kit")
    _write_infra(tmp_path / "infra")
    runner = _RecordingRunner()

    result = _plan(tmp_path, release_root, runner=runner)

    assert result.plan_path == str((tmp_path / "work" / PLAN_FILE_NAME).resolve())
    assert result.plan_digest == hashlib.sha256(b"binary-plan-bytes").hexdigest()
    assert result.mutation_performed is False
    assert json.loads(result.to_json())["schema_version"] == "fdai.deployment-cli.provision-plan.v1"
    plan_json = Path(result.plan_json_path).read_text(encoding="utf-8")
    assert json.loads(plan_json)["format_version"] == "1.2"
    executed = {call[0][0] for call in runner.calls}
    assert executed == {str(tmp_path / "kit" / "terraform" / "terraform")}
    assert [call[0][1] for call in runner.calls] == ["init", "plan", "show"]


def test_generated_cli_config_has_no_path_to_the_public_registry(tmp_path: Path) -> None:
    release_root = _write_kit(tmp_path / "kit")
    _write_infra(tmp_path / "infra")
    runner = _RecordingRunner()

    _plan(tmp_path, release_root, runner=runner)

    config = (tmp_path / "work" / CLI_CONFIG_NAME).read_text(encoding="utf-8")
    assert str((tmp_path / "kit" / "terraform" / "providers").resolve()) in config
    assert "direct {" in config
    assert 'exclude = ["*/*"]' in config
    _init_command, _cwd, env = runner.calls[0]
    assert env["TF_CLI_CONFIG_FILE"] == str(tmp_path / "work" / CLI_CONFIG_NAME)


def test_a_file_added_beside_the_binary_makes_the_kit_unusable(tmp_path: Path) -> None:
    release_root = _write_kit(tmp_path / "kit")
    _write_infra(tmp_path / "infra")
    decoy = tmp_path / "kit" / "terraform" / "terraform.new"
    decoy.write_bytes(b"decoy")
    runner = _RecordingRunner()

    with pytest.raises(ProvisionPlanError, match="not usable for planning"):
        _plan(tmp_path, release_root, runner=runner)

    assert runner.calls == []


def test_tampered_kit_stops_before_any_execution(tmp_path: Path) -> None:
    release_root = _write_kit(tmp_path / "kit")
    _write_infra(tmp_path / "infra")
    (tmp_path / "kit" / "bin" / "opa").write_bytes(b"replaced")
    runner = _RecordingRunner()

    with pytest.raises(ProvisionPlanError, match="not usable for planning"):
        _plan(tmp_path, release_root, runner=runner)

    assert runner.calls == []


def test_non_executable_terraform_reports_the_lost_permission(tmp_path: Path) -> None:
    release_root = _write_kit(tmp_path / "kit")
    _write_infra(tmp_path / "infra")
    binary = tmp_path / "kit" / "terraform" / "terraform"
    binary.chmod(0o600)
    runner = _RecordingRunner()

    with pytest.raises(ProvisionPlanError, match="not executable"):
        _plan(tmp_path, release_root, runner=runner)

    assert runner.calls == []


def test_detailed_exit_code_two_is_pending_changes_not_a_failure(tmp_path: Path) -> None:
    release_root = _write_kit(tmp_path / "kit")
    _write_infra(tmp_path / "infra")

    result = _plan(tmp_path, release_root, runner=_RecordingRunner(plan_exit=2))

    assert result.changes_present is True


def test_failed_plan_surfaces_the_terraform_error(tmp_path: Path) -> None:
    release_root = _write_kit(tmp_path / "kit")
    _write_infra(tmp_path / "infra")

    with pytest.raises(ProvisionPlanError, match="planning failed"):
        _plan(tmp_path, release_root, runner=_RecordingRunner(plan_exit=1))


def test_credentials_pass_through_but_unrelated_environment_does_not(tmp_path: Path) -> None:
    release_root = _write_kit(tmp_path / "kit")
    _write_infra(tmp_path / "infra")
    runner = _RecordingRunner()

    _plan(
        tmp_path,
        release_root,
        runner=runner,
        environ={
            "ARM_CLIENT_ID": "client",
            "TF_VAR_region": "koreacentral",
            "PATH": "/usr/bin",
            "FDAI_INTEGRITY_KEY": "/private/key.pem",
        },
    )

    _command, _cwd, env = runner.calls[0]
    assert env["ARM_CLIENT_ID"] == "client"
    assert env["TF_VAR_region"] == "koreacentral"
    assert env["TF_IN_AUTOMATION"] == "1"
    assert "FDAI_INTEGRITY_KEY" not in env


def test_plan_and_plan_json_are_owner_readable_only(tmp_path: Path) -> None:
    release_root = _write_kit(tmp_path / "kit")
    _write_infra(tmp_path / "infra")

    result = _plan(tmp_path, release_root, runner=_RecordingRunner())

    for path in (result.plan_path, result.plan_json_path):
        assert stat.S_IMODE(Path(path).stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "work").stat().st_mode) == 0o700


def test_missing_plan_file_after_a_successful_plan_is_an_error(tmp_path: Path) -> None:
    release_root = _write_kit(tmp_path / "kit")
    _write_infra(tmp_path / "infra")

    class _SilentRunner(_RecordingRunner):
        def __call__(
            self,
            command: Sequence[str],
            cwd: Path,
            env: Mapping[str, str],
            timeout: int,
        ) -> CommandResult:
            if command[1] == "plan":
                return CommandResult(returncode=0, stdout="", stderr="")
            return super().__call__(command, cwd, env, timeout)

    with pytest.raises(ProvisionPlanError, match="wrote no plan file"):
        _plan(tmp_path, release_root, runner=_SilentRunner())


def test_directory_without_terraform_configuration_is_rejected(tmp_path: Path) -> None:
    release_root = _write_kit(tmp_path / "kit")
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / "README.md").write_text("not infrastructure\n", encoding="utf-8")

    with pytest.raises(ProvisionPlanError, match="no Terraform configuration"):
        _plan(tmp_path, release_root, runner=_RecordingRunner())


def test_symlinked_work_directory_is_rejected(tmp_path: Path) -> None:
    release_root = _write_kit(tmp_path / "kit")
    _write_infra(tmp_path / "infra")
    (tmp_path / "real-work").mkdir()
    (tmp_path / "linked-work").symlink_to(tmp_path / "real-work")

    with pytest.raises(ProvisionPlanError, match="MUST NOT be a symlink"):
        _plan(tmp_path, release_root, work_dir=tmp_path / "linked-work", runner=_RecordingRunner())


def test_mirror_path_cannot_inject_terraform_interpolation(tmp_path: Path) -> None:
    root = tmp_path / "kit-${injected}"
    release_root = _write_kit(root)
    _write_infra(tmp_path / "infra")

    _plan(tmp_path, release_root, kit_root=root, runner=_RecordingRunner())

    config = (tmp_path / "work" / CLI_CONFIG_NAME).read_text(encoding="utf-8")
    assert "$${injected}" in config
    assert "${injected}" not in config.replace("$${injected}", "")


def test_highlighted_changes_count_each_class_once() -> None:
    highlighted = summarize_highlighted_changes(_PLAN_JSON)

    assert highlighted.destroy == 1
    assert highlighted.replace == 1
    assert highlighted.role_change == 1
    assert highlighted.to_dict() == {"destroy": 1, "replace": 1, "role_change": 1}


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        json.dumps([]),
        json.dumps({"resource_changes": {}}),
        json.dumps({"resource_changes": [{"type": "x"}]}),
        json.dumps({"resource_changes": [{"type": "x", "change": {"actions": [1]}}]}),
    ],
)
def test_unreadable_plan_json_never_reports_an_empty_blast_radius(payload: str) -> None:
    with pytest.raises(ProvisionPlanError):
        summarize_highlighted_changes(payload)


def test_end_to_end_against_a_real_terraform_process(tmp_path: Path) -> None:
    release_root = _write_kit(tmp_path / "kit", terraform=_TERRAFORM_STUB.encode("utf-8"))
    _write_infra(tmp_path / "infra")
    records = tmp_path / "records"
    records.mkdir()
    plan_json_source = tmp_path / "plan-source.json"
    plan_json_source.write_text(_PLAN_JSON, encoding="utf-8")
    variables = tmp_path / "dev.tfvars"
    variables.write_text('region = "koreacentral"\n', encoding="utf-8")

    result = _plan(
        tmp_path,
        release_root,
        var_files=(variables,),
        environ={
            "PATH": os.environ.get("PATH", ""),
            "ARM_RECORD_DIR": str(records),
            "ARM_PLAN_JSON_SOURCE": str(plan_json_source),
        },
    )

    assert result.plan_digest == hashlib.sha256(b"binary-plan-bytes").hexdigest()
    assert result.highlighted.destroy == 1
    assert (records / "init-config").read_text(encoding="utf-8").strip() == str(
        tmp_path / "work" / CLI_CONFIG_NAME
    )
    assert (records / "init-data-dir").read_text(encoding="utf-8").strip() == str(
        tmp_path / "work" / "terraform-data"
    )
    assert f"-var-file={variables}" in (records / "plan-args").read_text(encoding="utf-8")
    assert (tmp_path / "work" / PLAN_JSON_NAME).is_file()


def test_cli_reports_the_plan_as_machine_readable_json(tmp_path: Path) -> None:
    release_root = _write_kit(tmp_path / "kit", terraform=_TERRAFORM_STUB.encode("utf-8"))
    _write_infra(tmp_path / "infra")
    records = tmp_path / "records"
    records.mkdir()
    plan_json_source = tmp_path / "plan-source.json"
    plan_json_source.write_text(_PLAN_JSON, encoding="utf-8")
    root_path = tmp_path / "release-root.pub"
    root_path.write_bytes(release_root)
    stdout = io.StringIO()

    with _patched_environment(
        {
            "PATH": os.environ.get("PATH", ""),
            "ARM_RECORD_DIR": str(records),
            "ARM_PLAN_JSON_SOURCE": str(plan_json_source),
        }
    ):
        exit_code = main(
            [
                "provision",
                "plan",
                "--offline-kit",
                str(tmp_path / "kit"),
                "--release-root",
                str(root_path),
                "--infra-dir",
                str(tmp_path / "infra"),
                "--work-dir",
                str(tmp_path / "work"),
                "--cli-version",
                _VERSION,
                "--platform-tag",
                _PLATFORM,
                "--output",
                "json",
            ],
            stdout=stdout,
        )

    assert exit_code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["mutation_performed"] is False
    assert payload["highlighted"] == {"destroy": 1, "replace": 1, "role_change": 1}


def test_cli_refuses_a_missing_release_root_without_a_traceback(tmp_path: Path) -> None:
    _write_kit(tmp_path / "kit")
    _write_infra(tmp_path / "infra")
    stdout = io.StringIO()

    exit_code = main(
        [
            "provision",
            "plan",
            "--offline-kit",
            str(tmp_path / "kit"),
            "--release-root",
            str(tmp_path / "absent.pub"),
            "--infra-dir",
            str(tmp_path / "infra"),
            "--work-dir",
            str(tmp_path / "work"),
            "--cli-version",
            _VERSION,
            "--platform-tag",
            _PLATFORM,
            "--output",
            "json",
        ],
        stdout=stdout,
    )

    assert exit_code == 4
    assert json.loads(stdout.getvalue())["schema_version"] == (
        "fdai.deployment-cli.provision-plan.v1"
    )


def test_an_unreadable_infra_directory_is_reported_as_a_plan_error(tmp_path: Path) -> None:
    release_root = _write_kit(tmp_path / "kit")
    infra = _write_infra(tmp_path / "infra")
    infra.chmod(0o000)
    try:
        with pytest.raises(ProvisionPlanError, match="could not be read"):
            _plan(tmp_path, release_root, runner=_RecordingRunner())
    finally:
        infra.chmod(0o700)


def test_a_work_directory_that_cannot_be_restricted_stops_the_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release_root = _write_kit(tmp_path / "kit")
    _write_infra(tmp_path / "infra")
    work = tmp_path / "work"
    work.mkdir()
    original = Path.chmod

    def refuse(self: Path, mode: int, **kwargs: object) -> None:
        if self == work:
            raise PermissionError("not the owner")
        original(self, mode)

    monkeypatch.setattr(Path, "chmod", refuse)

    with pytest.raises(ProvisionPlanError, match="restricted to its owner"):
        _plan(tmp_path, release_root, runner=_RecordingRunner())


def test_a_plan_path_swapped_for_a_link_is_refused_before_it_is_digested(
    tmp_path: Path,
) -> None:
    release_root = _write_kit(tmp_path / "kit")
    _write_infra(tmp_path / "infra")
    secret = tmp_path / "secret"
    secret.write_bytes(b"not-the-plan")

    class _LinkingRunner(_RecordingRunner):
        def __call__(
            self,
            command: Sequence[str],
            cwd: Path,
            env: Mapping[str, str],
            timeout: int,
        ) -> CommandResult:
            if command[1] == "plan":
                out = next(item for item in command if item.startswith("-out="))
                Path(out.removeprefix("-out=")).symlink_to(secret)
                return CommandResult(returncode=0, stdout="", stderr="")
            return super().__call__(command, cwd, env, timeout)

    with pytest.raises(ProvisionPlanError, match="wrote no plan file"):
        _plan(tmp_path, release_root, runner=_LinkingRunner())

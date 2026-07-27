"""Plan the app layer from a signed offline kit without any public egress.

Step five of a disconnected handover used to be a checklist: unpack the kit,
find the Terraform binary, hand-write a provider-mirror configuration, and hope
the operator remembered to close the public registry fallback. This module owns
that step instead.

Three properties matter more than convenience. The Terraform binary and the
provider mirror are resolved from the *signed manifest*, so a tree added beside
the kit cannot decide what gets executed. The generated CLI configuration
excludes direct installation, so a missing mirror entry fails the plan rather
than silently reaching the public registry. And the emitted binary plan is
digested, because the apply step is defined as consuming that exact plan.

Terraform remains the execution engine and the source of truth; this module
supplies its inputs and reads its outputs.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess  # noqa: S404 - Terraform is the execution engine; argv is a list, never a shell
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NamedTuple

from fdai.deployment_cli.offline_kit import (
    OfflineKitManifest,
    OfflineKitVerificationError,
    verify_offline_kit_contents,
)

PROVISION_PLAN_SCHEMA: Final = "fdai.deployment-cli.provision-plan.v1"
PLAN_FILE_NAME: Final = "app-layer.tfplan"
PLAN_JSON_NAME: Final = "app-layer.tfplan.json"
CLI_CONFIG_NAME: Final = "offline.tfrc"
_TERRAFORM_DATA_DIR: Final = "terraform-data"
_INIT_TIMEOUT_SECONDS: Final = 900
_PLAN_TIMEOUT_SECONDS: Final = 1800
_SHOW_TIMEOUT_SECONDS: Final = 300
_MAX_PLAN_JSON_BYTES: Final = 256 * 1024 * 1024
_ERROR_TAIL_LINES: Final = 20
_ERROR_TAIL_CHARS: Final = 4000
_REPLACE_ACTIONS: Final = frozenset({("create", "delete"), ("delete", "create")})
_ROLE_RESOURCE_MARKERS: Final = ("role_assignment", "role_definition")
_ENV_PREFIX_ALLOWLIST: Final = ("ARM_", "AZURE_", "MSI_", "IDENTITY_", "TF_VAR_")
_ENV_NAME_ALLOWLIST: Final = (
    "HOME",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "LANG",
    "LC_ALL",
    "NO_PROXY",
    "PATH",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TMPDIR",
    "https_proxy",
    "http_proxy",
    "no_proxy",
)


class ProvisionPlanError(RuntimeError):
    """The app layer could not be planned from the offline kit."""

    def to_json(self) -> str:
        return json.dumps(
            {"error": str(self), "schema_version": PROVISION_PLAN_SCHEMA},
            sort_keys=True,
            separators=(",", ":"),
        )


class CommandResult(NamedTuple):
    """One completed Terraform invocation."""

    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], Path, Mapping[str, str], int], CommandResult]


@dataclass(frozen=True, slots=True)
class HighlightedChanges:
    """Change classes that a human approver has to see before an apply."""

    destroy: int
    replace: int
    role_change: int

    def to_dict(self) -> dict[str, int]:
        return {
            "destroy": self.destroy,
            "replace": self.replace,
            "role_change": self.role_change,
        }


@dataclass(frozen=True, slots=True)
class ProvisionPlanResult:
    """One binary plan produced from verified kit content."""

    kit_version: str
    cli_version: str
    bundle_version: str
    platform_tag: str
    manifest_digest: str
    plan_path: str
    plan_digest: str
    plan_json_path: str
    changes_present: bool
    highlighted: HighlightedChanges
    mutation_performed: bool = False
    provider_source: str = "offline-kit-mirror"
    schema_version: str = PROVISION_PLAN_SCHEMA

    @property
    def exit_code(self) -> int:
        return 0

    def to_dict(self) -> dict[str, object]:
        return {
            "bundle_version": self.bundle_version,
            "changes_present": self.changes_present,
            "cli_version": self.cli_version,
            "highlighted": self.highlighted.to_dict(),
            "kit_version": self.kit_version,
            "manifest_digest": self.manifest_digest,
            "mutation_performed": self.mutation_performed,
            "plan_digest": self.plan_digest,
            "plan_json_path": self.plan_json_path,
            "plan_path": self.plan_path,
            "platform_tag": self.platform_tag,
            "provider_source": self.provider_source,
            "schema_version": self.schema_version,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def run_provision_plan(
    *,
    kit_root: Path,
    infra_dir: Path,
    work_dir: Path,
    release_root_pem: bytes,
    cli_version: str,
    platform_tag: str,
    var_files: Sequence[Path] = (),
    backend_config_files: Sequence[Path] = (),
    environ: Mapping[str, str] | None = None,
    runner: CommandRunner | None = None,
) -> ProvisionPlanResult:
    """Verify the kit, then plan ``infra_dir`` with the kit's pinned toolchain.

    Verification is not optional. Reporting on an unverified kit is a
    judgement an operator can weigh; executing a binary out of one is not, so
    a kit that fails to verify stops the plan here.
    """
    try:
        manifest, verification = verify_offline_kit_contents(
            kit_root,
            release_root_pem=release_root_pem,
            cli_version=cli_version,
            platform_tag=platform_tag,
        )
    except (OfflineKitVerificationError, ValueError) as exc:
        raise ProvisionPlanError(f"offline kit is not usable for planning: {exc}") from exc

    terraform = _resolve_terraform_binary(kit_root, manifest)
    mirror = _resolve_provider_mirror(kit_root, manifest)
    infra = _resolve_infra_dir(infra_dir)
    work = _prepare_work_dir(work_dir)
    var_arguments = _resolve_input_files(var_files, label="variable file")
    backend_arguments = _resolve_input_files(backend_config_files, label="backend config file")

    cli_config = work / CLI_CONFIG_NAME
    _write_private_text(cli_config, _render_cli_config(mirror))
    plan_path = work / PLAN_FILE_NAME
    plan_json_path = work / PLAN_JSON_NAME
    for stale in (plan_path, plan_json_path):
        stale.unlink(missing_ok=True)

    env = _terraform_environment(
        environ if environ is not None else os.environ,
        cli_config=cli_config,
        data_dir=work / _TERRAFORM_DATA_DIR,
    )
    execute = runner or _subprocess_runner

    init_command = [str(terraform), "init", "-input=false", "-no-color"]
    init_command.extend(f"-backend-config={path}" for path in backend_arguments)
    _run_step(execute, init_command, infra, env, _INIT_TIMEOUT_SECONDS, step="init")

    plan_command = [
        str(terraform),
        "plan",
        "-input=false",
        "-no-color",
        "-lock=true",
        "-detailed-exitcode",
        f"-out={plan_path}",
    ]
    plan_command.extend(f"-var-file={path}" for path in var_arguments)
    plan_result = _run_step(
        execute,
        plan_command,
        infra,
        env,
        _PLAN_TIMEOUT_SECONDS,
        step="plan",
        success_codes=(0, 2),
    )
    changes_present = plan_result.returncode == 2
    if not plan_path.is_file():
        raise ProvisionPlanError("terraform plan reported success but wrote no plan file")
    plan_path.chmod(0o600)

    show_result = _run_step(
        execute,
        [str(terraform), "show", "-json", str(plan_path)],
        infra,
        env,
        _SHOW_TIMEOUT_SECONDS,
        step="show",
    )
    if len(show_result.stdout.encode("utf-8")) > _MAX_PLAN_JSON_BYTES:
        raise ProvisionPlanError("terraform plan JSON exceeds the size limit")
    _write_private_text(plan_json_path, show_result.stdout)

    return ProvisionPlanResult(
        kit_version=verification.kit_version,
        cli_version=verification.cli_version,
        bundle_version=verification.bundle_version,
        platform_tag=verification.platform_tag,
        manifest_digest=verification.manifest_digest,
        plan_path=str(plan_path),
        plan_digest=_file_digest(plan_path),
        plan_json_path=str(plan_json_path),
        changes_present=changes_present,
        highlighted=summarize_highlighted_changes(show_result.stdout),
    )


def summarize_highlighted_changes(plan_json: str) -> HighlightedChanges:
    """Count the change classes that a one-person approval has to cover.

    Unreadable plan JSON is not reported as "no destroys". It is an error,
    because a silent zero here would understate a plan's blast radius at the
    exact moment a human is deciding whether to approve it.
    """
    try:
        document = json.loads(plan_json)
    except json.JSONDecodeError as exc:
        raise ProvisionPlanError("terraform plan JSON could not be parsed") from exc
    if not isinstance(document, dict):
        raise ProvisionPlanError("terraform plan JSON is not an object")
    raw_changes = document.get("resource_changes", [])
    if not isinstance(raw_changes, list):
        raise ProvisionPlanError("terraform plan JSON resource changes are malformed")
    destroy = 0
    replace = 0
    role_change = 0
    for entry in raw_changes:
        if not isinstance(entry, dict):
            raise ProvisionPlanError("terraform plan JSON resource changes are malformed")
        change = entry.get("change")
        if not isinstance(change, dict):
            raise ProvisionPlanError("terraform plan JSON resource changes are malformed")
        actions = change.get("actions")
        if not isinstance(actions, list) or not all(isinstance(item, str) for item in actions):
            raise ProvisionPlanError("terraform plan JSON resource changes are malformed")
        ordered = tuple(actions)
        if ordered == ("delete",):
            destroy += 1
        elif ordered in _REPLACE_ACTIONS:
            replace += 1
        if ordered != ("no-op",) and _is_role_resource(entry.get("type")):
            role_change += 1
    return HighlightedChanges(destroy=destroy, replace=replace, role_change=role_change)


def _is_role_resource(resource_type: object) -> bool:
    return isinstance(resource_type, str) and any(
        marker in resource_type for marker in _ROLE_RESOURCE_MARKERS
    )


def _resolve_terraform_binary(kit_root: Path, manifest: OfflineKitManifest) -> Path:
    binary = kit_root / manifest.terraform_binary
    if binary.is_symlink() or not binary.is_file():
        raise ProvisionPlanError("offline kit Terraform binary is not a regular file")
    if not os.access(binary, os.X_OK):
        raise ProvisionPlanError(
            "offline kit Terraform binary is not executable; "
            "restore the execute permission lost in transit and plan again"
        )
    return binary


def _resolve_provider_mirror(kit_root: Path, manifest: OfflineKitManifest) -> Path:
    mirror = kit_root / manifest.provider_mirror_prefix
    if mirror.is_symlink() or not mirror.is_dir():
        raise ProvisionPlanError("offline kit provider mirror is not a directory")
    return mirror


def _resolve_infra_dir(infra_dir: Path) -> Path:
    if infra_dir.is_symlink() or not infra_dir.is_dir():
        raise ProvisionPlanError("infrastructure directory MUST be a regular directory")
    if not any(child.suffix == ".tf" for child in infra_dir.iterdir() if child.is_file()):
        raise ProvisionPlanError(
            "infrastructure directory contains no Terraform configuration; "
            "point at the 'infra' directory unpacked from the signed deployment bundle"
        )
    return infra_dir.resolve()


def _prepare_work_dir(work_dir: Path) -> Path:
    if work_dir.is_symlink():
        raise ProvisionPlanError("work directory MUST NOT be a symlink")
    try:
        work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise ProvisionPlanError("work directory could not be created") from exc
    if not work_dir.is_dir():
        raise ProvisionPlanError("work directory MUST be a regular directory")
    work_dir.chmod(0o700)
    return work_dir.resolve()


def _resolve_input_files(paths: Sequence[Path], *, label: str) -> tuple[Path, ...]:
    resolved: list[Path] = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ProvisionPlanError(f"{label} {path} is not a regular file")
        resolved.append(path.resolve())
    return tuple(resolved)


def _render_cli_config(mirror: Path) -> str:
    """Render a CLI configuration that has no path back to the public registry."""
    return (
        "provider_installation {\n"
        "  filesystem_mirror {\n"
        f"    path    = {_hcl_string(str(mirror))}\n"
        '    include = ["*/*"]\n'
        "  }\n"
        "  direct {\n"
        '    exclude = ["*/*"]\n'
        "  }\n"
        "}\n"
    )


def _hcl_string(value: str) -> str:
    if any(ord(character) < 0x20 for character in value):
        raise ProvisionPlanError("path contains a control character and cannot be configured")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("${", "$${").replace("%{", "%%{")
    return f'"{escaped}"'


def _terraform_environment(
    source: Mapping[str, str],
    *,
    cli_config: Path,
    data_dir: Path,
) -> dict[str, str]:
    """Build a minimal environment: credentials pass through, nothing else does."""
    env = {
        name: value
        for name, value in source.items()
        if name in _ENV_NAME_ALLOWLIST or name.startswith(_ENV_PREFIX_ALLOWLIST)
    }
    env["TF_CLI_CONFIG_FILE"] = str(cli_config)
    env["TF_DATA_DIR"] = str(data_dir)
    env["TF_IN_AUTOMATION"] = "1"
    env["TF_INPUT"] = "0"
    env.setdefault("PATH", "")
    return env


def _run_step(
    execute: CommandRunner,
    command: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout: int,
    *,
    step: str,
    success_codes: Iterable[int] = (0,),
) -> CommandResult:
    try:
        result = execute(command, cwd, env, timeout)
    except subprocess.TimeoutExpired as exc:
        raise ProvisionPlanError(f"terraform {step} exceeded {timeout} seconds") from exc
    except OSError as exc:
        raise ProvisionPlanError(f"terraform {step} could not be started: {exc}") from exc
    if result.returncode not in tuple(success_codes):
        raise ProvisionPlanError(f"terraform {step} failed:\n{_error_tail(result)}")
    return result


def _error_tail(result: CommandResult) -> str:
    text = result.stderr.strip() or result.stdout.strip()
    lines = text.splitlines()[-_ERROR_TAIL_LINES:]
    return "\n".join(lines)[-_ERROR_TAIL_CHARS:]


def _write_private_text(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)
    path.chmod(0o600)


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _subprocess_runner(
    command: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout: int,
) -> CommandResult:
    completed = subprocess.run(  # noqa: S603 - argv list from a verified kit, never a shell
        list(command),
        cwd=cwd,
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


__all__ = [
    "CLI_CONFIG_NAME",
    "PLAN_FILE_NAME",
    "PLAN_JSON_NAME",
    "PROVISION_PLAN_SCHEMA",
    "CommandResult",
    "HighlightedChanges",
    "ProvisionPlanError",
    "ProvisionPlanResult",
    "run_provision_plan",
    "summarize_highlighted_changes",
]

"""Command-line facade for safe FDAI deployment preparation."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from fdai_deployment_cli.__about__ import __version__
from fdai_deployment_cli.bundle import (
    BundleVerificationError,
    extract_bundle_archive,
    verify_bundle,
)
from fdai_deployment_cli.bootstrap_reconcile import reconcile_bootstrap
from fdai_deployment_cli.compiler import compile_manifest
from fdai_deployment_cli.doctor import (
    azure_active_target_binding,
    azure_cli_authenticated,
    doctor_json,
    inspect_tools,
)
from fdai_deployment_cli.github_actions import (
    DeploymentSelection,
    deployment_context_digest,
    dispatch_apply,
    dispatch_plan,
    workflow_status,
)
from fdai_deployment_cli.license import LicenseInspectionError, inspect_license
from fdai_deployment_cli.offline_kit import verify_offline_kit
from fdai_deployment_cli.offline_kit import materialize_verified_artifacts
from fdai_deployment_cli.plan_input import snapshot_plan_input
from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest
from fdai_deployment_cli.profile import load_profile, write_profile
from fdai_deployment_cli.private_output import write_private_output
from fdai_deployment_cli.simulation import rehearse
from fdai_deployment_cli.target import compute_target_binding
from fdai_deployment_cli.state import read_journal
from fdai_deployment_cli.status_projection import project_status


def main(argv: list[str] | None = None) -> int:
    """Run one fdaictl command and map safe failures to stable exit codes."""

    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"fdaictl: {exc}", file=sys.stderr)
        return 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fdaictl")
    subcommands = parser.add_subparsers(required=True)

    version = subcommands.add_parser("version")
    version.add_argument("--output", choices=("text", "json"), default="text")
    version.set_defaults(handler=_version)

    doctor = subcommands.add_parser("doctor")
    doctor.add_argument("--output", choices=("text", "json"), default="text")
    doctor.set_defaults(handler=_doctor)

    provision = subcommands.add_parser("provision")
    provision_commands = provision.add_subparsers(required=True)
    initialize = provision_commands.add_parser("init")
    initialize.add_argument("--profile", type=Path, required=True)
    initialize.add_argument("--environment", choices=("dev", "staging", "prod"), required=True)
    initialize.add_argument("--region", required=True)
    initialize.add_argument("--target-binding", required=True)
    initialize.add_argument("--connectivity", choices=("online", "offline"), required=True)
    initialize.add_argument("--host", choices=("existing-host", "managed-vm"), required=True)
    initialize.add_argument("--transport", choices=("manual", "github-actions"), required=True)
    initialize.add_argument(
        "--access-method",
        choices=(
            "internal_ssh",
            "temporary_public_ssh",
            "github_actions",
            "bastion",
            "run_command",
        ),
        required=True,
    )
    initialize.add_argument("--approval-quorum", type=int, default=1)
    initialize.add_argument("--monthly-cost-ceiling", type=int, default=0)
    initialize.add_argument("--force", action="store_true")
    initialize.add_argument("--output", choices=("text", "json"), default="text")
    initialize.set_defaults(handler=_provision_init)

    inspect = provision_commands.add_parser("inspect")
    inspect.add_argument("--profile", type=Path, required=True)
    inspect.add_argument("--output", choices=("text", "json"), default="text")
    inspect.set_defaults(handler=_provision_inspect)

    plan = provision_commands.add_parser("plan")
    plan.add_argument("--offline-kit", type=Path, required=True)
    plan.add_argument("--release-root", type=Path, required=True)
    plan.add_argument("--bundle-public-key", type=Path, required=True)
    plan.add_argument("--work-dir", type=Path, required=True)
    plan.add_argument("--variables-file", type=Path, required=True)
    plan.add_argument("--profile", type=Path, required=True)
    plan.add_argument("--output", choices=("text", "json"), default="text")
    plan.set_defaults(handler=_provision_plan)

    bootstrap_reconcile = provision_commands.add_parser("bootstrap-reconcile")
    bootstrap_reconcile.add_argument("--profile", type=Path, required=True)
    bootstrap_reconcile.add_argument("--source-commit", required=True)
    bootstrap_reconcile.add_argument("--ops-resource-group", required=True)
    bootstrap_reconcile.add_argument("--app-resource-group", required=True)
    bootstrap_reconcile.add_argument("--state-storage-account", required=True)
    bootstrap_reconcile.add_argument("--output-plan", type=Path, required=True)
    bootstrap_reconcile.add_argument("--ttl-seconds", type=int, default=3600)
    bootstrap_reconcile.add_argument("--output", choices=("text", "json"), default="text")
    bootstrap_reconcile.set_defaults(handler=_provision_bootstrap_reconcile)

    bundle = subcommands.add_parser("bundle")
    bundle_commands = bundle.add_subparsers(required=True)
    bundle_verify = bundle_commands.add_parser("verify")
    bundle_verify.add_argument("--bundle", type=Path, required=True)
    bundle_verify.add_argument("--public-key", type=Path, required=True)
    bundle_verify.add_argument("--output", choices=("text", "json"), default="text")
    bundle_verify.set_defaults(handler=_bundle_verify)

    deploy = subcommands.add_parser("deploy")
    deploy_commands = deploy.add_subparsers(required=True)
    deploy_plan = deploy_commands.add_parser("plan")
    _add_deploy_context_arguments(deploy_plan)
    deploy_plan.add_argument("--run-id", required=True)
    deploy_plan.set_defaults(handler=_deploy_plan)
    deploy_apply = deploy_commands.add_parser("apply")
    _add_deploy_context_arguments(deploy_apply)
    deploy_apply.add_argument("--run-id", required=True)
    deploy_apply.add_argument("--plan-id", required=True)
    deploy_apply.add_argument("--plan-digest", required=True)
    deploy_apply.add_argument("--plan-expires-at", required=True)
    deploy_apply.add_argument("--resume-verification", action="store_true")
    deploy_apply.set_defaults(handler=_deploy_apply)
    deploy_status = deploy_commands.add_parser("status")
    _add_deploy_context_arguments(deploy_status)
    deploy_status.add_argument("--request-id", required=True)
    deploy_status.add_argument("--resume-verification", action="store_true")
    deploy_status.set_defaults(handler=_deploy_status)

    license_command = subcommands.add_parser("license")
    license_commands = license_command.add_subparsers(required=True)
    license_inspect = license_commands.add_parser("inspect")
    license_inspect.add_argument("--token", type=Path, required=True)
    license_inspect.add_argument("--public-key", type=Path, required=True)
    license_inspect.add_argument("--image-digest", default=None)
    license_inspect.add_argument("--tenant-binding", default=None)
    license_inspect.add_argument("--output", choices=("text", "json"), default="text")
    license_inspect.set_defaults(handler=_license_inspect)

    onboard = subcommands.add_parser("onboard")
    onboard_commands = onboard.add_subparsers(required=True)
    guided = onboard_commands.add_parser("guided")
    guided.add_argument("--profile", type=Path, required=True)
    guided.add_argument("--source-commit", required=True)
    guided.add_argument("--run-id", required=True)
    guided.add_argument("--journal", type=Path, required=True)
    guided.add_argument("--simulate", action="store_true")
    guided.add_argument("--interrupt-after", default=None)
    guided.add_argument("--repository")
    guided.add_argument("--attempt", type=int, default=1)
    guided.add_argument("--plan-id")
    guided.add_argument("--plan-digest")
    guided.add_argument("--plan-expires-at")
    guided.add_argument("--approve-application", action="store_true")
    guided.add_argument("--resume-verification", action="store_true")
    guided.add_argument("--deploy-console", action=argparse.BooleanOptionalAction, default=True)
    guided.add_argument("--deploy-dev-operations-gateway", action="store_true")
    guided.add_argument(
        "--deploy-operator-api", action=argparse.BooleanOptionalAction, default=True
    )
    guided.add_argument("--deploy-document-ingestion", action="store_true")
    guided.add_argument("--deploy-isolated-executor", action="store_true")
    guided.add_argument("--deploy-monitoring", action="store_true")
    guided.add_argument("--output", choices=("text", "json"), default="text")
    guided.set_defaults(handler=_onboard_guided)
    status = onboard_commands.add_parser("status")
    status.add_argument("--journal", type=Path, required=True)
    status.add_argument("--output", choices=("text", "json"), default="text")
    status.set_defaults(handler=_onboard_status)
    return parser


def _add_deploy_context_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--deploy-console", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--deploy-dev-operations-gateway", action="store_true")
    parser.add_argument(
        "--deploy-operator-api", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--deploy-document-ingestion", action="store_true")
    parser.add_argument("--deploy-isolated-executor", action="store_true")
    parser.add_argument("--deploy-monitoring", action="store_true")
    parser.add_argument("--output", choices=("text", "json"), default="text")


def _version(args: argparse.Namespace) -> int:
    if args.output == "json":
        print(
            json.dumps(
                {"schema_version": "fdai.version.v1", "version": __version__},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    else:
        print(__version__)
    return 0


def _doctor(args: argparse.Namespace) -> int:
    report = doctor_json(
        inspect_tools(),
        azure_authenticated=azure_cli_authenticated(),
    )
    payload = json.loads(report)
    print(report if args.output == "json" else f"ready={str(payload['ready']).lower()}")
    return 0 if payload["ready"] else 3


def _provision_init(args: argparse.Namespace) -> int:
    profile = ProvisionProfile(
        environment=args.environment,
        region=args.region,
        target_binding=args.target_binding,
        connectivity=args.connectivity,
        host=args.host,
        transport=args.transport,
        access_method=args.access_method,
        shadow_only=True,
        approval_quorum=args.approval_quorum,
        monthly_cost_ceiling=args.monthly_cost_ceiling,
    )
    write_profile(args.profile, profile, force=args.force)
    result = {
        "schema_version": "fdai.provision-init.v1",
        "profile_digest": canonical_digest(profile.to_mapping()),
        "mutation_performed": False,
    }
    print(
        json.dumps(result, sort_keys=True, separators=(",", ":"))
        if args.output == "json"
        else f"profile initialized: {result['profile_digest']}"
    )
    return 0


def _provision_inspect(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    required_tools = (
        ("az", "terraform", "gh") if profile.transport == "github-actions" else ("az", "terraform")
    )
    checks = inspect_tools(required_tools)
    active_target = azure_active_target_binding()
    authenticated = active_target is not None and azure_cli_authenticated()
    target_matches = active_target == profile.target_binding
    base_ready = all(check.available for check in checks) and authenticated and target_matches
    state = "review" if base_ready else "incomplete"
    reasons = (
        ["execution_host_identity_unverified"]
        if base_ready
        else [
            *[f"tool_unavailable.{check.name}" for check in checks if not check.available],
            *(["azure_authentication_missing"] if not authenticated else []),
            *(["target_binding_mismatch"] if authenticated and not target_matches else []),
        ]
    )
    result = {
        "schema_version": "fdai.provision-inspect.v1",
        "state": state,
        "profile_digest": canonical_digest(profile.to_mapping()),
        "approval_quorum": profile.approval_quorum,
        "azure_authenticated": authenticated,
        "target_matches": target_matches,
        "mutation_performed": False,
        "missing_tools": [check.name for check in checks if not check.available],
        "reason_codes": reasons,
    }
    print(
        json.dumps(result, sort_keys=True, separators=(",", ":"))
        if args.output == "json"
        else f"state={result['state']}"
    )
    return 2 if base_ready else 3


def _provision_plan(args: argparse.Namespace) -> int:
    work_dir = _absolute_work_dir(args.work_dir)
    profile = load_profile(args.profile)
    _validate_plan_target(
        profile_binding=profile.target_binding,
        active_binding=azure_active_target_binding(),
        use_managed_identity=os.environ.get("ARM_USE_MSI", "").casefold() == "true",
    )
    verification = verify_offline_kit(
        args.offline_kit,
        release_root_pem=_read_public_key(args.release_root),
        cli_version=__version__,
        platform_tag=_runtime_platform_tag(),
    )
    _create_private_work_dir(work_dir)
    artifacts = materialize_verified_artifacts(
        args.offline_kit,
        verification,
        work_dir / "artifacts",
    )
    terraform = artifacts.terraform_binary
    mirror = artifacts.provider_mirror
    bundle_root = extract_bundle_archive(
        artifacts.deployment_bundle,
        work_dir / "bundle",
    )
    bundle_verification = verify_bundle(
        bundle_root,
        public_key_pem=_read_public_key(args.bundle_public_key),
        cli_version=__version__,
    )
    _require_bundle_version(
        kit_version=verification.bundle_version,
        bundle_version=bundle_verification.bundle_version,
    )
    infra_dir = bundle_root / "infra"
    if not infra_dir.is_dir():
        raise ValueError("verified deployment bundle does not contain infra")
    config = work_dir / "offline.tfrc"
    _write_private_text(
        config,
        "provider_installation {\n"
        "  filesystem_mirror {\n"
        f'    path = "{mirror}"\n'
        '    include = ["*/*"]\n'
        "  }\n"
        "  direct {\n"
        '    exclude = ["*/*"]\n'
        "  }\n"
        "}\n",
    )
    variables_file = work_dir / "plan.auto.tfvars.json"
    plan_context = snapshot_plan_input(
        args.variables_file,
        variables_file,
        expected_target_binding=profile.target_binding,
        expected_region=profile.region,
        expected_environment=profile.environment,
    )
    environment = _terraform_environment(
        work_dir=work_dir,
        config=config,
        source=os.environ,
        subscription_id=plan_context.subscription_id,
        tenant_id=plan_context.tenant_id,
        azure_cli_path=Path(azure_cli) if (azure_cli := shutil.which("az")) else None,
    )
    subprocess.run(
        [str(terraform), "init", "-backend=false", "-input=false"],
        cwd=infra_dir,
        env=environment,
        check=True,
        timeout=300,
    )
    try:
        completed = subprocess.run(
            [
                str(terraform),
                "plan",
                "-input=false",
                "-no-color",
                f"-var-file={variables_file}",
            ],
            cwd=infra_dir,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    finally:
        variables_file.unlink(missing_ok=True)
    if completed.returncode != 0:
        raise ValueError(_safe_plan_error(completed.stdout + completed.stderr))
    result = {
        "schema_version": "fdai.provision-plan.v1",
        "offline_manifest_digest": verification.manifest_digest,
        "mutation_performed": False,
    }
    print(
        json.dumps(result, sort_keys=True, separators=(",", ":"))
        if args.output == "json"
        else "plan completed"
    )
    return 0


def _safe_plan_error(output: str) -> str:
    """Map Terraform output to bounded stable errors without echoing provider values."""

    if "No value for required variable" in output:
        return "terraform plan requires deployment input: No value for required variable"
    authentication_markers = (
        "please run 'az login'",
        "could not configure azurecli authorizer",
        "managedidentitycredential authentication failed",
        "error building arm config",
        "unable to build authorizer",
    )
    normalized = output.casefold()
    if any(marker in normalized for marker in authentication_markers):
        return "terraform_provider_authentication_unavailable"
    return "terraform plan failed after offline provider initialization"


def _provision_bootstrap_reconcile(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    result = reconcile_bootstrap(
        profile,
        source_commit=args.source_commit,
        ops_resource_group=args.ops_resource_group,
        app_resource_group=args.app_resource_group,
        state_storage_account=args.state_storage_account,
        ttl_seconds=args.ttl_seconds,
    )
    output_plan = _absolute_work_dir(args.output_plan)
    payload = result.to_mapping()
    write_private_output(
        output_plan,
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
    )
    summary = {
        "schema_version": "fdai.bootstrap-reconcile-result.v1",
        "state": payload["state"],
        "plan_digest": result.plan_digest,
        "observation_digest": result.observation_digest,
        "mutation_performed": False,
    }
    print(
        json.dumps(summary, sort_keys=True, separators=(",", ":"))
        if args.output == "json"
        else f"state={summary['state']} plan_digest={result.plan_digest}"
    )
    return 2 if not result.blockers else 3


def _require_bundle_version(*, kit_version: str, bundle_version: str) -> None:
    if kit_version != bundle_version:
        raise ValueError("offline kit and deployment bundle versions do not match")


def _validate_plan_target(
    *,
    profile_binding: str,
    active_binding: str | None,
    use_managed_identity: bool,
) -> None:
    if use_managed_identity:
        return
    if active_binding is not None and active_binding != profile_binding:
        raise ValueError("active Azure target does not match the provision profile")


def _terraform_environment(
    *,
    work_dir: Path,
    config: Path,
    source: Mapping[str, str],
    subscription_id: str,
    tenant_id: str,
    azure_cli_path: Path | None,
) -> dict[str, str]:
    """Build a minimal Terraform environment and reject ambient control injection."""

    forbidden = {
        key
        for key in source
        if key.startswith("TF_CLI_ARGS")
        or key in {"TF_WORKSPACE", "TF_DATA_DIR", "TF_CLI_CONFIG_FILE"}
    }
    if forbidden:
        raise ValueError("ambient Terraform control variables are not accepted")
    allowed = ("HOME", "TMPDIR", "TEMP", "TMP", "SSL_CERT_FILE", "SSL_CERT_DIR")
    environment = {key: source[key] for key in allowed if key in source}
    azure_config_value = source.get("AZURE_CONFIG_DIR")
    if azure_config_value is not None:
        azure_config = Path(azure_config_value)
        if not azure_config.is_absolute():
            raise ValueError("AZURE_CONFIG_DIR MUST be absolute")
        details = azure_config.lstat()
        if not azure_config.is_dir() or azure_config.is_symlink() or details.st_mode & 0o077:
            raise ValueError("AZURE_CONFIG_DIR MUST be a private regular directory")
        environment["AZURE_CONFIG_DIR"] = str(azure_config)
    use_msi = source.get("ARM_USE_MSI", "").casefold()
    if use_msi not in {"", "true"}:
        raise ValueError("ARM_USE_MSI MUST be true when supplied")
    tenant_value = source.get("ARM_TENANT_ID")
    if tenant_value is not None and tenant_value.casefold() != tenant_id.casefold():
        raise ValueError("ARM_TENANT_ID does not match the verified plan target")
    client_id = source.get("ARM_CLIENT_ID")
    if client_id is not None:
        compute_target_binding(tenant_id=tenant_id, subscription_id=client_id)
    if azure_cli_path is not None:
        resolved_cli = azure_cli_path.resolve(strict=True)
        details = resolved_cli.stat()
        if not resolved_cli.is_file() or details.st_mode & 0o022:
            raise ValueError("Azure CLI executable is not trusted")
        path_entries = tuple(dict.fromkeys((str(resolved_cli.parent), "/usr/bin", "/bin")))
        environment["PATH"] = os.pathsep.join(path_entries)
    elif use_msi != "true":
        raise ValueError("Terraform plan requires Azure CLI or managed identity")
    if use_msi == "true":
        environment["ARM_USE_MSI"] = "true"
        environment["ARM_TENANT_ID"] = tenant_id
        if client_id is not None:
            environment["ARM_CLIENT_ID"] = client_id
    data_dir = work_dir / "terraform-data"
    data_dir.mkdir(mode=0o700)
    data_dir.chmod(0o700)
    environment.update(
        {
            "TF_CLI_CONFIG_FILE": str(config),
            "TF_DATA_DIR": str(data_dir),
            "TF_IN_AUTOMATION": "1",
            "ARM_SUBSCRIPTION_ID": subscription_id,
            "ARM_RESOURCE_PROVIDER_REGISTRATIONS": "none",
        }
    )
    return environment


def _create_private_work_dir(path: Path) -> None:
    """Create a new private work directory and reject every existing destination."""

    _require_nonreplaceable_parent_chain(path)
    os.mkdir(path, 0o700)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        details = os.fstat(descriptor)
        if details.st_uid != os.geteuid():
            raise PermissionError("plan work directory MUST be owned by the current UID")
        os.fchmod(descriptor, 0o700)
    finally:
        os.close(descriptor)


def _require_nonreplaceable_parent_chain(path: Path) -> None:
    trusted_owners = {0, os.geteuid(), Path("/").lstat().st_uid}
    current = path.parent
    while True:
        details = current.lstat()
        if not stat.S_ISDIR(details.st_mode):
            raise PermissionError("plan work directory parent chain MUST contain only directories")
        if details.st_uid not in trusted_owners:
            raise PermissionError("plan work directory parent chain has an unsafe owner")
        mode = stat.S_IMODE(details.st_mode)
        if mode & 0o022 and not (details.st_mode & stat.S_ISVTX):
            raise PermissionError("plan work directory parent chain is replaceable")
        if current == current.parent:
            return
        current = current.parent


def _absolute_work_dir(path: Path) -> Path:
    """Make a path absolute without resolving a potentially hostile symlink."""

    return path if path.is_absolute() else Path.cwd() / path


def _write_private_text(path: Path, content: str) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _runtime_platform_tag() -> str:
    """Return the supported runtime platform identity without caller input."""

    machine = platform.machine().casefold()
    architectures = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }
    architecture = architectures.get(machine)
    if sys.platform != "linux" or architecture is None:
        raise ValueError("this deployment CLI build supports linux x86_64 or aarch64")
    return f"linux-{architecture}"


def _bundle_verify(args: argparse.Namespace) -> int:
    try:
        result = verify_bundle(
            args.bundle,
            public_key_pem=_read_public_key(args.public_key),
            cli_version=__version__,
        )
    except BundleVerificationError:
        raise
    print(result.to_json() if args.output == "json" else f"verified {result.file_count} files")
    return 0


def _license_inspect(args: argparse.Namespace) -> int:
    try:
        result = inspect_license(
            _read_private_license_token(args.token),
            public_key_pem=_read_public_key(args.public_key),
            expected_image_digest=args.image_digest,
            expected_tenant_binding=args.tenant_binding,
        )
    except LicenseInspectionError:
        raise
    print(result.to_json() if args.output == "json" else "active")
    return 0


def _read_private_license_token(path: Path) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(details.st_mode)
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_size > 8192
        ):
            raise ValueError("license token MUST be a mode-0600 regular file within 8192 bytes")
        payload = stream.read(8193)
    try:
        token = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("license token MUST be ASCII") from exc
    if token != token.strip():
        raise ValueError("license token MUST NOT contain surrounding whitespace")
    return token


def _read_public_key(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or details.st_size > 65_536:
            raise ValueError("public key MUST be a regular file within 65536 bytes")
        return stream.read(65_537)


def _onboard_status(args: argparse.Namespace) -> int:
    events = read_journal(args.journal)
    result = project_status(events)
    print(
        json.dumps(result, sort_keys=True, separators=(",", ":"))
        if args.output == "json"
        else f"{result['state']}: {result['current_stage']}"
    )
    return 0


def _deploy_plan(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    _require_github_actions_profile(profile)
    receipt = dispatch_plan(
        repository=args.repository,
        environment=profile.environment,
        commit_sha=args.commit_sha,
        target_binding=profile.target_binding,
        region=profile.region,
        run_id=args.run_id,
        selection=_deployment_selection(args),
        attempt=args.attempt,
    )
    _print_mapping(receipt.to_mapping(), output=args.output, text=receipt.request_id)
    return 0


def _deploy_apply(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    _require_github_actions_profile(profile)
    receipt = dispatch_apply(
        repository=args.repository,
        environment=profile.environment,
        commit_sha=args.commit_sha,
        target_binding=profile.target_binding,
        region=profile.region,
        approval_quorum=profile.approval_quorum,
        run_id=args.run_id,
        plan_id=args.plan_id,
        plan_digest=args.plan_digest,
        plan_expires_at=args.plan_expires_at,
        resume_verification=args.resume_verification,
        selection=_deployment_selection(args),
        attempt=args.attempt,
    )
    _print_mapping(receipt.to_mapping(), output=args.output, text=receipt.request_id)
    return 0


def _deploy_status(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    _require_github_actions_profile(profile)
    context_digest = deployment_context_digest(
        environment=profile.environment,
        commit_sha=args.commit_sha,
        selection=_deployment_selection(args),
    )
    result = workflow_status(
        repository=args.repository,
        request_id_value=args.request_id,
        expected_commit=args.commit_sha,
        expected_context_digest=context_digest,
        target_binding=profile.target_binding,
        expected_region=profile.region,
        resume_verification=args.resume_verification,
    )
    _print_mapping(
        result,
        output=args.output,
        text=f"{result['status']}: {result['conclusion'] or 'pending'}",
    )
    return 0


def _deployment_selection(args: argparse.Namespace) -> DeploymentSelection:
    return DeploymentSelection(
        deploy_console=args.deploy_console,
        deploy_dev_operations_gateway=args.deploy_dev_operations_gateway,
        deploy_operator_api=args.deploy_operator_api,
        deploy_document_ingestion=args.deploy_document_ingestion,
        deploy_isolated_executor=args.deploy_isolated_executor,
        deploy_monitoring=args.deploy_monitoring,
    )


def _require_github_actions_profile(profile: ProvisionProfile) -> None:
    if profile.transport != "github-actions" or profile.access_method != "github_actions":
        raise ValueError("protected deploy commands require a github-actions profile")
    checks = inspect_tools(("az", "gh"))
    if not all(check.available for check in checks):
        raise ValueError("protected deploy command prerequisites are unavailable")
    if not azure_cli_authenticated():
        raise ValueError("azure_authentication_missing")
    active_target = azure_active_target_binding()
    if active_target != profile.target_binding:
        raise ValueError("active Azure target does not match the provision profile")


def _print_mapping(result: Mapping[str, object], *, output: str, text: str) -> None:
    print(json.dumps(result, sort_keys=True, separators=(",", ":")) if output == "json" else text)


def _onboard_guided(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    manifest = compile_manifest(profile, source_commit=args.source_commit)
    if not args.simulate:
        _require_github_actions_profile(profile)
        if not args.repository:
            raise ValueError("live onboarding requires --repository")
        selection = _deployment_selection(args)
        if args.plan_id is None and args.plan_digest is None:
            if args.approve_application or args.resume_verification:
                raise ValueError("application approval and resume require an exact plan")
            receipt = dispatch_plan(
                repository=args.repository,
                environment=profile.environment,
                commit_sha=args.source_commit,
                target_binding=profile.target_binding,
                region=profile.region,
                run_id=args.run_id,
                selection=selection,
                attempt=args.attempt,
            )
            result = {
                "schema_version": "fdai.onboard-guided.v1",
                "run_id": args.run_id,
                "manifest_digest": manifest.digest,
                "state": "waiting",
                "stage": "application-plan",
                "request_id": receipt.request_id,
                "context_digest": receipt.context_digest,
                "next_action": "review-protected-plan",
                "mutation_performed": True,
            }
            _print_mapping(
                result,
                output=args.output,
                text=f"waiting: review protected plan {receipt.request_id}",
            )
            return 0
        if args.plan_id is None or args.plan_digest is None:
            raise ValueError("plan id and digest MUST be supplied together")
        if not args.approve_application and not args.resume_verification:
            raise ValueError("exact apply requires --approve-application")
        if args.plan_expires_at is None:
            raise ValueError("--plan-expires-at is required for apply")
        receipt = dispatch_apply(
            repository=args.repository,
            environment=profile.environment,
            commit_sha=args.source_commit,
            target_binding=profile.target_binding,
            region=profile.region,
            approval_quorum=profile.approval_quorum,
            run_id=args.run_id,
            plan_id=args.plan_id,
            plan_digest=args.plan_digest,
            plan_expires_at=args.plan_expires_at,
            resume_verification=args.resume_verification,
            selection=selection,
            attempt=args.attempt,
        )
        result = {
            "schema_version": "fdai.onboard-guided.v1",
            "run_id": args.run_id,
            "manifest_digest": manifest.digest,
            "state": "verifying" if args.resume_verification else "applying",
            "stage": "application-apply",
            "request_id": receipt.request_id,
            "context_digest": receipt.context_digest,
            "next_action": "watch-protected-run",
            "mutation_performed": True,
        }
        _print_mapping(
            result,
            output=args.output,
            text=f"{result['state']}: {receipt.request_id}",
        )
        return 0
    events = rehearse(
        manifest,
        run_id=args.run_id,
        journal=args.journal,
        interrupt_after=args.interrupt_after,
    )
    latest = events[-1]
    result = {
        "schema_version": "fdai.onboard-guided.v1",
        "run_id": latest.run_id,
        "manifest_digest": manifest.digest,
        "state": latest.state.value,
        "stage": latest.stage,
        "sequence": latest.sequence,
        "mutation_performed": False,
    }
    print(
        json.dumps(result, sort_keys=True, separators=(",", ":"))
        if args.output == "json"
        else f"{latest.state.value}: {latest.stage}"
    )
    return 0


__all__ = ["main"]

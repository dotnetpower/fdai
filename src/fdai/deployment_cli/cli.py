"""Command parser for deployment administration."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TextIO

from fdai.core.trajectory import TrajectoryValidationError
from fdai.deployment_cli.bundle import (
    BundleVerificationError,
    ReleaseChannel,
    verify_deployment_bundle,
)
from fdai.deployment_cli.doctor import run_doctor
from fdai.deployment_cli.extension_kit import (
    ExtensionKitValidationError,
    validate_extension_kit,
)
from fdai.deployment_cli.guided_onboarding import (
    GuidedOnboardingError,
    GuidedOnboardingRequest,
    run_guided_onboarding,
)
from fdai.deployment_cli.onboarding import OnboardingError, initialize_environment
from fdai.deployment_cli.plan_submission import (
    PlanSubmissionError,
    get_github_plan_status,
    submit_github_apply,
    submit_github_plan,
)
from fdai.deployment_cli.portable_backup import (
    BACKUP_RESULT_SCHEMA,
    PortableBackupError,
    create_portable_backup,
    restore_portable_backup,
)
from fdai.deployment_cli.preflight import (
    PreflightInputError,
    run_azure_live_preflight,
    run_static_preflight,
    run_terraform_plan_preflight,
)
from fdai.deployment_cli.provision_inspect import (
    Connectivity,
    ExecutionHost,
    ExecutionTransport,
    inspect_provisioning,
)
from fdai.deployment_cli.release_channels import (
    RELEASE_RESULT_SCHEMA,
    ReleaseStateError,
    rollback_release,
    upgrade_release,
)
from fdai.deployment_cli.security_audit import run_security_audit
from fdai.deployment_cli.trajectory import validate_trajectory_dataset

VERSION_SCHEMA = "fdai.deployment-cli.version.v1"


def _package_version() -> str:
    try:
        return version("fdai")
    except PackageNotFoundError:
        return "0.0.0"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fdaictl",
        description="Diagnose and submit FDAI deployments without moving execution locally.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    version_parser = subcommands.add_parser("version", help="show CLI compatibility versions")
    version_parser.add_argument("--output", choices=("text", "json"), default="text")
    doctor_parser = subcommands.add_parser("doctor", help="check the deployment toolchain")
    doctor_parser.add_argument("--output", choices=("text", "json"), default="text")
    doctor_parser.add_argument("--config", type=Path, default=None)
    provision_parser = subcommands.add_parser(
        "provision", help="inspect and orchestrate guarded provisioning"
    )
    provision_commands = provision_parser.add_subparsers(dest="provision_command", required=True)
    provision_inspect = provision_commands.add_parser(
        "inspect", help="inspect execution profiles without changing resources"
    )
    provision_inspect.add_argument(
        "--connectivity",
        choices=tuple(item.value for item in Connectivity),
        default=Connectivity.AUTO.value,
    )
    provision_inspect.add_argument(
        "--host",
        choices=tuple(item.value for item in ExecutionHost),
        default=ExecutionHost.AUTO.value,
    )
    provision_inspect.add_argument(
        "--transport",
        choices=tuple(item.value for item in ExecutionTransport),
        default=ExecutionTransport.AUTO.value,
    )
    provision_inspect.add_argument("--offline-kit", type=Path, default=None)
    provision_inspect.add_argument("--internal-ssh", action="store_true")
    provision_inspect.add_argument("--allow-temporary-public-ssh", action="store_true")
    provision_inspect.add_argument("--bastion", action="store_true")
    provision_inspect.add_argument("--output", choices=("text", "json"), default="text")
    onboard_parser = subcommands.add_parser("onboard", help="prepare local deployment config")
    onboard_commands = onboard_parser.add_subparsers(dest="onboard_command", required=True)
    onboard_init = onboard_commands.add_parser("init", help="create an environment config")
    onboard_init.add_argument("--environment", choices=("dev", "staging", "prod"), required=True)
    onboard_init.add_argument("--region", required=True)
    onboard_init.add_argument("--config", type=Path, default=None)
    onboard_init.add_argument("--force", action="store_true")
    onboard_init.add_argument("--output", choices=("text", "json"), default="text")
    onboard_guided = onboard_commands.add_parser(
        "guided", help="run guarded setup through remote plan status"
    )
    onboard_guided.add_argument("--environment", choices=("dev", "staging", "prod"), required=True)
    onboard_guided.add_argument("--region", required=True)
    onboard_guided.add_argument("--config", type=Path, required=True)
    onboard_guided.add_argument("--preflight-input", type=Path, required=True)
    onboard_guided.add_argument("--terraform-plan", type=Path, default=None)
    onboard_guided.add_argument("--repository", required=True)
    onboard_guided.add_argument("--workflow-id", default="deploy-dev.yml")
    onboard_guided.add_argument("--ref", default="main")
    onboard_guided.add_argument("--bundle-digest", required=True)
    onboard_guided.add_argument("--commit-sha", required=True)
    onboard_guided.add_argument("--force-config", action="store_true")
    onboard_guided.add_argument("--output", choices=("text", "json"), default="text")
    deploy_parser = subcommands.add_parser("deploy", help="analyze or submit deployments")
    deploy_commands = deploy_parser.add_subparsers(dest="deploy_command", required=True)
    deploy_preflight = deploy_commands.add_parser(
        "preflight", help="run deterministic read-only deployment checks"
    )
    deploy_preflight.add_argument("--input", type=Path, required=True)
    deploy_preflight.add_argument("--terraform-plan", type=Path, default=None)
    deploy_preflight.add_argument("--environment-config", type=Path, default=None)
    deploy_preflight.add_argument("--output", choices=("text", "json"), default="text")
    deploy_plan = deploy_commands.add_parser(
        "plan", help="submit a plan-only job to the approved deployment runner"
    )
    deploy_plan.add_argument("--config", type=Path, required=True)
    deploy_plan.add_argument("--repository", required=True)
    deploy_plan.add_argument("--workflow-id", default="deploy-dev.yml")
    deploy_plan.add_argument("--ref", default="main")
    deploy_plan.add_argument("--bundle-digest", required=True)
    deploy_plan.add_argument("--commit-sha", required=True)
    deploy_plan.add_argument("--output", choices=("text", "json"), default="text")
    deploy_status = deploy_commands.add_parser(
        "status", help="read sanitized metadata for a protected deployment plan"
    )
    deploy_status.add_argument("--repository", required=True)
    deploy_status.add_argument("--plan-id", required=True)
    deploy_status.add_argument("--output", choices=("text", "json"), default="text")
    deploy_apply = deploy_commands.add_parser(
        "apply", help="submit an exact protected plan to the approved runner"
    )
    deploy_apply.add_argument("--config", type=Path, required=True)
    deploy_apply.add_argument("--repository", required=True)
    deploy_apply.add_argument("--plan-id", required=True)
    deploy_apply.add_argument("--bundle-digest", required=True)
    deploy_apply.add_argument("--commit-sha", required=True)
    deploy_apply.add_argument("--output", choices=("text", "json"), default="text")
    security_parser = subcommands.add_parser("security", help="inspect runtime security posture")
    security_commands = security_parser.add_subparsers(dest="security_command", required=True)
    security_audit = security_commands.add_parser("audit", help="run fail-closed security checks")
    security_audit.add_argument("--config", type=Path, default=None)
    security_audit.add_argument("--fix-permissions", action="store_true")
    security_audit.add_argument("--output", choices=("text", "json"), default="text")
    bundle_parser = subcommands.add_parser("bundle", help="verify deployment artifacts")
    bundle_commands = bundle_parser.add_subparsers(dest="bundle_command", required=True)
    bundle_verify = bundle_commands.add_parser("verify", help="verify a signed bundle")
    bundle_verify.add_argument("--bundle", type=Path, required=True)
    bundle_verify.add_argument("--public-key", type=Path, required=True)
    bundle_verify.add_argument("--output", choices=("text", "json"), default="text")
    backup_parser = subcommands.add_parser(
        "backup", help="create or restore portable deployment metadata"
    )
    backup_commands = backup_parser.add_subparsers(dest="backup_command", required=True)
    backup_create = backup_commands.add_parser(
        "create", help="create a verified secret-free portable backup"
    )
    backup_create.add_argument("--config", type=Path, required=True)
    backup_create.add_argument("--references", type=Path, required=True)
    backup_create.add_argument("--audit-metadata", type=Path, required=True)
    backup_create.add_argument("--user-context", type=Path, required=True)
    backup_create.add_argument("--archive", type=Path, required=True)
    backup_create.add_argument("--force", action="store_true")
    backup_create.add_argument("--output", choices=("text", "json"), default="text")
    backup_restore = backup_commands.add_parser(
        "restore", help="verify and restore a portable backup into a new directory"
    )
    backup_restore.add_argument("--archive", type=Path, required=True)
    backup_restore.add_argument("--destination", type=Path, required=True)
    backup_restore.add_argument("--output", choices=("text", "json"), default="text")
    release_parser = subcommands.add_parser(
        "release", help="activate or roll back signed deployment bundle channels"
    )
    release_commands = release_parser.add_subparsers(dest="release_command", required=True)
    release_upgrade = release_commands.add_parser(
        "upgrade", help="activate a newer signed bundle revision"
    )
    release_upgrade.add_argument("--state", type=Path, required=True)
    release_upgrade.add_argument("--config", type=Path, required=True)
    release_upgrade.add_argument("--bundle", type=Path, required=True)
    release_upgrade.add_argument("--public-key", type=Path, required=True)
    release_upgrade.add_argument(
        "--channel",
        choices=tuple(channel.value for channel in ReleaseChannel),
        required=True,
    )
    release_upgrade.add_argument("--output", choices=("text", "json"), default="text")
    release_rollback = release_commands.add_parser(
        "rollback", help="restore the newest prior signed bundle revision"
    )
    release_rollback.add_argument("--state", type=Path, required=True)
    release_rollback.add_argument("--config", type=Path, required=True)
    release_rollback.add_argument("--bundle", type=Path, required=True)
    release_rollback.add_argument("--public-key", type=Path, required=True)
    release_rollback.add_argument("--output", choices=("text", "json"), default="text")
    extension_parser = subcommands.add_parser("extension", help="validate extension packages")
    extension_commands = extension_parser.add_subparsers(dest="extension_command", required=True)
    extension_validate = extension_commands.add_parser(
        "validate", help="run offline extension compatibility and security checks"
    )
    extension_validate.add_argument("--manifest", type=Path, required=True)
    extension_validate.add_argument("--archive", type=Path, required=True)
    extension_validate.add_argument("--host-version", required=True)
    extension_validate.add_argument("--output", choices=("text", "json"), default="text")
    trajectory_parser = subcommands.add_parser(
        "trajectory", help="inspect governed trajectory datasets offline"
    )
    trajectory_commands = trajectory_parser.add_subparsers(dest="trajectory_command", required=True)
    trajectory_validate = trajectory_commands.add_parser(
        "validate", help="validate checksums, schema, ordering, and source mapping"
    )
    trajectory_validate.add_argument("--dataset", type=Path, required=True)
    trajectory_validate.add_argument("--manifest", type=Path, required=True)
    trajectory_validate.add_argument("--purpose", required=True)
    trajectory_validate.add_argument("--access-scope", required=True)
    trajectory_validate.add_argument("--output", choices=("text", "json"), default="text")
    return parser


def _version_payload() -> dict[str, str]:
    return {
        "bundle_version": "not-installed",
        "cli_version": _package_version(),
        "schema": VERSION_SCHEMA,
    }


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    """Run ``fdaictl`` and return a documented process exit code."""
    args = _build_parser().parse_args(argv)
    output = stdout or sys.stdout
    if args.command == "version":
        payload = _version_payload()
        if args.output == "json":
            print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=output)
        else:
            text = f"FDAI CLI {payload['cli_version']} (bundle: {payload['bundle_version']})"
            print(text, file=output)
        return 0
    if args.command == "doctor":
        report = run_doctor(config_path=args.config)
        if args.output == "json":
            print(report.to_json(), file=output)
        else:
            for check in report.checks:
                print(f"{check.status.upper():4} {check.check_id}: {check.summary}", file=output)
            print("READY" if report.ready else "NOT READY", file=output)
        return 0 if report.ready else 4
    if args.command == "provision" and args.provision_command == "inspect":
        inspect_result = inspect_provisioning(
            connectivity=Connectivity(args.connectivity),
            execution_host=ExecutionHost(args.host),
            transport=ExecutionTransport(args.transport),
            offline_kit=args.offline_kit,
            internal_ssh=args.internal_ssh,
            allow_temporary_public_ssh=args.allow_temporary_public_ssh,
            bastion=args.bastion,
        )
        if args.output == "json":
            print(inspect_result.to_json(), file=output)
        else:
            for inspect_check in inspect_result.checks:
                print(
                    f"{inspect_check.status.upper():14} "
                    f"{inspect_check.check_id}: {inspect_check.summary}",
                    file=output,
                )
            print(
                f"{inspect_result.status.upper()}: "
                f"{inspect_result.connectivity.value} / "
                f"{inspect_result.execution_host.value} / "
                f"{inspect_result.transport.value}",
                file=output,
            )
            if inspect_result.access_method is not None:
                print(f"Access: {inspect_result.access_method}", file=output)
            print("No resources were changed.", file=output)
        return inspect_result.exit_code
    if args.command == "onboard" and args.onboard_command == "guided":
        try:
            guided_result = asyncio.run(
                run_guided_onboarding(
                    GuidedOnboardingRequest(
                        environment=args.environment,
                        region=args.region,
                        config_path=args.config,
                        preflight_input_path=args.preflight_input,
                        terraform_plan_path=args.terraform_plan,
                        repository=args.repository,
                        workflow_id=args.workflow_id,
                        ref=args.ref,
                        bundle_digest=args.bundle_digest,
                        commit_sha=args.commit_sha,
                        force_config=args.force_config,
                    )
                )
            )
        except GuidedOnboardingError as exc:
            if args.output == "json":
                print(exc.to_json(), file=output)
            else:
                print(f"ONBOARDING BLOCKED ({exc.step_id}): {exc}", file=output)
            return 4
        if args.output == "json":
            print(guided_result.to_json(), file=output)
        else:
            for step in guided_result.steps:
                print(f"{step.status.upper():7} {step.step_id}: {step.summary}", file=output)
            print(
                f"Plan {guided_result.plan_id} is {guided_result.plan_status}: "
                f"{guided_result.workflow_url}",
                file=output,
            )
        return 0
    if args.command == "onboard" and args.onboard_command == "init":
        try:
            onboarding_result = initialize_environment(
                environment=args.environment,
                region=args.region,
                destination=args.config,
                force=args.force,
            )
        except OnboardingError as exc:
            if args.output == "json":
                print(exc.to_json(), file=output)
            else:
                print(f"ERROR: {exc}", file=output)
            return 4
        if args.output == "json":
            print(onboarding_result.to_json(), file=output)
        else:
            print(
                f"Created {onboarding_result.environment} configuration "
                f"at {onboarding_result.path}",
                file=output,
            )
        return 0
    if args.command == "deploy" and args.deploy_command == "preflight":
        try:
            preflight_result = asyncio.run(
                run_azure_live_preflight(
                    args.input,
                    args.environment_config,
                    args.terraform_plan,
                )
                if args.environment_config is not None
                else (
                    run_static_preflight(args.input)
                    if args.terraform_plan is None
                    else run_terraform_plan_preflight(args.input, args.terraform_plan)
                )
            )
        except PreflightInputError as exc:
            if args.output == "json":
                print(exc.to_json(), file=output)
            else:
                print(f"INCOMPLETE: {exc}", file=output)
            return 4
        if args.output == "json":
            print(preflight_result.to_json(), file=output)
        else:
            for finding in preflight_result.report.findings:
                print(
                    f"{finding.severity.value.upper():8} {finding.category.value}: {finding.title}",
                    file=output,
                )
            print(preflight_result.report.verdict.value.upper(), file=output)
        return preflight_result.exit_code
    if args.command == "deploy" and args.deploy_command == "plan":
        doctor_report = run_doctor(config_path=args.config)
        try:
            plan_result = asyncio.run(
                submit_github_plan(
                    config_path=args.config,
                    repository=args.repository,
                    workflow_id=args.workflow_id,
                    ref=args.ref,
                    bundle_digest=args.bundle_digest,
                    commit_sha=args.commit_sha,
                    doctor_report=doctor_report,
                )
            )
        except PlanSubmissionError as exc:
            if args.output == "json":
                print(exc.to_json(), file=output)
            else:
                print(f"NOT SUBMITTED: {exc}", file=output)
            return 4
        if args.output == "json":
            print(plan_result.to_json(), file=output)
        else:
            print(
                f"Submitted plan {plan_result.plan_id} in workflow "
                f"{plan_result.submission_id}: "
                f"{plan_result.workflow_url}",
                file=output,
            )
        return 0
    if args.command == "deploy" and args.deploy_command == "status":
        try:
            status_result = asyncio.run(
                get_github_plan_status(
                    repository=args.repository,
                    plan_id=args.plan_id,
                )
            )
        except PlanSubmissionError as exc:
            if args.output == "json":
                print(exc.to_json(), file=output)
            else:
                print(f"UNAVAILABLE: {exc}", file=output)
            return 4
        if args.output == "json":
            print(status_result.to_json(), file=output)
        else:
            print(
                f"{status_result.plan_id} {status_result.status.upper()} "
                f"expires {status_result.expires_at}",
                file=output,
            )
        return 0
    if args.command == "deploy" and args.deploy_command == "apply":
        doctor_report = run_doctor(config_path=args.config)
        try:
            apply_result = asyncio.run(
                submit_github_apply(
                    config_path=args.config,
                    repository=args.repository,
                    plan_id=args.plan_id,
                    bundle_digest=args.bundle_digest,
                    commit_sha=args.commit_sha,
                    doctor_report=doctor_report,
                )
            )
        except PlanSubmissionError as exc:
            if args.output == "json":
                print(exc.to_json(), file=output)
            else:
                print(f"NOT SUBMITTED: {exc}", file=output)
            return 4
        if args.output == "json":
            print(apply_result.to_json(), file=output)
        else:
            print(
                f"Submitted exact apply for {apply_result.plan_id} in workflow "
                f"{apply_result.submission_id}: {apply_result.workflow_url}",
                file=output,
            )
        return 0
    if args.command == "security" and args.security_command == "audit":
        security_report = run_security_audit(
            config_path=args.config,
            fix_permissions=args.fix_permissions,
        )
        if args.output == "json":
            print(security_report.to_json(), file=output)
        else:
            for security_finding in security_report.findings:
                print(
                    f"{security_finding.severity.upper():8} "
                    f"{security_finding.check_id}: {security_finding.summary}",
                    file=output,
                )
            print("SECURE" if security_report.secure else "ACTION REQUIRED", file=output)
        return 0 if security_report.secure else 3
    if args.command == "trajectory" and args.trajectory_command == "validate":
        try:
            trajectory_report = validate_trajectory_dataset(
                dataset_path=args.dataset,
                manifest_path=args.manifest,
                purpose=args.purpose,
                access_scope=args.access_scope,
            )
        except (OSError, TrajectoryValidationError, ValueError) as exc:
            if args.output == "json":
                print(json.dumps({"error": str(exc), "valid": False}), file=output)
            else:
                print(f"INVALID: {exc}", file=output)
            return 4
        if args.output == "json":
            print(trajectory_report.to_json(), file=output)
        else:
            print(
                f"VALID {trajectory_report.dataset_id}: {trajectory_report.record_count} records",
                file=output,
            )
        return 0
    if args.command == "bundle" and args.bundle_command == "verify":
        try:
            public_key = args.public_key.read_bytes()
            bundle_result = verify_deployment_bundle(
                args.bundle,
                public_key_pem=public_key,
                cli_version=_package_version(),
            )
        except (OSError, BundleVerificationError, ValueError) as exc:
            if args.output == "json":
                print(
                    json.dumps(
                        {
                            "error": str(exc),
                            "schema_version": "fdai.deployment-cli.bundle-verification.v1",
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    file=output,
                )
            else:
                print(f"INVALID: {exc}", file=output)
            return 4
        if args.output == "json":
            print(bundle_result.to_json(), file=output)
        else:
            print(
                f"Verified bundle {bundle_result.bundle_version} "
                f"({bundle_result.file_count} files)",
                file=output,
            )
        return 0
    if args.command == "backup":
        try:
            if args.backup_command == "create":
                backup_result = create_portable_backup(
                    config_path=args.config,
                    references_path=args.references,
                    audit_metadata_path=args.audit_metadata,
                    user_context_path=args.user_context,
                    archive_path=args.archive,
                    force=args.force,
                )
            else:
                backup_result = restore_portable_backup(
                    archive_path=args.archive,
                    destination=args.destination,
                )
        except (OSError, PortableBackupError, ValueError) as exc:
            if args.output == "json":
                print(
                    json.dumps(
                        {"error": str(exc), "schema_version": BACKUP_RESULT_SCHEMA},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    file=output,
                )
            else:
                print(f"BACKUP BLOCKED: {exc}", file=output)
            return 4
        if args.output == "json":
            print(backup_result.to_json(), file=output)
        else:
            print(
                f"Portable backup {backup_result.operation} completed "
                f"for {backup_result.file_count} files at {backup_result.path}",
                file=output,
            )
        return 0
    if args.command == "release":
        try:
            public_key = args.public_key.read_bytes()
            if args.release_command == "upgrade":
                release_state = upgrade_release(
                    state_path=args.state,
                    config_path=args.config,
                    bundle_path=args.bundle,
                    public_key_pem=public_key,
                    cli_version=_package_version(),
                    channel=ReleaseChannel(args.channel),
                )
            else:
                release_state = rollback_release(
                    state_path=args.state,
                    config_path=args.config,
                    bundle_path=args.bundle,
                    public_key_pem=public_key,
                    cli_version=_package_version(),
                )
        except (OSError, ReleaseStateError, ValueError) as exc:
            if args.output == "json":
                print(
                    json.dumps(
                        {"error": str(exc), "schema_version": RELEASE_RESULT_SCHEMA},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    file=output,
                )
            else:
                print(f"RELEASE BLOCKED: {exc}", file=output)
            return 4
        if args.output == "json":
            print(release_state.to_json(operation=args.release_command), file=output)
        else:
            print(
                f"Release {args.release_command} selected "
                f"{release_state.active.bundle_version} "
                f"({release_state.active.release_channel.value})",
                file=output,
            )
        return 0
    if args.command == "extension" and args.extension_command == "validate":
        try:
            extension_result = validate_extension_kit(
                args.manifest,
                args.archive,
                host_version=args.host_version,
            )
        except ExtensionKitValidationError as exc:
            if args.output == "json":
                print(
                    json.dumps(
                        {
                            "error": str(exc),
                            "schema_version": "fdai.extension-kit-validation.v1",
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    file=output,
                )
            else:
                print(f"INVALID: {exc}", file=output)
            return 4
        if args.output == "json":
            print(extension_result.to_json(), file=output)
        else:
            print(
                f"Valid extension {extension_result.extension_id} "
                f"v{extension_result.extension_version} for host "
                f"{extension_result.host_version}",
                file=output,
            )
        return 0
    return 64


__all__ = ["VERSION_SCHEMA", "main"]

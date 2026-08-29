"""Command-line facade for safe FDAI deployment preparation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from fdai_deployment_cli.__about__ import __version__
from fdai_deployment_cli.bundle import BundleVerificationError, verify_bundle
from fdai_deployment_cli.compiler import compile_manifest
from fdai_deployment_cli.doctor import azure_cli_authenticated, doctor_json, inspect_tools
from fdai_deployment_cli.license import LicenseInspectionError, inspect_license
from fdai_deployment_cli.offline_kit import verify_offline_kit
from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest
from fdai_deployment_cli.profile import load_profile, write_profile
from fdai_deployment_cli.simulation import rehearse
from fdai_deployment_cli.state import read_journal


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
    plan.add_argument("--infra-dir", type=Path, required=True)
    plan.add_argument("--work-dir", type=Path, required=True)
    plan.add_argument("--cli-version", required=True)
    plan.add_argument("--platform-tag", required=True)
    plan.add_argument("--output", choices=("text", "json"), default="text")
    plan.set_defaults(handler=_provision_plan)

    bundle = subcommands.add_parser("bundle")
    bundle_commands = bundle.add_subparsers(required=True)
    bundle_verify = bundle_commands.add_parser("verify")
    bundle_verify.add_argument("--bundle", type=Path, required=True)
    bundle_verify.add_argument("--public-key", type=Path, required=True)
    bundle_verify.add_argument("--output", choices=("text", "json"), default="text")
    bundle_verify.set_defaults(handler=_bundle_verify)

    license_command = subcommands.add_parser("license")
    license_commands = license_command.add_subparsers(required=True)
    license_inspect = license_commands.add_parser("inspect")
    license_inspect.add_argument("--token", type=Path, required=True)
    license_inspect.add_argument("--public-key", type=Path, required=True)
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
    guided.add_argument("--output", choices=("text", "json"), default="text")
    guided.set_defaults(handler=_onboard_guided)
    status = onboard_commands.add_parser("status")
    status.add_argument("--journal", type=Path, required=True)
    status.add_argument("--output", choices=("text", "json"), default="text")
    status.set_defaults(handler=_onboard_status)
    return parser


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
    report = doctor_json(inspect_tools())
    payload = json.loads(report)
    print(report if args.output == "json" else f"ready={str(payload['ready']).lower()}")
    return 0 if payload["ready"] else 3


def _provision_init(args: argparse.Namespace) -> int:
    profile = ProvisionProfile(
        environment=args.environment,
        region=args.region,
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
    checks = inspect_tools()
    authenticated = azure_cli_authenticated()
    ready = all(check.available for check in checks) and authenticated
    result = {
        "schema_version": "fdai.provision-inspect.v1",
        "state": "ready" if ready else "incomplete",
        "profile_digest": canonical_digest(profile.to_mapping()),
        "approval_quorum": profile.approval_quorum,
        "azure_authenticated": authenticated,
        "mutation_performed": False,
        "missing_tools": [check.name for check in checks if not check.available],
    }
    print(
        json.dumps(result, sort_keys=True, separators=(",", ":"))
        if args.output == "json"
        else f"state={result['state']}"
    )
    return 0 if ready else 3


def _provision_plan(args: argparse.Namespace) -> int:
    verification = verify_offline_kit(
        args.offline_kit,
        release_root_pem=args.release_root.read_bytes(),
        cli_version=args.cli_version,
        platform_tag=args.platform_tag,
    )
    args.work_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.work_dir.chmod(0o700)
    terraform_relative = json.loads(
        (args.offline_kit / "offline-kit.json").read_text(encoding="utf-8")
    )["terraform_binary"]
    mirror_relative = json.loads(
        (args.offline_kit / "offline-kit.json").read_text(encoding="utf-8")
    )["provider_mirror_prefix"]
    terraform = args.offline_kit / terraform_relative
    mirror = args.offline_kit / mirror_relative
    config = args.work_dir / "offline.tfrc"
    config.write_text(
        "provider_installation {\n"
        "  filesystem_mirror {\n"
        f'    path = "{mirror}"\n'
        '    include = ["*/*"]\n'
        "  }\n"
        "  direct {\n"
        '    exclude = ["*/*"]\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    config.chmod(0o600)
    environment = dict(os.environ)
    environment["TF_CLI_CONFIG_FILE"] = str(config)
    environment["TF_IN_AUTOMATION"] = "1"
    subprocess.run(
        [str(terraform), "init", "-backend=false", "-input=false"],
        cwd=args.infra_dir,
        env=environment,
        check=True,
        timeout=300,
    )
    completed = subprocess.run(
        [str(terraform), "plan", "-input=false", "-no-color"],
        cwd=args.infra_dir,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
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
    return "terraform plan failed after offline provider initialization"


def _bundle_verify(args: argparse.Namespace) -> int:
    try:
        result = verify_bundle(
            args.bundle,
            public_key_pem=args.public_key.read_bytes(),
            cli_version=__version__,
        )
    except BundleVerificationError:
        raise
    print(result.to_json() if args.output == "json" else f"verified {result.file_count} files")
    return 0


def _license_inspect(args: argparse.Namespace) -> int:
    try:
        result = inspect_license(
            args.token.read_text(encoding="ascii").strip(),
            public_key_pem=args.public_key.read_bytes(),
        )
    except LicenseInspectionError:
        raise
    print(result.to_json() if args.output == "json" else "active")
    return 0


def _onboard_status(args: argparse.Namespace) -> int:
    events = read_journal(args.journal)
    if not events:
        raise ValueError("provision journal is empty")
    latest = events[-1]
    result = {
        "schema_version": "fdai.onboard-status.v1",
        "run_id": latest.run_id,
        "context_digest": latest.context_digest,
        "sequence": latest.sequence,
        "stage": latest.stage,
        "state": latest.state.value,
        "event_digest": latest.digest,
    }
    print(
        json.dumps(result, sort_keys=True, separators=(",", ":"))
        if args.output == "json"
        else f"{latest.state.value}: {latest.stage}"
    )
    return 0


def _onboard_guided(args: argparse.Namespace) -> int:
    if not args.simulate:
        raise ValueError("live onboarding requires the protected Azure runner")
    profile = load_profile(args.profile)
    manifest = compile_manifest(profile, source_commit=args.source_commit)
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

"""Command-line facade for safe FDAI deployment preparation."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

from fdai_deployment_cli.__about__ import __version__
from fdai_deployment_cli.aks_preflight import inspect_aks_target
from fdai_deployment_cli.bootstrap_reconcile import reconcile_bootstrap
from fdai_deployment_cli.bundle import (
    verify_bundle,
)
from fdai_deployment_cli.cli_parser import build_parser
from fdai_deployment_cli.cli_plan import (
    _absolute_work_dir,
    _create_private_work_dir,
    _print_mapping,
    _provision_plan,
    _read_public_key,
    _require_bundle_version,  # noqa: F401 - compatibility seam
    _runtime_platform_tag,
    _safe_plan_error,  # noqa: F401 - compatibility seam
    _terraform_environment,  # noqa: F401 - compatibility seam
    _validate_plan_target,  # noqa: F401 - compatibility seam
    _write_private_text,  # noqa: F401 - compatibility seam
    read_plan_input,  # noqa: F401 - compatibility seam
)
from fdai_deployment_cli.compiler import compile_manifest
from fdai_deployment_cli.console_artifact import build_console_update_artifact
from fdai_deployment_cli.console_config import configure_console
from fdai_deployment_cli.console_update import (
    apply_console_update_plan,
    load_console_update_plan,
    prepare_console_update_plan,
)
from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest
from fdai_deployment_cli.deployment_progress import DeploymentProgress
from fdai_deployment_cli.doctor import (
    azure_active_target_binding,
    azure_cli_authenticated,
    doctor_json,
    inspect_tools,
)
from fdai_deployment_cli.license import inspect_license
from fdai_deployment_cli.offline_prepare import prepare_offline_release
from fdai_deployment_cli.private_output import write_private_output
from fdai_deployment_cli.profile import load_profile, write_profile
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.simulation import rehearse
from fdai_deployment_cli.source_azure import plan_source_installation
from fdai_deployment_cli.source_deploy import prepare_source_deployment
from fdai_deployment_cli.source_service_update import deploy_source_service_update
from fdai_deployment_cli.standalone_deploy import deploy_azure_foundation
from fdai_deployment_cli.state import read_journal
from fdai_deployment_cli.status_projection import project_status
from fdai_deployment_cli.support_install import install_support


def main(argv: list[str] | None = None) -> int:
    """Run one fdaictl command and map safe failures to stable exit codes."""

    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except ValueError as exc:
        print(f"fdaictl: {exc}", file=sys.stderr)
        return 3
    except (OSError, subprocess.SubprocessError):
        print(
            "fdaictl: local or child operation failed; inspect retained evidence before recovery",
            file=sys.stderr,
        )
        return 3
    except EOFError:
        print("fdaictl: approval input closed; no new approval was granted", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("fdaictl: interrupted; inspect retained evidence before resuming", file=sys.stderr)
        return 130


def _parser() -> argparse.ArgumentParser:
    return build_parser(
        {
            "version": _version,
            "doctor": _doctor,
            "offline_prepare": _offline_prepare,
            "offline_configure_console": _offline_configure_console,
            "offline_install_support": _offline_install_support,
            "provision_azure": _provision_azure,
            "provision_source_service_update": _provision_source_service_update,
            "provision_console_update_build": _provision_console_update_build,
            "provision_console_update_plan": _provision_console_update_plan,
            "provision_console_update_apply": _provision_console_update_apply,
            "provision_init": _provision_init,
            "provision_inspect": _provision_inspect,
            "provision_plan": _provision_plan,
            "provision_bootstrap_reconcile": _provision_bootstrap_reconcile,
            "bundle_verify": _bundle_verify,
            "license_inspect": _license_inspect,
            "onboard_guided": _onboard_guided,
            "onboard_status": _onboard_status,
        }
    )


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


def _provision_azure(args: argparse.Namespace) -> int:
    """Run the standalone active-Azure-login deployment path."""

    from fdai_deployment_cli.installation_scope import InstallationOptions

    runtime_profile = RuntimeDeploymentProfile.create(
        runtime_platform=args.runtime,
        database_placement=args.database,
        system_node_count=args.system_nodes,
        system_node_sku=args.system_node_sku,
        user_node_min_count=args.user_nodes,
        user_node_max_count=args.max_user_nodes,
        user_node_sku=args.user_node_sku,
    )
    if (args.prepare_only or args.preflight_only) and args.source is None:
        raise ValueError("source-only preparation or preflight requires --source")
    if re.fullmatch(r"[a-z][a-z0-9]{1,11}", args.foundation_workload) is None:
        raise ValueError(
            "--foundation-workload must be a lowercase token of 2 through 12 characters"
        )
    if args.foundation_workload != "fdai" and args.source is None:
        raise ValueError("--foundation-workload is supported only for source deployment")
    if args.foundation_recovery_directory is not None and (
        args.source is None or args.work_dir is None or args.prepare_only or args.preflight_only
    ):
        raise ValueError(
            "Foundation recovery requires --source and the original --work-dir without preparation or preflight"
        )
    if args.approval_file is not None and (
        args.source is None or args.prepare_only or args.preflight_only
    ):
        raise ValueError("--approval-file requires source deployment, not preparation or preflight")
    initial_options_requested = (
        args.setup_cost_ceiling is not None
        or args.console_access is not None
        or args.allow_dedicated_identities
        or args.cleanup_temporary_resources
    )
    if initial_options_requested and (
        args.source is None
        or args.prepare_only
        or args.preflight_only
        or args.approval_file is not None
        or args.foundation_recovery_directory is not None
    ):
        raise ValueError(
            "initial scope options require a source install without an exact approval file"
        )
    selected_dir = args.work_dir
    if selected_dir is None:
        selected_dir = Path.home() / (
            ".local/state/fdai/azure-source"
            if args.source is not None
            else ".local/state/fdai/azure"
        )
    work_dir = selected_dir if selected_dir.is_absolute() else Path.cwd() / selected_dir
    adoption_paths = tuple(
        getattr(args, name)
        for name in (
            "adopt_application_state",
            "adopt_application_recovery",
            "adopt_resolved_models",
        )
    )
    if any(path is not None for path in adoption_paths) and not all(
        path is not None for path in adoption_paths
    ):
        raise ValueError("recovered public deployment requires all three adoption inputs")
    if args.source is not None:
        if args.online_url is not None or any(path is not None for path in adoption_paths):
            raise ValueError(
                "source deployment cannot reuse kit URLs or application-state adoption"
            )
        if not args.prepare_only and not args.preflight_only:
            result = plan_source_installation(
                source_root=args.source,
                work_dir=work_dir,
                runtime_profile=runtime_profile,
                region=args.region,
                monthly_cost_ceiling=args.monthly_cost_ceiling,
                foundation_workload=args.foundation_workload,
                timeout_seconds=args.timeout_seconds,
                approval_file=args.approval_file,
                foundation_recovery_directory=args.foundation_recovery_directory,
                interactive=False,
                installation_options=(
                    InstallationOptions(
                        setup_cost_ceiling=args.setup_cost_ceiling,
                        console_access=args.console_access or "public-https-entra",
                        allow_dedicated_identities=args.allow_dedicated_identities,
                        cleanup_temporary_resources=args.cleanup_temporary_resources,
                    )
                    if args.approval_file is None and args.foundation_recovery_directory is None
                    else None
                ),
                confirm_initial=args.foundation_recovery_directory is None
                and args.output == "text"
                and sys.stdin.isatty(),
            )
            _print_mapping(
                result,
                output=args.output,
                text=(
                    f"source deployment: {result['state']}; "
                    f"reason={result.get('reason_code', 'review_required')}; deployment is not ready"
                ),
            )
            return 2 if result["state"] == "review" else 3
        result = prepare_source_deployment(
            source_root=args.source,
            work_dir=work_dir,
            runtime_profile=runtime_profile,
            region=args.region,
            monthly_cost_ceiling=args.monthly_cost_ceiling,
        )
        if args.preflight_only:
            result = inspect_aks_target(
                profile=runtime_profile,
                region=args.region,
                timeout_seconds=min(args.timeout_seconds, 180),
            )
            _print_mapping(
                result,
                output=args.output,
                text=f"AKS capacity preflight: {result['state']}; no deployment performed",
            )
            return 0 if result["state"] == "feasible" else 3
        _print_mapping(
            result,
            output=args.output,
            text="source snapshot prepared; no Azure access or deployment performed",
        )
        return 0

    def adoption_path(value: Path | None) -> Path | None:
        if value is None or value.is_absolute():
            return value
        return Path.cwd() / value

    mode = args.progress if args.output == "text" else "off"
    with DeploymentProgress(mode=mode) as progress:
        result = deploy_azure_foundation(
            work_dir=work_dir,
            online=args.online,
            offline_kit=args.offline_kit,
            online_url=args.online_url,
            region=args.region,
            runtime_profile=runtime_profile,
            monthly_cost_ceiling=args.monthly_cost_ceiling,
            timeout_seconds=args.timeout_seconds,
            license_signing_key=args.license_signing_key,
            trial_token=args.trial_token,
            adopt_runner_image_receipt=adoption_path(args.adopt_runner_image_receipt),
            adopt_application_state=adoption_path(args.adopt_application_state),
            adopt_application_recovery=adoption_path(args.adopt_application_recovery),
            adopt_resolved_models=adoption_path(args.adopt_resolved_models),
        )
        if result.get("deployment_ready") is not True:
            raise ValueError("standalone deployment did not return verified deployment readiness")
        progress.ready()
    _print_mapping(
        result,
        output=args.output,
        text=(
            "standalone Azure deployment ready; subscription-wide assurance evidence remains open"
        ),
    )
    return 0


def _provision_source_service_update(args: argparse.Namespace) -> int:
    """Build and deploy one source-selected service from an eligible deployment host."""

    source = args.source.absolute()
    application = args.application_work_dir.absolute()
    selected = args.work_dir
    if selected is None:
        commit = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=source,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        selected = Path.home() / ".local/state/fdai/source-service-updates" / commit / args.service
    result = deploy_source_service_update(
        source_root=source,
        application_work_dir=application,
        work_dir=selected,
        service=args.service,
        timeout_seconds=args.timeout_seconds,
        adopt_historical_binding=args.adopt_historical_binding,
        adopt_historical_state=args.adopt_historical_state,
        adopt_historical_variables=args.adopt_historical_variables,
        adopt_historical_live=args.adopt_historical_live,
        adopt_historical_plan=args.adopt_historical_plan,
    )
    print(
        json.dumps(result, sort_keys=True, separators=(",", ":"))
        if args.output == "json"
        else (f"source service update applied: {result['service']} at {result['source_commit']}")
    )
    return 0


def _provision_console_update_plan(args: argparse.Namespace) -> int:
    """Create one private existing-development Console update plan."""

    result = prepare_console_update_plan(
        source_root=_absolute_work_dir(args.source),
        candidate_archive=_absolute_work_dir(args.candidate_archive),
        candidate_manifest=_absolute_work_dir(args.candidate_manifest),
        rollback_archive=_absolute_work_dir(args.rollback_archive),
        rollback_manifest=_absolute_work_dir(args.rollback_manifest),
        target_file=_absolute_work_dir(args.target),
        work_dir=_absolute_work_dir(args.work_dir),
        ttl_seconds=args.ttl_seconds,
    )
    _print_mapping(
        result,
        output=args.output,
        text=(f"Console update plan ready: {result['plan_digest']}; no Azure mutation performed"),
    )
    return 0


def _provision_console_update_build(args: argparse.Namespace) -> int:
    """Build a deterministic Console artifact from one protected source revision."""

    result = build_console_update_artifact(
        source_root=_absolute_work_dir(args.source),
        revision=args.revision,
        output_dir=_absolute_work_dir(args.output_dir),
        timeout_seconds=args.timeout_seconds,
    )
    _print_mapping(
        result,
        output=args.output,
        text=(f"Console artifact built: {result['archive_sha256']}; no Azure mutation performed"),
    )
    return 0


def _provision_console_update_apply(args: argparse.Namespace) -> int:
    """Apply one explicitly invoked Console update plan without redundant input."""

    work_dir = _absolute_work_dir(args.work_dir)
    plan = load_console_update_plan(
        work_dir / "plan.json", allow_expired_claim=(work_dir / "claim.json").is_file()
    )
    if args.output == "text":
        print(
            "Console update exact plan\n"
            f"  source commit: {plan['source_commit']}\n"
            f"  target binding: {plan['target_binding']}\n"
            f"  candidate SHA-256: {plan['candidate_archive_sha256']}\n"
            f"  rollback SHA-256: {plan['rollback_archive_sha256']}\n"
            f"  plan digest: {plan['plan_digest']}\n"
            "Applying the explicitly invoked non-destructive dev plan.",
            file=sys.stderr,
        )
    source_root = _absolute_work_dir(args.source)
    result = apply_console_update_plan(
        source_root=source_root,
        work_dir=work_dir,
        approved_plan_digest=str(plan["plan_digest"]),
        scripts=_console_update_scripts(source_root),
        timeout_seconds=args.timeout_seconds,
    )
    _print_mapping(
        result,
        output=args.output,
        text=f"Console update applied and read back: {result['receipt_digest']}",
    )
    return 0


def _console_update_scripts(source_root: Path) -> Path:
    """Prefer the current reviewed source-checkout controls over artifact-source scripts."""

    checkout_scripts = Path(__file__).resolve().parents[4] / "scripts/deployment/azure"
    if (checkout_scripts / "publish-console.sh").is_file():
        return checkout_scripts
    return source_root / "scripts/deployment/azure"


def _offline_prepare(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    release_root = _read_public_key(args.release_root)
    bundle_key = _read_public_key(args.bundle_public_key)
    work_dir = _absolute_work_dir(args.work_dir)
    _create_private_work_dir(work_dir)
    result = prepare_offline_release(
        args.offline_kit,
        work_dir=work_dir,
        profile=profile,
        source_commit=args.source_commit,
        release_root_pem=release_root,
        bundle_public_key_pem=bundle_key,
        cli_version=__version__,
        platform_tag=_runtime_platform_tag(),
    )
    _print_mapping(
        result,
        output=args.output,
        text="prepared: signed inputs only; subscription provisioning and approvals remain required",
    )
    return 0


def _offline_configure_console(args: argparse.Namespace) -> int:
    result = configure_console(
        _absolute_work_dir(args.directory), _absolute_work_dir(args.settings)
    )
    _print_mapping(
        result,
        output=args.output,
        text="Console configured for Entra; publication and authenticated access remain unverified",
    )
    return 0


def _offline_install_support(args: argparse.Namespace) -> int:
    public_key = _read_public_key(args.release_root)
    work_dir = _absolute_work_dir(args.work_dir)
    _create_private_work_dir(work_dir)
    result = install_support(
        args.offline_kit,
        work_dir=work_dir,
        release_root_pem=public_key,
        cli_version=__version__,
        platform_tag=_runtime_platform_tag(),
    )
    _print_mapping(
        result,
        output=args.output,
        text="deployment support installed offline; runtime services have not been started",
    )
    return 0


def _provision_inspect(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    checks = inspect_tools(("az", "terraform"))
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


def _bundle_verify(args: argparse.Namespace) -> int:
    result = verify_bundle(
        args.bundle,
        public_key_pem=_read_public_key(args.public_key),
        cli_version=__version__,
    )
    print(result.to_json() if args.output == "json" else f"verified {result.file_count} files")
    return 0


def _license_inspect(args: argparse.Namespace) -> int:
    result = inspect_license(
        _read_private_license_token(args.token),
        public_key_pem=_read_public_key(args.public_key),
        expected_image_digest=args.image_digest,
        expected_tenant_binding=args.tenant_binding,
    )
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


def _onboard_status(args: argparse.Namespace) -> int:
    events = read_journal(args.journal)
    result = project_status(events)
    print(
        json.dumps(result, sort_keys=True, separators=(",", ":"))
        if args.output == "json"
        else f"{result['state']}: {result['current_stage']}"
    )
    return 0


def _onboard_guided(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    manifest = compile_manifest(profile, source_commit=args.source_commit)
    if not args.simulate:
        raise ValueError(
            "live onboarding uses 'fdaictl provision azure'; "
            "GitHub Actions deployment is not supported"
        )
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

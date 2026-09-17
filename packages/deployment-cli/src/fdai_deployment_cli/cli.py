"""Command-line facade for safe FDAI deployment preparation."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Mapping
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from fdai_deployment_cli.__about__ import __version__
from fdai_deployment_cli.aks_preflight import inspect_aks_target
from fdai_deployment_cli.bootstrap_reconcile import reconcile_bootstrap
from fdai_deployment_cli.bundle import (
    extract_bundle_archive,
    verify_bundle,
)
from fdai_deployment_cli.cli_parser import build_parser
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
from fdai_deployment_cli.foundation_image import verify_foundation_runner_image
from fdai_deployment_cli.foundation_input import snapshot_foundation_input
from fdai_deployment_cli.foundation_plan import (
    foundation_plan_context,
    save_foundation_plan,
)
from fdai_deployment_cli.license import inspect_license
from fdai_deployment_cli.offline_kit import materialize_verified_artifacts, verify_offline_kit
from fdai_deployment_cli.offline_prepare import prepare_offline_release
from fdai_deployment_cli.plan_input import read_plan_input, snapshot_plan_input
from fdai_deployment_cli.private_output import write_private_output
from fdai_deployment_cli.profile import load_profile, write_profile
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.simulation import rehearse
from fdai_deployment_cli.source_azure import plan_source_installation
from fdai_deployment_cli.source_deploy import prepare_source_deployment
from fdai_deployment_cli.source_foundation import prepare_source_foundation_plan
from fdai_deployment_cli.standalone_application import read_exact_approval_input
from fdai_deployment_cli.standalone_deploy import deploy_azure_foundation
from fdai_deployment_cli.state import read_journal
from fdai_deployment_cli.status_projection import project_status
from fdai_deployment_cli.support_install import install_support
from fdai_deployment_cli.target import compute_target_binding


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
    """Collect bounded exact approval and apply one Console update plan."""

    if args.output != "text" or not sys.stdin.isatty():
        raise ValueError("Console update apply requires text output and a real terminal")
    work_dir = _absolute_work_dir(args.work_dir)
    plan = load_console_update_plan(work_dir / "plan.json")
    print(
        "Console update exact plan\n"
        f"  source commit: {plan['source_commit']}\n"
        f"  target binding: {plan['target_binding']}\n"
        f"  candidate SHA-256: {plan['candidate_archive_sha256']}\n"
        f"  rollback SHA-256: {plan['rollback_archive_sha256']}\n"
        f"  plan digest: {plan['plan_digest']}\n"
        "Type the exact plan digest to approve publication:",
        file=sys.stderr,
    )
    approved_digest = read_exact_approval_input(timeout_seconds=min(args.timeout_seconds, 600))
    source_root = _absolute_work_dir(args.source)
    result = apply_console_update_plan(
        source_root=source_root,
        work_dir=work_dir,
        approved_plan_digest=approved_digest,
        scripts=source_root / "scripts/deployment/azure",
        timeout_seconds=args.timeout_seconds,
    )
    _print_mapping(
        result,
        output=args.output,
        text=f"Console update applied and read back: {result['receipt_digest']}",
    )
    return 0


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


def _provision_plan(args: argparse.Namespace) -> int:
    work_dir = _absolute_work_dir(args.work_dir)
    profile = load_profile(args.profile)
    foundation = args.stage == "foundation"
    source_mode = args.source_snapshot is not None
    if source_mode:
        if (
            not foundation
            or not args.save_plan
            or args.source_snapshot_digest is None
            or args.terraform is None
        ):
            raise ValueError(
                "source plans require foundation, --save-plan, snapshot digest and Terraform"
            )
        if args.release_root is not None or args.bundle_public_key is not None:
            raise ValueError("source plans cannot accept kit verification keys")
    elif args.release_root is None or args.bundle_public_key is None:
        raise ValueError("kit plans require release and bundle verification keys")
    elif args.source_snapshot_digest is not None or args.terraform is not None:
        raise ValueError("kit plans cannot accept source execution inputs")
    if args.save_plan and not foundation:
        raise ValueError("saved local plans are supported only for the foundation stage")
    if foundation and (profile.host != "managed-vm" or profile.monthly_cost_ceiling <= 0):
        raise ValueError("foundation planning requires a managed-vm profile and cost ceiling")
    active_binding = azure_active_target_binding()
    if foundation and active_binding != profile.target_binding:
        raise ValueError("foundation planning requires the authenticated operator target")
    if foundation and os.environ.get("ARM_USE_MSI", ""):
        raise ValueError(
            "foundation planning uses the authenticated operator, not managed identity"
        )
    _validate_plan_target(
        profile_binding=profile.target_binding,
        active_binding=active_binding,
        use_managed_identity=os.environ.get("ARM_USE_MSI", "").casefold() == "true",
    )
    if source_mode:
        _create_private_work_dir(work_dir)
        result = prepare_source_foundation_plan(
            snapshot=_absolute_work_dir(args.source_snapshot),
            snapshot_digest=cast(str, args.source_snapshot_digest),
            terraform=_absolute_work_dir(cast(Path, args.terraform)),
            profile=profile,
            variables_file=args.variables_file,
            work_dir=work_dir,
            environment_builder=_terraform_environment,
        )
        _print_mapping(
            result,
            output=args.output,
            text="source Foundation plan saved; exact human approval remains required",
        )
        return 0
    verification = verify_offline_kit(
        args.offline_kit,
        release_root_pem=_read_public_key(cast(Path, args.release_root)),
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
        public_key_pem=_read_public_key(cast(Path, args.bundle_public_key)),
        cli_version=__version__,
    )
    _require_bundle_version(
        kit_version=verification.bundle_version,
        bundle_version=bundle_verification.bundle_version,
    )
    infra_dir = bundle_root / "infra"
    if not infra_dir.is_dir():
        raise ValueError("verified deployment bundle does not contain infra")
    if foundation:
        infra_dir = infra_dir / "genesis-foundation"
        if not infra_dir.is_dir() or not (infra_dir / ".terraform.lock.hcl").is_file():
            raise ValueError(
                "verified deployment bundle does not contain the locked foundation root"
            )
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
    snapshot_input = snapshot_foundation_input if foundation else snapshot_plan_input
    plan_context = snapshot_input(
        args.variables_file,
        variables_file,
        expected_target_binding=profile.target_binding,
        expected_region=profile.region,
        expected_environment=profile.environment,
    )
    try:
        environment = _terraform_environment(
            work_dir=work_dir,
            config=config,
            source=os.environ,
            subscription_id=plan_context.subscription_id,
            tenant_id=plan_context.tenant_id,
            azure_cli_path=Path(azure_cli) if (azure_cli := shutil.which("az")) else None,
        )
        variables = read_plan_input(variables_file) if args.save_plan else {}
        if (
            args.save_plan
            and foundation
            and profile.access_method == "bastion"
            and variables.get("enable_bastion") is not True
        ):
            raise ValueError("Foundation Bastion profile requires Bastion in the exact plan")
        runner_image_observation_digest = (
            verify_foundation_runner_image(variables, expected_region=profile.region)
            if args.save_plan and foundation
            else ""
        )
        provider_lock = (infra_dir / ".terraform.lock.hcl").read_bytes() if args.save_plan else b""
        saved_context = (
            foundation_plan_context(
                profile=profile,
                variables=variables,
                offline_manifest_digest=verification.manifest_digest,
                deployment_bundle_digest=bundle_verification.manifest_digest,
                terraform_digest=dict(verification.file_digests)[verification.terraform_binary],
                provider_lock=provider_lock,
                runner_image_observation_digest=runner_image_observation_digest,
            )
            if args.save_plan
            else {}
        )
        initialized = subprocess.run(
            [str(terraform), "init", "-backend=false", "-input=false", "-lockfile=readonly"],
            cwd=infra_dir,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if initialized.returncode != 0:
            raise ValueError("terraform initialization failed with the locked offline providers")
        saved_review = None
        with (
            TemporaryDirectory(prefix="foundation-plan-", dir=work_dir)
            if args.save_plan
            else nullcontext(None)
        ) as temporary:
            command = [
                str(terraform),
                "plan",
                "-input=false",
                "-no-color",
                f"-var-file={variables_file}",
            ]
            if temporary is not None:
                command.append(f"-out={Path(temporary) / 'plan.tfplan'}")
            completed = subprocess.run(
                command,
                cwd=infra_dir,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
                umask=0o077,
            )
            if completed.returncode != 0:
                raise ValueError(_safe_plan_error(completed.stdout + completed.stderr))
            if temporary is not None:
                if (infra_dir / ".terraform.lock.hcl").read_bytes() != provider_lock:
                    raise ValueError("foundation provider lock changed during planning")
                saved_review = save_foundation_plan(
                    plan=Path(temporary) / "plan.tfplan",
                    destination=work_dir,
                    terraform=terraform,
                    root=infra_dir,
                    environment=environment,
                    context=saved_context,
                    variables=variables,
                )
    finally:
        variables_file.unlink(missing_ok=True)
    result = {
        "schema_version": "fdai.provision-plan.v1",
        "offline_manifest_digest": verification.manifest_digest,
        "mutation_performed": False,
    }
    if foundation:
        result.update(
            {
                "stage": "foundation",
                "state": "review",
                "subscription_ready": False,
                "apply_authorized": False,
                "deployment_bundle_digest": bundle_verification.manifest_digest,
                "profile_digest": canonical_digest(profile.to_mapping()),
            }
        )
    if saved_review is not None:
        result["saved_plan"] = saved_review
    text = (
        f"foundation plan saved; review digest: {saved_review['review_digest']}; no apply authorized"
        if saved_review is not None
        else "foundation dry run completed; approval and installation remain required"
        if foundation
        else "plan completed"
    )
    print(
        json.dumps(result, sort_keys=True, separators=(",", ":")) if args.output == "json" else text
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


def _print_mapping(result: Mapping[str, object], *, output: str, text: str) -> None:
    print(json.dumps(result, sort_keys=True, separators=(",", ":")) if output == "json" else text)


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

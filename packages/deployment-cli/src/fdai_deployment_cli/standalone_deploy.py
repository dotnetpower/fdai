"""Supervise signed-kit Azure Foundation without GitHub services or a source checkout."""

from __future__ import annotations

import importlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai_deployment_cli.aks_preflight import inspect_aks_target
from fdai_deployment_cli.application_state_adoption import (
    ApplicationStateAdoption,
    stage_application_state_adoption,
)
from fdai_deployment_cli.azure_naming import selected_azure_region_short_name
from fdai_deployment_cli.catalog_review_profile import CatalogReviewDeploymentProfile
from fdai_deployment_cli.control_package import verify_control_package
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.deployment_kit import DeploymentKit, acquire_deployment_kit
from fdai_deployment_cli.deployment_progress import begin_stage, progress_detail, terminal_output
from fdai_deployment_cli.foundation_failure import foundation_failure_summary
from fdai_deployment_cli.foundation_output import foundation_output
from fdai_deployment_cli.foundation_process import run_foundation_process
from fdai_deployment_cli.private_output import read_private_bytes
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.standalone_application_completion import complete_application
from fdai_deployment_cli.standalone_foundation_adoption import (
    deploy_with_adopted_foundation,
)
from fdai_deployment_cli.standalone_foundation_transition import (
    default_transition_plan_runner,
    run_foundation_transition,
)
from fdai_deployment_cli.standalone_status import current_status, prior_attempt
from fdai_service_contracts.product_profile import ProductAddOn

_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SAFE_ENVIRONMENT_KEYS = frozenset(
    {
        "AZURE_CONFIG_DIR",
        "CURL_CA_BUNDLE",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOGNAME",
        "PATH",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "TERM",
        "TMPDIR",
        "TZ",
        "USER",
    }
)


@dataclass(frozen=True, slots=True)
class ActiveAzureTarget:
    """Authenticated Azure user target selected by the current CLI profile."""

    subscription_id: str
    tenant_id: str


def deploy_azure_foundation(
    *,
    work_dir: Path,
    online: bool,
    offline_kit: Path | None,
    online_url: str | None,
    region: str,
    monthly_cost_ceiling: int,
    timeout_seconds: int,
    trial_token: Path | None,
    runtime_profile: RuntimeDeploymentProfile | None = None,
    adopt_runner_image_receipt: Path | None = None,
    adopt_application_state: Path | None = None,
    adopt_application_recovery: Path | None = None,
    adopt_resolved_models: Path | None = None,
    adopt_foundation_directory: Path | None = None,
    adopt_foundation_recovery_directory: Path | None = None,
    catalog_review_profile: CatalogReviewDeploymentProfile | None = None,
    control_package: Path | None = None,
) -> dict[str, object]:
    """Advance one standalone deployment through verified application convergence.

    ``control_package`` optionally selects a signed deployment-control wheelhouse that replaces
    only the managed-host CLI; the verified kit still supplies every runtime payload.
    """

    deadline = DeploymentDeadline(timeout_seconds, clock=time.monotonic)
    selected_runtime = runtime_profile or RuntimeDeploymentProfile.create(
        runtime_platform="container-apps",
        database_placement="postgres-flex",
    )
    begin_stage("azure")
    progress_detail("Checking the active Azure CLI human identity")
    target = active_azure_target()
    deadline.remaining()
    _create_or_validate_private_directory(work_dir)
    kit_work = work_dir / "kit-work"
    _create_or_validate_private_directory(kit_work)
    begin_stage("kit")
    kit = acquire_deployment_kit(
        work_dir=kit_work,
        online=online,
        offline_kit=offline_kit,
        online_url=online_url,
    )
    deadline.remaining()
    control = None
    if control_package is not None:
        if online:
            raise ValueError("a control package requires a local signed offline kit")
        progress_detail("Verifying the signed deployment-control package")
        control = verify_control_package(control_package)
    adoption_inputs = (
        adopt_application_state,
        adopt_application_recovery,
        adopt_resolved_models,
    )
    if any(value is not None for value in adoption_inputs) and not all(
        value is not None for value in adoption_inputs
    ):
        raise ValueError("recovered public deployment requires all three adoption inputs")
    adoption: ApplicationStateAdoption | None = None
    if all(value is not None for value in adoption_inputs):
        assert adopt_application_state is not None
        assert adopt_application_recovery is not None
        assert adopt_resolved_models is not None
        region_short = selected_azure_region_short_name(
            region=region,
            subscription_id=target.subscription_id,
            environment="dev",
            workload="fdai",
            retained_variables=work_dir / "run" / "foundation-variables.json",
        )
        adoption = stage_application_state_adoption(
            source_state=adopt_application_state,
            recovery_receipt=adopt_application_recovery,
            resolved_models=adopt_resolved_models,
            output_directory=work_dir / "application-state-adoption",
            subscription_id=target.subscription_id,
            resource_group_name=f"rg-fdai-dev-{region_short}",
            environment="dev",
            region_short=region_short,
        )
    adopted = deploy_with_adopted_foundation(
        foundation_directory=adopt_foundation_directory,
        recovery_directory=adopt_foundation_recovery_directory,
        adopt_runner_image_receipt=adopt_runner_image_receipt,
        work_dir=work_dir,
        kit=kit,
        tenant_id=target.tenant_id,
        subscription_id=target.subscription_id,
        region=region,
        monthly_cost_ceiling=monthly_cost_ceiling,
        deadline=deadline,
        selected_runtime=selected_runtime,
        trial_token=trial_token,
        application_state_adoption=adoption,
        catalog_review_profile=catalog_review_profile,
        current_operator_object_id=_current_operator_object_id,
        control_package=control,
    )
    if adopted is not None:
        return adopted
    if (
        selected_runtime.runtime_platform.value == "aks"
        and adoption is None
        and not (work_dir / "run" / "status.json").exists()
    ):
        if _identity_add_on_selected(selected_runtime):
            _require_unique_entra_display_names(
                selected_runtime, kit.bundle_root / "scripts/deployment/azure"
            )
        _require_feasible_new_aks_target(selected_runtime, region=region, deadline=deadline)
    begin_stage("discovery")
    progress_detail("Discovering image, storage name, and non-overlapping networks")
    scripts = kit.bundle_root / "scripts/deployment/azure"
    if not scripts.is_dir() or scripts.is_symlink():
        raise ValueError("verified deployment bundle is missing Azure orchestration")
    create_runner_image = not online and adopt_runner_image_receipt is None
    sys.path.insert(0, str(scripts))
    try:
        prepare = importlib.import_module("genesis_prepare")
        prepared: Any = prepare.prepare_standalone_genesis(
            deployment_kit=kit,
            tenant_id=target.tenant_id,
            subscription_id=target.subscription_id,
            region=region,
            monthly_cost_ceiling=monthly_cost_ceiling,
            connectivity="online" if online else "offline",
            root=work_dir / "run",
            create_runner_image=create_runner_image,
            region_short=selected_azure_region_short_name(
                region=region,
                subscription_id=target.subscription_id,
                environment="dev",
                workload="fdai",
                retained_variables=work_dir / "run" / "foundation-variables.json",
            ),
        )
        foundation_variables = prepared.variables
        if adopt_runner_image_receipt is not None:
            runner_image = importlib.import_module("genesis_runner_image_contract")
            foundation_variables = prepared.root / "foundation-with-runner-image.json"
            if foundation_variables.exists():
                runner_image.verify_foundation_image_input(
                    source=prepared.variables,
                    image_receipt=adopt_runner_image_receipt,
                    profile_path=prepared.profile,
                    destination=foundation_variables,
                )
            else:
                runner_image.materialize_foundation_image_input(
                    source=prepared.variables,
                    image_receipt=adopt_runner_image_receipt,
                    profile_path=prepared.profile,
                    destination=foundation_variables,
                )
    finally:
        sys.path.remove(str(scripts))
    # An offline kit upgrade continues the retained Foundation under the revision that created
    # it; the newly verified kit remains the application source.
    foundation_source = str(getattr(prepared, "foundation_source_commit", "") or kit.source_commit)
    lineage_continuation = foundation_source != kit.source_commit
    source_evidence = json.dumps(
        {
            "source_commit": kit.source_commit,
            "foundation_source_commit": foundation_source,
            "kit_manifest_digest": kit.verification.manifest_digest,
            "bundle_manifest_digest": kit.bundle_manifest_digest,
            "runtime_release_digest": kit.runtime.digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    approval = prepared.root / "current-foundation-approval.json"
    status_path = prepared.root / "status.json"
    begin_stage("foundation")
    while True:
        remaining = deadline.remaining()
        if remaining < 1830:
            raise TimeoutError("standalone Foundation deadline has insufficient remaining budget")
        previous_attempt = prior_attempt(status_path)
        stage_timeout = min(14_400, remaining - 30)
        command = (
            sys.executable,
            str(scripts / "genesis_orchestrator.py"),
            "--environment",
            "dev",
            "--region",
            region,
            "--apply",
            "--allow-probe-resources",
            "--source-commit",
            foundation_source,
            "--work-dir",
            str(prepared.root),
            "--foundation-offline-kit",
            str(prepared.offline_kit),
            "--foundation-release-root",
            str(prepared.release_root),
            "--foundation-bundle-public-key",
            str(prepared.bundle_public_key),
            "--foundation-profile",
            str(prepared.profile),
            "--foundation-variables-file",
            str(foundation_variables),
            *(
                ()
                if not create_runner_image
                else (
                    "--create-runner-image",
                    "--runner-image-terraform",
                    str(prepared.terraform),
                )
            ),
            "--runner-ssh-private-key",
            str(prepared.ssh_private_key),
            *(("--approval-file", str(approval)) if approval.exists() else ()),
            "--execution-timeout-seconds",
            str(stage_timeout),
            "--output",
            "json",
        )
        try:
            with foundation_output() as stderr:
                foundation_exit = run_foundation_process(
                    command,
                    cwd=kit.bundle_root,
                    env=_standalone_subprocess_environment(
                        PYTHONPATH=os.pathsep.join(
                            (str(scripts), str(Path(__file__).parent.parent))
                        ),
                        AZURE_SUBSCRIPTION_ID=target.subscription_id,
                        AZURE_TENANT_ID=target.tenant_id,
                        FDAI_SIGNED_SOURCE_EVIDENCE=source_evidence,
                    ),
                    stdout=subprocess.DEVNULL,
                    stderr=stderr,
                    timeout=stage_timeout + 15,
                )
                if foundation_exit.returncode not in {0, 2}:
                    raise ValueError(
                        foundation_failure_summary(
                            status_path,
                            previous=previous_attempt,
                            source_commit=foundation_source,
                            run_binding=prepared.run_binding,
                        )
                    )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                "standalone Foundation orchestration timed out; inspect retained status before recovery"
            ) from exc
        status = current_status(
            status_path,
            previous=previous_attempt,
            source_commit=foundation_source,
            run_binding=prepared.run_binding,
        )
        completed_stages = status.get("completed_stages")
        if (
            status.get("current_stage") == "application-plan"
            and status.get("route") == "private-runner"
            and isinstance(completed_stages, list)
            and "foundation-state" in completed_stages
        ):
            foundation = _foundation_result(kit, prepared, status)
            lineage_receipt_digest = _bind_application_to_foundation_lineage(
                kit=kit,
                prepared=prepared,
                status=status,
                lineage_continuation=lineage_continuation,
                tenant_id=target.tenant_id,
                subscription_id=target.subscription_id,
                region=region,
                monthly_cost_ceiling=monthly_cost_ceiling,
            )
            deadline.remaining()
            return complete_application(
                kit=kit,
                prepared=prepared,
                status=status,
                scripts=scripts,
                deadline=deadline,
                selected_runtime=selected_runtime,
                trial_token=trial_token,
                application_state_adoption=adoption,
                foundation_state_receipt_digest=str(foundation["foundation_state_receipt_digest"]),
                foundation_adoption_receipt_digest=lineage_receipt_digest,
                catalog_review_profile=(
                    catalog_review_profile or CatalogReviewDeploymentProfile.unselected()
                ),
                current_operator_object_id=_current_operator_object_id,
                control_package=control,
            )
        if foundation_exit.returncode != 2:
            raise ValueError("standalone Foundation orchestration failed")
        if lineage_continuation:
            # A new Foundation plan computed from the newer kit must not be approved under the
            # retained revision's lineage; continuation only verifies completed checkpoints.
            raise ValueError(
                "offline kit upgrade requires a completed Foundation and cannot approve a new "
                "Foundation plan under its retained source lineage; inspect retained status"
            )
        approval.unlink(missing_ok=True)
        try:
            with terminal_output("Review the exact Foundation plan", approval=True):
                prompt = subprocess.run(
                    (
                        sys.executable,
                        str(scripts / "genesis_approval_prompt.py"),
                        "--status",
                        str(status_path),
                        "--output",
                        str(approval),
                    ),
                    cwd=kit.bundle_root,
                    env=_standalone_subprocess_environment(
                        PYTHONPATH=os.pathsep.join(
                            (str(scripts), str(Path(__file__).parent.parent))
                        ),
                        FDAI_SIGNED_SOURCE_EVIDENCE=source_evidence,
                    ),
                    stdout=sys.stderr,
                    check=False,
                    timeout=deadline.remaining(600),
                )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("standalone Foundation approval prompt timed out") from exc
        if prompt.returncode != 0:
            raise ValueError("standalone Foundation approval was not granted")


def _require_feasible_new_aks_target(
    profile: RuntimeDeploymentProfile,
    *,
    region: str,
    deadline: DeploymentDeadline,
) -> None:
    """Stop a new AKS installation before its first Azure change when the target is infeasible."""

    progress_detail("Checking AKS capacity and database availability before the first Azure change")
    preflight = inspect_aks_target(
        profile=profile, region=region, timeout_seconds=deadline.remaining(180)
    )
    if preflight.get("state") != "feasible":
        blockers = preflight.get("blockers")
        names = (
            ", ".join(str(item) for item in blockers)
            if isinstance(blockers, list) and blockers
            else "unknown"
        )
        raise ValueError(f"standalone AKS preflight blocked a new installation: {names}")


def _require_unique_entra_display_names(
    profile: RuntimeDeploymentProfile,
    scripts: Path,
) -> None:
    """Stop identity-enabled new installations before first Azure effect if names are ambiguous."""

    if not _identity_add_on_selected(profile):
        return
    sys.path.insert(0, str(scripts))
    try:
        genesis_entra = importlib.import_module("genesis_entra")
        check = getattr(genesis_entra, "check_unique_display_names", None)
        if callable(check):
            check()
            return
        plan_entra = getattr(genesis_entra, "plan_entra", None)
        if callable(plan_entra):
            plan_entra()
    finally:
        sys.path.remove(str(scripts))


def _identity_add_on_selected(profile: RuntimeDeploymentProfile) -> bool:
    product = profile.product_profile
    return product.selects(ProductAddOn.READ_ONLY_CONSOLE) or product.selects(
        ProductAddOn.ENTERPRISE_IDENTITY_GOVERNANCE
    )


def active_azure_target() -> ActiveAzureTarget:
    """Read the active Azure CLI user target without changing account selection."""

    try:
        completed = subprocess.run(
            (
                "az",
                "account",
                "show",
                "--query",
                "{subscription_id:id,tenant_id:tenantId,user_type:user.type}",
                "--output",
                "json",
                "--only-show-errors",
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError(
            "Azure authentication read failed; inspect the local login context"
        ) from None
    if completed.returncode != 0:
        raise ValueError("Azure authentication is unavailable; run az login first")
    value = json.loads(completed.stdout)
    subscription = value.get("subscription_id") if isinstance(value, dict) else None
    tenant = value.get("tenant_id") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("user_type") != "user"
        or not isinstance(subscription, str)
        or _GUID.fullmatch(subscription) is None
        or not isinstance(tenant, str)
        or _GUID.fullmatch(tenant) is None
    ):
        raise ValueError("standalone deployment requires an authenticated Azure human")
    return ActiveAzureTarget(subscription_id=subscription, tenant_id=tenant)


def _standalone_subprocess_environment(
    source: Mapping[str, str] | None = None,
    **overrides: str,
) -> dict[str, str]:
    """Return the minimal non-secret environment used by standalone child processes."""

    inherited = os.environ if source is None else source
    result = {key: inherited[key] for key in _SAFE_ENVIRONMENT_KEYS if key in inherited}
    result.update(overrides)
    return result


def _current_operator_object_id() -> str:
    try:
        completed = subprocess.run(
            (
                "az",
                "ad",
                "signed-in-user",
                "show",
                "--query",
                "id",
                "--output",
                "tsv",
                "--only-show-errors",
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError("authenticated Azure operator read failed; no retry performed") from None
    value = completed.stdout.strip()
    if completed.returncode != 0 or _GUID.fullmatch(value) is None:
        raise ValueError("authenticated Azure operator object ID is unavailable")
    return value


def _bind_application_to_foundation_lineage(
    *,
    kit: DeploymentKit,
    prepared: Any,
    status: dict[str, Any],
    lineage_continuation: bool,
    tenant_id: str,
    subscription_id: str,
    region: str,
    monthly_cost_ceiling: int,
) -> str | None:
    """Give the managed host verified evidence that binds a retained Foundation to this kit."""

    receipt_path = prepared.root / "foundation-adoption-receipt.json"
    if not lineage_continuation:
        if receipt_path.exists() or receipt_path.is_symlink():
            retained = _private_json(receipt_path)
            if retained.get("foundation_source_commit") == kit.source_commit:
                # The kit is back at the Foundation's own revision, so no adoption applies.
                review = prepared.root / "foundation-adoption-review"
                _create_or_validate_private_directory(review)
                receipt_path.rename(review / f"{str(retained.get('receipt_digest'))[:16]}.json")
        return None
    report = status.get("foundation_report")
    plan = report.get("foundation_plan") if isinstance(report, dict) else None
    plan_ref = plan.get("plan_ref") if isinstance(plan, dict) else None
    if (
        not isinstance(plan_ref, str)
        or re.fullmatch(r"foundation-plan-attempt-[1-9][0-9]*", plan_ref) is None
    ):
        raise ValueError("retained Foundation plan reference is invalid")
    receipt = run_foundation_transition(
        kit=kit,
        run_root=prepared.root,
        retained_plan_ref=plan_ref,
        transition_plan_ref=None,
        application_source_commit=kit.source_commit,
        kit_manifest_digest=kit.verification.manifest_digest,
        runtime_release_digest=kit.runtime.digest,
        tenant_id=tenant_id,
        subscription_id=subscription_id,
        region=region,
        monthly_cost_ceiling=monthly_cost_ceiling,
        plan_runner=default_transition_plan_runner,
    )
    return str(receipt["receipt_digest"])


def _foundation_result(
    kit: DeploymentKit, prepared: Any, status: dict[str, Any]
) -> dict[str, object]:
    report = status.get("foundation_report")
    handoff = report.get("state_handoff") if isinstance(report, dict) else None
    receipt = handoff.get("receipt_digest") if isinstance(handoff, dict) else None
    if not isinstance(receipt, str) or _DIGEST.fullmatch(receipt) is None:
        raise ValueError("Foundation state handoff receipt is unavailable")
    return {
        "schema_version": "fdai.standalone-azure-deployment.v1",
        "state": "foundation-ready",
        "source_commit": kit.source_commit,
        "kit_manifest_digest": kit.verification.manifest_digest,
        "runtime_release_digest": kit.runtime.digest,
        "foundation_state_receipt_digest": receipt,
        "work_dir": str(prepared.root),
        "next_action": "plan-standalone-application",
        "mutation_performed": True,
        "subscription_ready": False,
    }


def _private_json(path: Path) -> dict[str, Any]:
    value = json.loads(read_private_bytes(path, max_bytes=1_048_576))
    if not isinstance(value, dict):
        raise ValueError("standalone deployment status is invalid")  # noqa: TRY004 - JSON contract.
    return {str(key): item for key, item in value.items()}


def _create_or_validate_private_directory(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    details = path.lstat()
    if (
        not path.is_absolute()
        or not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
        or details.st_uid != os.geteuid()
    ):
        raise PermissionError("standalone deployment directory must be current-UID mode 0700")

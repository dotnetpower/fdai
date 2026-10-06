"""Control standalone managed-host application deployment through Azure Bastion."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import select
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fdai_deployment_cli import standalone_catalog_checkpoint
from fdai_deployment_cli.application_state_adoption import ApplicationStateAdoption
from fdai_deployment_cli.catalog_review_profile import (
    CatalogReviewDeploymentProfile,
)
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.control_package import ControlPackage
from fdai_deployment_cli.deadline_transport import DeadlineTransport
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.deployment_kit import DeploymentKit, archive_verified_kit
from fdai_deployment_cli.deployment_progress import begin_stage, progress_detail, terminal_output
from fdai_deployment_cli.license_issue import deployment_license_token as _license_token
from fdai_deployment_cli.operational_evidence_verifier_input import (
    OperationalEvidenceVerifierDeploymentInput,
)
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.source_application_inputs import (
    build_source_console,
    source_transfer_inputs,
)
from fdai_deployment_cli.standalone_checkpoint_failure import remote_failure as _remote_failure
from fdai_deployment_cli.standalone_console_publish import publish_verified_console
from fdai_deployment_cli.standalone_remote_prepare import prepare_remote as _prepare_remote
from fdai_deployment_cli.standalone_review import validate_plan_review
from fdai_deployment_cli.standalone_transfer_cleanup import cleanup_remote_transfers, remote_prune
from fdai_deployment_cli.target import compute_target_binding

_DIGEST = re.compile(r"[0-9a-f]{64}")
_SSH_USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
__all__ = ["deploy_standalone_application", "publish_verified_console"]


def deploy_standalone_application(
    *,
    kit: DeploymentKit | None,
    prepared: Any,
    foundation_status: dict[str, Any],
    entra_bindings: dict[str, str] | None,
    scripts: Path,
    trial_token: Path | None,
    timeout_seconds: int,
    runtime_profile: RuntimeDeploymentProfile | None = None,
    application_state_adoption: ApplicationStateAdoption | None = None,
    catalog_review_profile: CatalogReviewDeploymentProfile | None = None,
    operational_evidence_verifier_input: OperationalEvidenceVerifierDeploymentInput | None = None,
    control_package: ControlPackage | None = None,
    source_snapshot: Path | None = None,
    source_snapshot_digest: str | None = None,
    source_root: Path | None = None,
) -> dict[str, object]:
    """Deploy and independently replan the application without a workflow host."""

    deadline = DeploymentDeadline(timeout_seconds, clock=time.monotonic)
    selected_runtime = runtime_profile or RuntimeDeploymentProfile.create(
        runtime_platform="container-apps",
        database_placement="postgres-flex",
    )
    source_mode = source_snapshot is not None
    begin_stage("transfer")
    progress_detail(
        "Verifying the handoff and preparing the source snapshot for Bastion transfer"
        if source_mode
        else "Verifying the handoff and preparing the signed kit for Bastion transfer"
    )
    report = _mapping(foundation_status.get("foundation_report"), "Foundation report")
    plan = _mapping(report.get("foundation_plan"), "Foundation plan")
    plan_directory = prepared.root / str(plan["plan_ref"])
    handoff_path = plan_directory / "foundation-private-handoff.json"
    handoff = _private_json(handoff_path, "Foundation handoff")
    adoption_descriptor_digest = (
        canonical_digest(
            _private_json(application_state_adoption.descriptor, "adoption descriptor")
        )
        if application_state_adoption is not None
        else ""
    )
    runner = _mapping(handoff.get("runner"), "Foundation runner")
    access = _mapping(handoff.get("access"), "Foundation access")
    ops = _mapping(handoff.get("ops"), "Foundation operations")
    known_hosts = plan_directory / "runner-known-hosts"
    module = _import_bastion(scripts)
    module.validate_known_hosts(known_hosts)
    private_key = prepared.ssh_private_key
    if module.validate_ssh_private_key(private_key) != runner.get("ssh_key_digest"):
        raise ValueError("standalone host SSH key differs from Foundation evidence")
    source_transfer = None
    if source_mode:
        if (
            kit is not None
            or source_snapshot_digest is None
            or source_snapshot is None
            or source_root is None
        ):
            raise ValueError("source application continuation inputs are incomplete")
        source_transfer = source_transfer_inputs(
            prepared_root=prepared.root,
            source_snapshot=source_snapshot,
            source_snapshot_digest=source_snapshot_digest,
        )
        transport_archive = source_transfer.archive
        archive_digest = None
    else:
        if kit is None:
            raise ValueError("standalone application requires a verified kit or source snapshot")
        transport_archive = prepared.root / "standalone-kit.tar.gz"
        archive_digest = archive_verified_kit(kit, transport_archive)
    entra_path = prepared.root / "entra-bindings.json" if entra_bindings is not None else None
    if entra_path is not None and entra_bindings is not None:
        _replace_private_json(entra_path, entra_bindings)
    work_binding: dict[str, object] = {
        "target_binding": prepared.target_binding,
        "source_commit": prepared.source_commit,
        "runtime_profile_digest": selected_runtime.digest,
    }
    if source_mode:
        work_binding["source_snapshot_digest"] = source_snapshot_digest
        work_binding["provenance"] = "operator-selected-source"
    else:
        work_binding["kit_manifest_digest"] = prepared.kit_manifest_digest
    if control_package is not None:
        work_binding["control_package_digest"] = control_package.archive_digest
    work_ref = canonical_digest(work_binding)[:24]
    username = str(runner["admin_username"])
    if _SSH_USER.fullmatch(username) is None:
        raise ValueError("Foundation runner SSH username is invalid")
    remote_root = f"/home/{username}/.fdai-transfer-{work_ref}"
    remote_archive = f"{remote_root}/kit.tar.gz"
    remote_handoff = f"{remote_root}/foundation-handoff.json"
    remote_entra = f"{remote_root}/entra-bindings.json" if entra_path is not None else None
    remote_approval = f"{remote_root}/approval.json"
    remote_adoption_state = f"{remote_root}/application-state.json"
    remote_adoption_models = f"{remote_root}/resolved-models.json"
    remote_adoption_descriptor = f"{remote_root}/application-state-adoption.json"
    app_work = f"{remote_root}/application"
    host_alias = module.stable_host_key_alias(str(runner["vm_id"]))
    with module.BastionTunnel(
        subscription_id=str(handoff["subscription_id"]),
        resource_group=str(ops["resource_group_name"]),
        bastion_name=str(access["bastion_name"]),
        vm_id=str(runner["vm_id"]),
        username=username,
        private_key=private_key,
        known_hosts=known_hosts,
        host_key_alias=host_alias,
        cwd=plan_directory,
        timeout=deadline.remaining(),
        trust_new_host_key=False,
    ) as underlying_tunnel:
        tunnel = DeadlineTransport(underlying_tunnel, deadline)
        host_preparation = _prepare_remote(
            tunnel,
            remote_root=remote_root,
            remote_archive=remote_archive,
            archive=None if source_mode else transport_archive,
            archive_digest=archive_digest,
            handoff_path=handoff_path,
            remote_handoff=remote_handoff,
            entra_path=entra_path,
            remote_entra=remote_entra,
            app_work=app_work,
            source_archive=transport_archive if source_mode else None,
            source_archive_digest=(
                source_transfer.archive_digest if source_transfer is not None else None
            ),
            source_receiver=source_transfer.receiver if source_transfer is not None else None,
            source_receiver_digest=(
                source_transfer.receiver_digest if source_transfer is not None else None
            ),
            source_snapshot_digest=source_snapshot_digest if source_mode else None,
            source_runtime_requirements=(
                source_transfer.runtime_requirements if source_transfer is not None else None
            ),
            source_runtime_requirements_digest=(
                source_transfer.runtime_requirements_digest if source_transfer is not None else None
            ),
            runtime_profile=selected_runtime,
            application_state_adoption=application_state_adoption,
            remote_adoption_state=remote_adoption_state,
            remote_adoption_models=remote_adoption_models,
            remote_adoption_descriptor=remote_adoption_descriptor,
            timeout_seconds=deadline.remaining(),
            catalog_review_profile=(
                catalog_review_profile or CatalogReviewDeploymentProfile.unselected()
            ),
            operational_evidence_verifier_input=operational_evidence_verifier_input,
            control_package=control_package,
        )
        if (
            isinstance(host_preparation, dict)
            and host_preparation.get("focused_private_access") is True
        ):
            progress_detail("Converging the focused private data-plane access path")
            access_recovery = _remote_json(
                tunnel,
                remote_root,
                app_work,
                ("recover-apply", "--stage", "access"),
                timeout=3600,
            )
            if access_recovery.get("state") == "applied":
                access_receipt = access_recovery
            else:
                access_plan, access_apply_command = _plan_after_recovery(
                    tunnel,
                    remote_root,
                    app_work,
                    access_recovery,
                    stage="access",
                    timeout=3600,
                )
                deadline.remaining()
                access_approval = _approve_plan(prepared.root, access_plan, deadline=deadline)
                tunnel.ssh(("rm", "-f", "--", remote_approval), timeout=60)
                tunnel.copy_to(access_approval, remote_approval, timeout=120)
                access_receipt = _remote_json(
                    tunnel,
                    remote_root,
                    app_work,
                    (
                        access_apply_command,
                        "--stage",
                        "access",
                        "--approval",
                        remote_approval,
                    ),
                    timeout=7200,
                )
                access_approval.unlink(missing_ok=True)
                tunnel.ssh(("rm", "-f", "--", remote_approval), timeout=60)
            _require_receipt(access_receipt, "access")
        begin_stage("substrate")
        progress_detail("Recovering by verification, or planning private infrastructure")
        substrate_recovery = _remote_json(
            tunnel,
            remote_root,
            app_work,
            ("recover-apply", "--stage", "substrate"),
            timeout=3600,
        )
        if substrate_recovery.get("state") == "applied":
            substrate_receipt = substrate_recovery
        else:
            substrate_plan, substrate_apply_command = _plan_after_recovery(
                tunnel,
                remote_root,
                app_work,
                substrate_recovery,
                stage="substrate",
                timeout=3600,
            )
            if application_state_adoption is not None:
                _require_nondestructive_adoption_plan(substrate_plan)
            deadline.remaining()
            substrate_approval = _approve_plan(prepared.root, substrate_plan, deadline=deadline)
            tunnel.ssh(("rm", "-f", "--", remote_approval), timeout=60)
            tunnel.copy_to(substrate_approval, remote_approval, timeout=120)
            progress_detail("Applying the approved infrastructure plan and verifying its effects")
            substrate_receipt = _remote_json(
                tunnel,
                remote_root,
                app_work,
                (
                    substrate_apply_command,
                    "--stage",
                    "substrate",
                    "--approval",
                    remote_approval,
                ),
                timeout=7200,
            )
            substrate_approval.unlink(missing_ok=True)
            tunnel.ssh(("rm", "-f", "--", remote_approval), timeout=60)
        _require_receipt(substrate_receipt, "substrate")
        if selected_runtime.runtime_platform.value == "aks":
            begin_stage("runtime")
            progress_detail("Preparing and planning the private AKS runtime")
            _remote_json(
                tunnel,
                remote_root,
                app_work,
                ("prepare-runtime",),
                timeout=1800,
            )
            runtime_receipt: dict[str, Any] | None = None
            for runtime_phase in range(2):
                runtime_recovery = _remote_json(
                    tunnel,
                    remote_root,
                    app_work,
                    ("recover-apply", "--stage", "runtime"),
                    timeout=3600,
                )
                if runtime_recovery.get("state") == "applied":
                    runtime_receipt = runtime_recovery
                else:
                    runtime_plan, runtime_apply_command = _plan_after_recovery(
                        tunnel,
                        remote_root,
                        app_work,
                        runtime_recovery,
                        stage="runtime",
                        timeout=3600,
                    )
                    deadline.remaining()
                    runtime_approval = _approve_plan(prepared.root, runtime_plan, deadline=deadline)
                    tunnel.ssh(("rm", "-f", "--", remote_approval), timeout=60)
                    tunnel.copy_to(runtime_approval, remote_approval, timeout=120)
                    runtime_receipt = _remote_json(
                        tunnel,
                        remote_root,
                        app_work,
                        (
                            runtime_apply_command,
                            "--stage",
                            "runtime",
                            "--approval",
                            remote_approval,
                        ),
                        timeout=7200,
                    )
                    runtime_approval.unlink(missing_ok=True)
                    tunnel.ssh(("rm", "-f", "--", remote_approval), timeout=60)
                _require_receipt(runtime_receipt, "runtime")
                if runtime_receipt.get("operation") != "runtime-cluster":
                    break
                if runtime_phase == 1:
                    raise ValueError("fresh AKS runtime ordering did not reach the association")
                progress_detail(
                    "Planning Container Insights association after AKS cluster creation"
                )
            if runtime_receipt is None:
                raise ValueError("runtime apply receipt is unavailable")
            _require_receipt(runtime_receipt, "runtime")
        if selected_runtime.runtime_platform.value == "aks" and runtime_receipt is None:
            raise ValueError("runtime apply receipt is unavailable")
        runtime_receipt_digest = ""
        if selected_runtime.runtime_platform.value == "aks":
            if runtime_receipt is None:
                raise ValueError("runtime apply receipt is unavailable")
            runtime_receipt_digest = str(runtime_receipt["receipt_digest"])
        binding_receipt = _remote_json(
            tunnel,
            remote_root,
            app_work,
            ("deployment-binding",),
            timeout=300,
        )
        deployment_binding = str(binding_receipt.get("deployment_binding", ""))
        installation_binding = str(binding_receipt.get("installation_binding", ""))
        if (
            binding_receipt.get("terraform_name_verified") is not True
            or re.fullmatch(r"[0-9a-f]{64}", deployment_binding) is None
            or re.fullmatch(r"[0-9a-f]{64}", installation_binding) is None
        ):
            raise ValueError("standalone deployment binding is not verified")
        begin_stage("images")
        progress_detail("Importing runtime images and reading back their digests")
        image_receipt = _remote_json(
            tunnel,
            remote_root,
            app_work,
            ("import-images",),
            timeout=5400,
        )
        image_digests = _mapping(image_receipt.get("image_digests"), "image import receipt")
        core_digest = str(image_digests["core-control-plane"]).removeprefix("sha256:")
        if selected_runtime.database_placement.value == "postgres-aks":
            begin_stage("database")
            progress_detail("Preparing and planning compact in-cluster PostgreSQL")
            _remote_json(
                tunnel,
                remote_root,
                app_work,
                ("prepare-database",),
                timeout=1800,
            )
            database_recovery = _remote_json(
                tunnel,
                remote_root,
                app_work,
                ("recover-apply", "--stage", "database"),
                timeout=3600,
            )
            if database_recovery.get("state") == "applied":
                database_receipt = database_recovery
            else:
                database_plan, database_apply_command = _plan_after_recovery(
                    tunnel,
                    remote_root,
                    app_work,
                    database_recovery,
                    stage="database",
                    timeout=3600,
                )
                deadline.remaining()
                database_approval = _approve_plan(prepared.root, database_plan, deadline=deadline)
                tunnel.ssh(("rm", "-f", "--", remote_approval), timeout=60)
                tunnel.copy_to(database_approval, remote_approval, timeout=120)
                database_receipt = _remote_json(
                    tunnel,
                    remote_root,
                    app_work,
                    (
                        database_apply_command,
                        "--stage",
                        "database",
                        "--approval",
                        remote_approval,
                    ),
                    timeout=3600,
                )
                database_approval.unlink(missing_ok=True)
                tunnel.ssh(("rm", "-f", "--", remote_approval), timeout=60)
            _require_receipt(database_receipt, "database")
        begin_stage("capability")
        aks = selected_runtime.runtime_platform.value == "aks"
        token = _license_token(
            trial_token=trial_token,
            image_digest=core_digest,
            deployment_binding=deployment_binding,
            installation_binding=installation_binding if aks else None,
            work_ref=work_ref,
        )
        license_mode = "observation-only"
        if token is not None:
            license_receipt = _remote_json(
                tunnel,
                remote_root,
                app_work,
                (
                    "install-license",
                    "--image-digest",
                    core_digest,
                    "--deployment-binding",
                    deployment_binding,
                    *(("--installation-binding", installation_binding) if aks else ()),
                ),
                timeout=300,
                input_text=token,
            )
            token = ""
            if (
                license_receipt.get("secret_metadata_verified") is not True
                or license_receipt.get("secret_content_verified") is not True
            ):
                raise ValueError("standalone license installation was not verified")
            license_mode = "licensed"
        else:
            progress_detail(
                "No capability token; the keyless Trial opens after the application deploys"
                if aks
                else "Observation-only mode; no license secret is installed"
            )
        begin_stage("migration")
        progress_detail("Running database migrations and materializing catalogs")
        migration_receipt = _remote_json(
            tunnel,
            remote_root,
            app_work,
            ("migrate",),
            timeout=5400,
        )
        if (
            migration_receipt.get("state") != "migrated"
            or migration_receipt.get("catalogs_materialized") is not True
        ):
            raise ValueError("standalone database and catalog bootstrap is incomplete")
        begin_stage("application")
        progress_detail("Recovering by verification, or planning the application")
        if selected_runtime.runtime_platform.value == "aks":
            _remote_json(
                tunnel,
                remote_root,
                app_work,
                ("prepare-application",),
                timeout=1800,
            )
        application_recovery = _remote_json(
            tunnel,
            remote_root,
            app_work,
            ("recover-apply", "--stage", "application"),
            timeout=3600,
        )
        if application_recovery.get("state") == "applied":
            application_receipt = application_recovery
        else:
            application_plan, application_apply_command = _plan_after_recovery(
                tunnel,
                remote_root,
                app_work,
                application_recovery,
                stage="application",
                timeout=3600,
            )
            if application_state_adoption is not None:
                _require_nondestructive_adoption_plan(application_plan)
            deadline.remaining()
            application_approval = _approve_plan(prepared.root, application_plan, deadline=deadline)
            tunnel.ssh(("rm", "-f", "--", remote_approval), timeout=60)
            tunnel.copy_to(application_approval, remote_approval, timeout=120)
            progress_detail("Applying the approved application plan and verifying its effects")
            application_receipt = _remote_json(
                tunnel,
                remote_root,
                app_work,
                (
                    application_apply_command,
                    "--stage",
                    "application",
                    "--approval",
                    remote_approval,
                ),
                timeout=7200,
            )
            application_approval.unlink(missing_ok=True)
            tunnel.ssh(("rm", "-f", "--", remote_approval), timeout=60)
        _require_receipt(application_receipt, "application")
        post_application = standalone_catalog_checkpoint.run_post_application_checkpoints(
            tunnel,
            remote_root=remote_root,
            app_work=app_work,
            runtime_platform=selected_runtime.runtime_platform.value,
            remote_json=_remote_json,
        )
        initial_inventory = post_application.inventory
        catalog_review = post_application.catalog_review
        if license_mode == "observation-only" and post_application.trial_open:
            license_mode = "trial"
        begin_stage("verification")
        progress_detail("Checking service health and a second zero-change Terraform plan")
        verification = _remote_json(
            tunnel,
            remote_root,
            app_work,
            ("verify",),
            timeout=3600,
        )
        if (
            verification.get("terraform_zero_change_verified") is not True
            or verification.get("runtime_health_verified") is not True
        ):
            raise ValueError("standalone application convergence is incomplete")
        console_receipt: dict[str, object] | None = None
        if selected_runtime.console_selected and selected_runtime.runtime_platform.value == "aks":
            if entra_bindings is None:
                raise ValueError("read-only Console requires enterprise identity bindings")
            browser_console = _mapping(
                verification.get("browser_console"), "browser Console verification"
            )
            progress_detail("Registering the Console redirect and publishing verified static files")
            entra = _import_entra(scripts)
            redirect_changed = entra.ensure_console_spa_redirect(
                str(entra_bindings["ENTRA_CONSOLE_SPA_CLIENT_ID"]),
                str(browser_console["console_origin"]),
            )
            if source_mode:
                if source_root is None:
                    raise ValueError("source Console build requires a verified snapshot")
                console_archive, console_archive_sha256 = build_source_console(
                    source_root=source_root,
                    source_commit=prepared.source_commit,
                    prepared_root=prepared.root,
                    timeout_seconds=deadline.remaining(1800),
                )
                assert source_snapshot is not None
                bundle_root = source_snapshot / "tree"
            else:
                if kit is None:
                    raise ValueError("signed Console publication requires the verified kit")
                runtime = kit.runtime.to_mapping()
                console_artifact = _mapping(runtime.get("console"), "runtime Console artifact")
                console_archive = kit.materialized_root / str(console_artifact["archive"])
                console_archive_sha256 = str(console_artifact["archive_sha256"])
                bundle_root = kit.bundle_root
            console_receipt = publish_verified_console(
                console_archive=console_archive,
                console_archive_sha256=console_archive_sha256,
                bundle_root=bundle_root,
                prepared_root=prepared.root,
                entra_bindings=entra_bindings,
                browser_console=browser_console,
                scripts=scripts,
                subscription_id=str(handoff["subscription_id"]),
                tenant_id=str(handoff["tenant_id"]),
                timeout_seconds=deadline.remaining(),
                redirect_changed=redirect_changed,
            )
        transient_paths = (
            (f"{remote_root}/source-transfer.tar", f"{remote_root}/source-receiver.pyz")
            if source_mode
            else (remote_archive,)
        )
        cleanup_remote_transfers(
            tunnel,
            transient_paths=transient_paths,
            remote_approval=remote_approval,
            prune=lambda: remote_prune(tunnel, remote_root=remote_root, work_dir=app_work),
        )
    receipt: dict[str, object] = {
        "schema_version": "fdai.standalone-application-terminal-receipt.v2",
        "state": "application-converged",
        "source_commit": prepared.source_commit,
        "target_binding": prepared.target_binding,
        "substrate_receipt_digest": substrate_receipt["receipt_digest"],
        "initial_inventory_receipt_digest": initial_inventory["receipt_digest"],
        "catalog_review_receipt_digest": catalog_review["receipt_digest"],
        "catalog_review_state": catalog_review["state"],
        "runtime_receipt_digest": runtime_receipt_digest,
        "database_receipt_digest": (
            database_receipt["receipt_digest"]
            if selected_runtime.database_placement.value == "postgres-aks"
            else ""
        ),
        "image_import_receipt_digest": image_receipt["receipt_digest"],
        "migration_receipt_digest": migration_receipt["receipt_digest"],
        "application_receipt_digest": application_receipt["receipt_digest"],
        "verification_receipt_digest": verification["receipt_digest"],
        "console_publication_receipt_digest": (
            console_receipt["receipt_digest"] if console_receipt is not None else ""
        ),
        "runtime_profile_digest": selected_runtime.digest,
        "runtime_platform": selected_runtime.runtime_platform.value,
        "database_placement": selected_runtime.database_placement.value,
        "product_profile": selected_runtime.product_profile.model_dump(mode="json"),
        "remote_transient_cleanup_verified": True,
        "application_state_adopted": application_state_adoption is not None,
        "application_state_adoption_descriptor_digest": adoption_descriptor_digest,
        "application_converged": True,
        "browser_access_verified": console_receipt is not None,
        "deployment_ready": True,
        "inventory_ready": True,
        "license_mode": license_mode,
        "provenance": "operator-selected-source" if source_mode else "signed-release",
        "release_signature_verified": not source_mode,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    if source_mode:
        receipt["source_snapshot_digest"] = source_snapshot_digest
    elif kit is not None:
        kit_verification = getattr(kit, "verification", None)
        kit_runtime = getattr(kit, "runtime", None)
        if kit_verification is not None:
            receipt["kit_manifest_digest"] = kit_verification.manifest_digest
        if kit_runtime is not None:
            receipt["runtime_release_digest"] = kit_runtime.digest
    receipt["receipt_digest"] = canonical_digest(receipt)
    deadline.remaining()
    _replace_private_json(prepared.root / "standalone-application-receipt.json", receipt)
    return receipt


def _plan_after_recovery(
    tunnel: Any,
    remote_root: str,
    app_work: str,
    recovery: dict[str, Any],
    *,
    stage: str,
    timeout: int,
) -> tuple[dict[str, Any], str]:
    """Use a separately bound residual review, or request an ordinary current plan."""

    if isinstance(recovery.get("residual_recovery"), dict):
        return recovery, "apply-residual"
    return (
        _remote_json(
            tunnel,
            remote_root,
            app_work,
            ("plan", "--stage", stage),
            timeout=timeout,
        ),
        "apply",
    )


def _remote_json(
    tunnel: Any,
    remote_root: str,
    app_work: str,
    arguments: tuple[str, ...],
    *,
    timeout: int,
    input_text: str | None = None,
) -> dict[str, Any]:
    result = tunnel.ssh(
        (
            f"{remote_root}/venv/bin/python",
            "-m",
            "fdai_deployment_cli.standalone_host",
            "--work-dir",
            app_work,
            *arguments,
        ),
        timeout=timeout,
        input_text=input_text,
    )
    if result.returncode != 0:
        failure = _remote_failure(result)
        if failure is not None:
            codes = failure.get("provider_error_codes")
            code_text = (
                f"; provider_error_code={','.join(str(code) for code in codes)}"
                if isinstance(codes, list) and codes
                else ""
            )
            raise ValueError(
                "standalone managed-host checkpoint failed: "
                f"reason_code={failure['reason_code']}{code_text}; "
                f"excerpt={failure['message_excerpt']}"
            )
        raise ValueError("standalone managed-host checkpoint failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("standalone managed-host checkpoint returned invalid output") from exc
    return _mapping(value, "standalone managed-host result")


def _require_nondestructive_adoption_plan(review: dict[str, Any]) -> None:
    _stage, destructive = validate_plan_review(review)
    if destructive:
        raise ValueError("recovered application state requires a zero-destroy plan")


@terminal_output("Review the exact application plan", approval=True)
def _approve_plan(
    root: Path, review: dict[str, Any], *, deadline: DeploymentDeadline | None = None
) -> Path:
    """Record invocation approval; require one exact confirmation for delete or replace."""

    stage, destructive = validate_plan_review(review)
    approval_deadline = DeploymentDeadline(
        min(600, deadline.remaining() if deadline is not None else 600), clock=time.monotonic
    )

    def approval_seconds(maximum: int = 600) -> int:
        validate_plan_review(review)
        plan_remaining = int(
            (_parse_moment(str(review["expires_at"])) - datetime.now(UTC)).total_seconds()
        )
        remaining = min(plan_remaining, approval_deadline.remaining(maximum))
        if remaining <= 0:
            raise TimeoutError("standalone approval deadline expired; no approval was granted")
        return remaining

    historical_reconciliation = review.get("historical_reconciliation")
    residual_recovery = review.get("residual_recovery")
    operation = (
        str(residual_recovery["operation"])
        if isinstance(residual_recovery, dict)
        else str(historical_reconciliation["operation"])
        if isinstance(historical_reconciliation, dict)
        else stage
    )
    expected = f"{operation}-apply"
    print(json.dumps(review, indent=2, sort_keys=True), file=sys.stderr)
    # Constitution Article 1: the invocation approves a plan; only destruction needs confirmation.
    print(f"Approved by this invocation: {expected}", file=sys.stderr, flush=True)
    if destructive:
        print(
            f"Plan contains {destructive} delete or replacement action(s); type "
            f"{expected}-destructive to approve: ",
            end="",
            file=sys.stderr,
            flush=True,
        )
        confirmation = _approval_input(timeout_seconds=approval_seconds())
        if confirmation != f"{expected}-destructive":
            raise ValueError("standalone destructive application plan approval was denied")
    actor = _azure_actor_digest(str(review["target_binding"]), timeout_seconds=approval_seconds(60))
    approval_deadline.remaining()
    validate_plan_review(review)
    now = datetime.now(UTC).replace(microsecond=0)
    expires = min(_parse_moment(str(review["expires_at"])), now + timedelta(hours=1))
    approval = {
        "schema_version": "fdai.standalone-plan-approval.v1",
        "stage": stage,
        "plan_digest": review["plan_digest"],
        "review_digest": review["review_digest"],
        "target_binding": review["target_binding"],
        "source_commit": review["source_commit"],
        "actor_digest": actor,
        "approved_at": _moment(now),
        "expires_at": _moment(expires),
    }
    path = root / f"{operation}-approval.json"
    path.unlink(missing_ok=True)
    write_private_output(path, json.dumps(approval, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def _approval_input(*, timeout_seconds: int = 600) -> str:
    """Treat a closed input stream as denial, never as approval or an implicit retry."""

    _wait_for_approval_input(timeout_seconds)
    try:
        return input("").strip()
    except EOFError as exc:
        raise ValueError("approval input closed; no new approval was granted") from exc


def _wait_for_approval_input(timeout_seconds: int) -> None:
    """Wait only on a real terminal with the plan and invocation's remaining budget."""

    if timeout_seconds <= 0:
        raise TimeoutError("standalone approval deadline expired; no approval was granted")
    if not sys.stdin.isatty():
        raise ValueError("standalone approval requires an interactive terminal")
    try:
        readable, _, _ = select.select([sys.stdin], [], [], timeout_seconds)
    except (OSError, ValueError):
        raise ValueError("standalone approval input is unavailable") from None
    if not readable:
        raise TimeoutError("standalone approval input timed out; no approval was granted")


def _require_receipt(value: dict[str, Any], stage: str) -> None:
    if (
        value.get("state") != "applied"
        or value.get("stage") != stage
        or value.get("control_plane_readback_verified") is not True
        or not isinstance(value.get("receipt_digest"), str)
        or _DIGEST.fullmatch(str(value["receipt_digest"])) is None
    ):
        raise ValueError(f"standalone {stage} apply receipt is invalid")


def _import_bastion(scripts: Path) -> Any:
    sys.path.insert(0, str(scripts))
    try:
        return importlib.import_module("genesis_bastion")
    finally:
        sys.path.remove(str(scripts))


def _import_entra(scripts: Path) -> Any:
    sys.path.insert(0, str(scripts))
    try:
        return importlib.import_module("genesis_entra")
    finally:
        sys.path.remove(str(scripts))


def _azure_actor_digest(target_binding: str, *, timeout_seconds: int = 60) -> str:
    result = subprocess.run(
        (
            "az",
            "account",
            "show",
            "--query",
            "{subscription_id:id,tenant_id:tenantId,user_name:user.name,user_type:user.type}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("authenticated Azure approval actor is unavailable") from exc
    if not isinstance(value, dict) or result.returncode != 0 or value.get("user_type") != "user":
        raise ValueError("authenticated Azure approval actor is unavailable")
    subscription = value.get("subscription_id")
    tenant = value.get("tenant_id")
    login = value.get("user_name")
    if (
        not isinstance(subscription, str)
        or not isinstance(tenant, str)
        or not isinstance(login, str)
        or not login.strip()
        or compute_target_binding(tenant_id=tenant, subscription_id=subscription) != target_binding
    ):
        raise ValueError("active Azure target does not match the approved plan")
    return hashlib.sha256(f"{target_binding}:{login.casefold()}".encode()).hexdigest()


def _private_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(read_private_bytes(path, max_bytes=4 * 1024 * 1024))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is invalid") from exc
    return _mapping(value, label)


def _replace_private_json(path: Path, value: dict[str, object] | dict[str, str]) -> None:
    temporary = path.parent / f".{path.name}.tmp-{os.getpid()}"
    temporary.unlink(missing_ok=True)
    write_private_output(
        temporary,
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
    )
    os.replace(temporary, path)
    path.chmod(0o600)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} is invalid")
    return {str(key): item for key, item in value.items()}


def _moment(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_moment(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("plan expiry is invalid")
    return result.astimezone(UTC)

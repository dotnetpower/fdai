"""Control standalone managed-host application deployment through Azure Bastion."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import select
import stat
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fdai_deployment_cli.application_state_adoption import ApplicationStateAdoption
from fdai_deployment_cli.bundle import extract_bundle_archive
from fdai_deployment_cli.console_config import configure_console
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.deadline_transport import DeadlineTransport
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.deployment_kit import DeploymentKit, archive_verified_kit
from fdai_deployment_cli.deployment_progress import begin_stage, progress_detail, terminal_output
from fdai_deployment_cli.license import inspect_license
from fdai_deployment_cli.license_issue import (
    discover_license_signing_key,
    issue_deployment_license,
)
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.standalone_review import validate_plan_review
from fdai_deployment_cli.target import compute_target_binding
from fdai_deployment_cli.trust_roots import license_public_key_pem

_DIGEST = re.compile(r"[0-9a-f]{64}")
_SSH_USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}")


def deploy_standalone_application(
    *,
    kit: DeploymentKit,
    prepared: Any,
    foundation_status: dict[str, Any],
    entra_bindings: dict[str, str],
    scripts: Path,
    license_signing_key: Path | None,
    trial_token: Path | None,
    timeout_seconds: int,
    runtime_profile: RuntimeDeploymentProfile | None = None,
    application_state_adoption: ApplicationStateAdoption | None = None,
) -> dict[str, object]:
    """Deploy and independently replan the application without a workflow host."""

    deadline = DeploymentDeadline(timeout_seconds, clock=time.monotonic)
    selected_runtime = runtime_profile or RuntimeDeploymentProfile.create(
        runtime_platform="container-apps",
        database_placement="postgres-flex",
    )
    begin_stage("transfer")
    progress_detail("Verifying the handoff and preparing the signed kit for Bastion transfer")
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
    transport_archive = prepared.root / "standalone-kit.tar.gz"
    archive_digest = archive_verified_kit(kit, transport_archive)
    entra_path = prepared.root / "entra-bindings.json"
    _replace_private_json(entra_path, entra_bindings)
    work_ref = canonical_digest(
        {
            "target_binding": prepared.target_binding,
            "source_commit": prepared.source_commit,
            "kit_manifest_digest": prepared.kit_manifest_digest,
            "runtime_profile_digest": selected_runtime.digest,
        }
    )[:24]
    username = str(runner["admin_username"])
    if _SSH_USER.fullmatch(username) is None:
        raise ValueError("Foundation runner SSH username is invalid")
    remote_root = f"/home/{username}/.fdai-transfer-{work_ref}"
    remote_archive = f"{remote_root}/kit.tar.gz"
    remote_handoff = f"{remote_root}/foundation-handoff.json"
    remote_entra = f"{remote_root}/entra-bindings.json"
    remote_approval = f"{remote_root}/approval.json"
    remote_adoption_state = f"{remote_root}/application-state.json"
    remote_adoption_models = f"{remote_root}/resolved-models.json"
    remote_adoption_descriptor = f"{remote_root}/application-state-adoption.json"
    app_work = f"{remote_root}/application"
    host_alias = (
        "fdai-standalone-"
        + hashlib.sha256(str(runner["vm_id"]).casefold().encode()).hexdigest()[:16]
    )
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
        _prepare_remote(
            tunnel,
            remote_root=remote_root,
            remote_archive=remote_archive,
            archive=transport_archive,
            archive_digest=archive_digest,
            handoff_path=handoff_path,
            remote_handoff=remote_handoff,
            entra_path=entra_path,
            remote_entra=remote_entra,
            app_work=app_work,
            runtime_profile=selected_runtime,
            application_state_adoption=application_state_adoption,
            remote_adoption_state=remote_adoption_state,
            remote_adoption_models=remote_adoption_models,
            remote_adoption_descriptor=remote_adoption_descriptor,
            timeout_seconds=deadline.remaining(),
        )
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
            substrate_plan = _remote_json(
                tunnel,
                remote_root,
                app_work,
                ("plan", "--stage", "substrate"),
                timeout=3600,
            )
            if application_state_adoption is not None:
                _require_nondestructive_adoption_plan(substrate_plan)
            deadline.remaining()
            substrate_approval = _approve_plan(prepared.root, substrate_plan, deadline=deadline)
            tunnel.copy_to(substrate_approval, remote_approval, timeout=120)
            progress_detail("Applying the approved infrastructure plan and verifying its effects")
            substrate_receipt = _remote_json(
                tunnel,
                remote_root,
                app_work,
                ("apply", "--stage", "substrate", "--approval", remote_approval),
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
                runtime_plan = _remote_json(
                    tunnel,
                    remote_root,
                    app_work,
                    ("plan", "--stage", "runtime"),
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
                    ("apply", "--stage", "runtime", "--approval", remote_approval),
                    timeout=7200,
                )
                runtime_approval.unlink(missing_ok=True)
                tunnel.ssh(("rm", "-f", "--", remote_approval), timeout=60)
            _require_receipt(runtime_receipt, "runtime")
        binding_receipt = _remote_json(
            tunnel,
            remote_root,
            app_work,
            ("deployment-binding",),
            timeout=300,
        )
        deployment_binding = str(binding_receipt.get("deployment_binding", ""))
        if (
            binding_receipt.get("terraform_name_verified") is not True
            or re.fullmatch(r"[0-9a-f]{64}", deployment_binding) is None
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
                database_plan = _remote_json(
                    tunnel,
                    remote_root,
                    app_work,
                    ("plan", "--stage", "database"),
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
                    ("apply", "--stage", "database", "--approval", remote_approval),
                    timeout=3600,
                )
                database_approval.unlink(missing_ok=True)
                tunnel.ssh(("rm", "-f", "--", remote_approval), timeout=60)
            _require_receipt(database_receipt, "database")
        begin_stage("capability")
        token = _license_token(
            key=license_signing_key,
            trial_token=trial_token,
            image_digest=core_digest,
            deployment_binding=deployment_binding,
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
            progress_detail("Observation-only mode; no license secret is installed")
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
            application_plan = _remote_json(
                tunnel,
                remote_root,
                app_work,
                ("plan", "--stage", "application"),
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
                ("apply", "--stage", "application", "--approval", remote_approval),
                timeout=7200,
            )
            application_approval.unlink(missing_ok=True)
            tunnel.ssh(("rm", "-f", "--", remote_approval), timeout=60)
        _require_receipt(application_receipt, "application")
        begin_stage("initial-inventory")
        progress_detail("Collecting and independently reading back the initial inventory")
        initial_inventory = _remote_json(
            tunnel,
            remote_root,
            app_work,
            ("initial-inventory",),
            timeout=4200,
        )
        if (
            initial_inventory.get("state") != "inventory-verified"
            or initial_inventory.get("active_generation_readback_verified") is not True
            or initial_inventory.get("progress_persisted") is not True
        ):
            raise ValueError("standalone initial inventory is incomplete")
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
        if selected_runtime.runtime_platform.value == "aks":
            browser_console = _mapping(
                verification.get("browser_console"), "browser Console verification"
            )
            progress_detail("Registering the Console redirect and publishing verified static files")
            entra = _import_entra(scripts)
            redirect_changed = entra.ensure_console_spa_redirect(
                str(entra_bindings["ENTRA_CONSOLE_SPA_CLIENT_ID"]),
                str(browser_console["console_origin"]),
            )
            runtime = kit.runtime.to_mapping()
            console_artifact = _mapping(runtime.get("console"), "runtime Console artifact")
            console_receipt = publish_verified_console(
                console_archive=kit.materialized_root / str(console_artifact["archive"]),
                console_archive_sha256=str(console_artifact["archive_sha256"]),
                bundle_root=kit.bundle_root,
                prepared_root=prepared.root,
                entra_bindings=entra_bindings,
                browser_console=browser_console,
                scripts=scripts,
                subscription_id=str(handoff["subscription_id"]),
                tenant_id=str(handoff["tenant_id"]),
                timeout_seconds=deadline.remaining(),
                redirect_changed=redirect_changed,
            )
        begin_stage("cleanup")
        progress_detail("Removing transient transfers and verifying their absence")
        cleanup = tunnel.ssh(("rm", "-f", "--", remote_archive, remote_approval), timeout=300)
        archive_absent = tunnel.ssh(("test", "!", "-e", remote_archive), timeout=60)
        approval_absent = tunnel.ssh(("test", "!", "-e", remote_approval), timeout=60)
        if any(result.returncode != 0 for result in (cleanup, archive_absent, approval_absent)):
            raise ValueError("standalone remote transient cleanup is incomplete")
    receipt: dict[str, object] = {
        "schema_version": "fdai.standalone-application-terminal-receipt.v2",
        "state": "application-converged",
        "source_commit": prepared.source_commit,
        "target_binding": prepared.target_binding,
        "substrate_receipt_digest": substrate_receipt["receipt_digest"],
        "initial_inventory_receipt_digest": initial_inventory["receipt_digest"],
        "runtime_receipt_digest": (
            runtime_receipt["receipt_digest"]
            if selected_runtime.runtime_platform.value == "aks"
            else ""
        ),
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
        "remote_transient_cleanup_verified": True,
        "application_state_adopted": application_state_adoption is not None,
        "application_state_adoption_descriptor_digest": adoption_descriptor_digest,
        "application_converged": True,
        "browser_access_verified": console_receipt is not None,
        "deployment_ready": True,
        "inventory_ready": True,
        "license_mode": license_mode,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    deadline.remaining()
    _replace_private_json(prepared.root / "standalone-application-receipt.json", receipt)
    return receipt


def _prepare_remote(
    tunnel: Any,
    *,
    remote_root: str,
    remote_archive: str,
    archive: Path,
    archive_digest: str,
    handoff_path: Path,
    remote_handoff: str,
    entra_path: Path,
    remote_entra: str,
    app_work: str,
    runtime_profile: RuntimeDeploymentProfile | None = None,
    application_state_adoption: ApplicationStateAdoption | None = None,
    remote_adoption_state: str = "",
    remote_adoption_models: str = "",
    remote_adoption_descriptor: str = "",
    timeout_seconds: int,
) -> None:
    selected_runtime = runtime_profile or RuntimeDeploymentProfile.create(
        runtime_platform="container-apps",
        database_placement="postgres-flex",
    )
    created = tunnel.ssh(("install", "-d", "-m", "0700", remote_root), timeout=60)
    if created.returncode != 0:
        raise ValueError("standalone remote work directory is unavailable")
    removed = tunnel.ssh(("rm", "-f", "--", remote_archive), timeout=60)
    if removed.returncode != 0:
        raise ValueError("standalone remote archive reset failed")
    tunnel.copy_to(archive, remote_archive, timeout=min(1800, timeout_seconds))
    tunnel.copy_to(handoff_path, remote_handoff, timeout=120)
    tunnel.copy_to(entra_path, remote_entra, timeout=120)
    if application_state_adoption is not None:
        if not all((remote_adoption_state, remote_adoption_models, remote_adoption_descriptor)):
            raise ValueError("standalone application adoption destinations are incomplete")
        tunnel.copy_to(application_state_adoption.state, remote_adoption_state, timeout=300)
        tunnel.copy_to(
            application_state_adoption.resolved_models, remote_adoption_models, timeout=120
        )
        tunnel.copy_to(
            application_state_adoption.descriptor, remote_adoption_descriptor, timeout=120
        )
    digest = tunnel.ssh(("sha256sum", remote_archive), timeout=300)
    if digest.returncode != 0 or digest.stdout.split(maxsplit=1)[0] != archive_digest:
        raise ValueError("standalone transport archive digest differs")
    prepare_arguments = (
        f"{remote_root}/venv/bin/python",
        "-m",
        "fdai_deployment_cli.standalone_host",
        "--work-dir",
        app_work,
        "prepare",
        "--kit",
        f"{remote_root}/kit",
        "--handoff",
        remote_handoff,
        "--entra",
        remote_entra,
        "--runtime-platform",
        selected_runtime.runtime_platform.value,
        "--database-placement",
        selected_runtime.database_placement.value,
        "--system-node-count",
        str(selected_runtime.system_node_count),
        "--system-node-sku",
        selected_runtime.system_node_sku,
        "--user-node-min-count",
        str(selected_runtime.user_node_min_count),
        "--user-node-max-count",
        str(selected_runtime.user_node_max_count),
        "--user-node-sku",
        selected_runtime.user_node_sku,
        *(
            (
                "--adoption-state",
                remote_adoption_state,
                "--adoption-models",
                remote_adoption_models,
                "--adoption-descriptor",
                remote_adoption_descriptor,
            )
            if application_state_adoption is not None
            else ()
        ),
    )
    commands = (
        (("rm", "-rf", "--", f"{remote_root}/kit"), 300),
        (("tar", "-xzf", remote_archive, "-C", remote_root), 1800),
        (("python3", "-m", "venv", f"{remote_root}/venv"), 300),
        (
            (
                f"{remote_root}/venv/bin/pip",
                "install",
                "--no-index",
                "--no-cache-dir",
                "--find-links",
                f"{remote_root}/kit/python",
                "fdai-deployment-cli",
            ),
            900,
        ),
        (("install", "-d", "-m", "0700", app_work), 60),
        (prepare_arguments, 1800),
    )
    for command, limit in commands:
        setup = tunnel.ssh(command, timeout=min(limit, timeout_seconds))
        if setup.returncode != 0:
            raise ValueError("standalone managed-host preparation failed")


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
    """Read two exact confirmations within one bounded window; silence grants nothing."""

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

    expected = f"{stage}-apply"
    print(json.dumps(review, indent=2, sort_keys=True), file=sys.stderr)
    print(
        f"Type the exact stage name to approve ({expected}): ", end="", file=sys.stderr, flush=True
    )
    supplied = _approval_input(timeout_seconds=approval_seconds())
    if supplied != expected:
        raise ValueError("standalone application plan approval was denied")
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
    path = root / f"{stage}-approval.json"
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


def _license_token(
    *,
    key: Path | None,
    trial_token: Path | None,
    image_digest: str,
    deployment_binding: str,
    work_ref: str,
) -> str | None:
    """Return a verified license token or keep an unlicensed deployment observation-only."""

    issuer = discover_license_signing_key(key)
    if issuer is not None:
        return issue_deployment_license(
            private_key=issuer,
            image_digest=image_digest,
            deployment_binding=deployment_binding,
            license_id=f"lic-{work_ref}",
        )
    token_path = trial_token
    if token_path is None:
        return None
    path = token_path if token_path.is_absolute() else Path.cwd() / token_path
    token = read_private_bytes(path, max_bytes=8192).decode("ascii")
    inspect_license(
        token,
        public_key_pem=license_public_key_pem(),
        expected_image_digest=image_digest,
        expected_tenant_binding=deployment_binding,
    )
    return token


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


def publish_verified_console(
    *,
    console_archive: Path,
    console_archive_sha256: str,
    bundle_root: Path,
    prepared_root: Path,
    entra_bindings: dict[str, str],
    browser_console: dict[str, Any],
    scripts: Path,
    subscription_id: str,
    tenant_id: str,
    timeout_seconds: int,
    redirect_changed: bool,
    verify_only: bool = False,
) -> dict[str, object]:
    """Configure a verified prebuilt Console, publish it, and read back exact bytes."""

    _require_archive_digest(console_archive, console_archive_sha256)
    extraction = prepared_root / "console-publish"
    if extraction.exists():
        console_directory = extraction / "dist"
    else:
        console_directory = extract_bundle_archive(console_archive, extraction)
    console_directory.chmod(0o700)
    settings = {
        "schema_version": "fdai.console-runtime.v1",
        "operator_api_base_url": str(browser_console["operator_api_base_url"]),
        "ingestion_api_base_url": str(browser_console["ingestion_api_base_url"]),
        "tenant_id": tenant_id,
        "spa_client_id": str(entra_bindings["ENTRA_CONSOLE_SPA_CLIENT_ID"]),
        "api_scope": str(entra_bindings["ENTRA_CONSOLE_API_SCOPE"]),
    }
    settings_path = prepared_root / "console-runtime-settings.json"
    _replace_private_json(settings_path, settings)
    configured = configure_console(console_directory, settings_path)
    summary = prepared_root / "console-publish-summary.txt"
    if not summary.exists():
        write_private_output(summary, "")
    environment = {
        **os.environ,
        "EXPECTED_AZURE_TENANT_ID": settings["tenant_id"],
        "ENTRA_CONSOLE_SPA_CLIENT_ID": settings["spa_client_id"],
        "ENTRA_CONSOLE_API_SCOPE": settings["api_scope"],
        "ARM_SUBSCRIPTION_ID": subscription_id,
        "CONSOLE_DEFAULT_HOSTNAME": str(browser_console["console_hostname"]),
        "CONSOLE_STATIC_WEB_APP_ID": str(browser_console["console_static_web_app_id"]),
        "BROWSER_GATEWAY_OPERATOR_URL": settings["operator_api_base_url"],
        "BROWSER_GATEWAY_INGESTION_URL": settings["ingestion_api_base_url"],
        "CONSOLE_PREBUILT_DIRECTORY": str(console_directory),
        "FDAI_CONSOLE_VERIFY_ONLY": "1" if verify_only else "0",
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    completed = subprocess.run(
        (
            "/bin/bash",
            str(scripts / "publish-console.sh"),
            str(bundle_root / "infra/runtimes/aks/workloads"),
        ),
        cwd=bundle_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise ValueError("prebuilt Console publication or browser verification failed")
    receipt: dict[str, object] = {
        "schema_version": "fdai.standalone-console-publication.v1",
        "state": "verified" if verify_only else "published",
        "console_origin": browser_console["console_origin"],
        "console_archive_sha256": console_archive_sha256,
        "runtime_config_digest": configured["runtime_config_digest"],
        "entra_redirect_changed": redirect_changed,
        "artifact_hash_verified": True,
        "spa_fallback_verified": True,
        "api_health_verified": True,
        "authorization_preflight_verified": True,
        "unauthenticated_denial_verified": True,
        "entra_redirect_verified": True,
        "mutation_performed": not verify_only,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    _replace_private_json(prepared_root / "console-publication-receipt.json", receipt)
    return receipt


def _require_archive_digest(path: Path, expected_digest: str) -> None:
    """Recheck one no-follow regular archive immediately before it is consumed."""

    if _DIGEST.fullmatch(expected_digest) is None:
        raise ValueError("Console archive digest is invalid")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Console archive is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            observed = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("Console archive changed while it was read")
        if observed != expected_digest:
            raise ValueError("Console archive digest does not match the signed release")
    finally:
        os.close(descriptor)


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
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("plan expiry is invalid")
    return result.astimezone(UTC)

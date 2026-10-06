"""Execute standalone application checkpoints on the Bastion-reachable managed host."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlencode

from fdai_service_contracts.product_profile import ObservationDataSource, ProductAddOn

from fdai_deployment_cli import (
    aks_readiness,
    catalog_review_profile,
    source_application_inputs,
    standalone_host_values,
    standalone_planned_outputs,
    standalone_terraform_environment,
)
from fdai_deployment_cli import foundation_adoption_host as foundation_host
from fdai_deployment_cli import operational_evidence_verifier_input as oev
from fdai_deployment_cli.aks_historical_reconciliation import (
    reconciled_variables,
    secret_binding_reordered,
    validate_reconciliation_plan,
)
from fdai_deployment_cli.aks_service_update import (
    SERVICES as AKS_SERVICES,
)
from fdai_deployment_cli.aks_service_update import (
    deployment_snapshot,
    peers_unchanged,
    validate_plan_scope,
    validate_update_request,
)
from fdai_deployment_cli.aks_workload_jobs import (
    aks_kubernetes_direct_api_environment as _aks_kubernetes_direct_api_environment,
)
from fdai_deployment_cli.aks_workload_jobs import (
    prepare_aks_scheduled_jobs as _prepare_aks_scheduled_jobs,
)
from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.deployment_kit import acquire_deployment_kit
from fdai_deployment_cli.oci_archive import validate_oci_archive
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.runtime_profile import (
    RuntimeDeploymentProfile,
    legacy_full_product_matches,
    legacy_runtime_profile_digest,
)
from fdai_deployment_cli.runtime_support_installation import (
    install_runtime_support as _install_runtime_support,
)
from fdai_deployment_cli.standalone_aks_inventory import (
    initial_inventory_binding as _initial_inventory_binding,
)
from fdai_deployment_cli.standalone_aks_inventory import (
    run_initial_aks_inventory as _initial_aks_inventory,
)
from fdai_deployment_cli.standalone_aks_nodepool_guard import (
    guard_existing_runtime_node_pools as _guard_existing_runtime_node_pools,
)
from fdai_deployment_cli.standalone_catalog_review import run_catalog_review
from fdai_deployment_cli.standalone_checkpoint_failure import (
    failure_record as _failure_record,
)
from fdai_deployment_cli.standalone_checkpoint_failure import (
    terraform_failure as _terraform_failure,
)
from fdai_deployment_cli.standalone_host_state import (
    absolute as _absolute,
)
from fdai_deployment_cli.standalone_host_state import (
    acquire_checkpoint_lock as _acquire_checkpoint_lock,
)
from fdai_deployment_cli.standalone_host_state import (
    executable_digest as _executable_digest,
)
from fdai_deployment_cli.standalone_host_state import (
    file_digest as _file_digest,
)
from fdai_deployment_cli.standalone_host_state import (
    moment as _moment,
)
from fdai_deployment_cli.standalone_host_state import (
    parse_moment as _parse_moment,
)
from fdai_deployment_cli.standalone_host_state import (
    private_directory as _private_directory,
)
from fdai_deployment_cli.standalone_host_state import (
    private_json as _private_json,
)
from fdai_deployment_cli.standalone_host_state import (
    replace_or_verify_private_json as _replace_or_verify_private_json,
)
from fdai_deployment_cli.standalone_host_state import (
    replace_private_json as _replace_private_json,
)
from fdai_deployment_cli.standalone_host_values import (
    AKS_CORE_STARTUP_READINESS,
    aks_operator_environment,
    aks_operator_request_receipts,
)
from fdai_deployment_cli.standalone_host_values import (
    console_origin as _console_origin,
)
from fdai_deployment_cli.standalone_host_values import (
    foundation_application_workload as _foundation_application_workload,
)
from fdai_deployment_cli.standalone_host_values import (
    foundation_binding_digest as _foundation_binding_digest,
)
from fdai_deployment_cli.standalone_host_values import (
    plan_summary as _plan_summary,
)
from fdai_deployment_cli.standalone_host_values import (
    required_image_digest as _required_image_digest,
)
from fdai_deployment_cli.standalone_host_values import (
    vault_name as _vault_name,
)
from fdai_deployment_cli.standalone_license_installation import (
    aks_license_environment,
    install_license,
)
from fdai_deployment_cli.standalone_management_egress import management_egress_cidrs
from fdai_deployment_cli.standalone_migration_evidence import verify_service_evidence
from fdai_deployment_cli.standalone_operational_evidence import (
    add_aks_operational_evidence_verifier_workload as _add_aks_operational_evidence_verifier_workload,
)
from fdai_deployment_cli.standalone_operational_evidence import aks_workload as _aks_workload
from fdai_deployment_cli.standalone_operational_evidence import (
    runtime_principal_ids_with_operational_evidence_verifier as _runtime_principal_ids,
)
from fdai_deployment_cli.standalone_product_profile import (
    context_selects_add_on as _selects_add_on,
)
from fdai_deployment_cli.standalone_product_profile import product_terraform_values
from fdai_deployment_cli.standalone_residual_apply import (
    apply_residual_plan as _apply_residual_plan,
)
from fdai_deployment_cli.standalone_residual_apply import (
    prepare_residual_review as _prepare_residual_review,
)
from fdai_deployment_cli.standalone_residual_apply import (
    recover_residual_apply as _recover_residual_apply,
)
from fdai_deployment_cli.standalone_residual_apply import (
    residual_claim_exists as _residual_claim_exists,
)
from fdai_deployment_cli.standalone_residual_apply import (
    seal_terraform_plan as _seal_terraform_plan,
)
from fdai_deployment_cli.standalone_stage_targets import (
    database_placement as _database_placement,
)
from fdai_deployment_cli.standalone_stage_targets import (
    focused_private_access as _focused_private_access,
)
from fdai_deployment_cli.standalone_stage_targets import (
    not_required_recovery as _not_required_recovery,
)
from fdai_deployment_cli.standalone_stage_targets import (
    operation_targets as _operation_targets,
)
from fdai_deployment_cli.standalone_stage_targets import (
    reconcile_retained_private_access as _reconcile_retained_private_access,
)
from fdai_deployment_cli.standalone_stage_targets import (
    runtime_operation as _runtime_operation,
)
from fdai_deployment_cli.standalone_stage_targets import (
    stage_targets as _stage_targets,
)
from fdai_deployment_cli.standalone_terraform_environment import (
    configure_terraform as _configure_terraform,
)
from fdai_deployment_cli.standalone_terraform_environment import (
    terraform_configuration as _terraform_configuration,
)
from fdai_deployment_cli.standalone_trial_activation import (
    activate_trial,
    deployment_binding_digest,
)
from fdai_deployment_cli.target import compute_target_binding

_DIGEST = re.compile(r"[0-9a-f]{64}")
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_SOURCE_COMMIT = re.compile(r"[0-9a-f]{40}")
_AKS_RUNTIME_NAMESPACE = "fdai-runtime"
_STAGES: Final = ("access", "substrate", "runtime", "database", "application")


def main(argv: list[str] | None = None) -> int:
    """Run one remote checkpoint with an owner-only umask and emit only sanitized JSON."""

    os.umask(0o077)
    parser = argparse.ArgumentParser(prog="python -m fdai_deployment_cli.standalone_host")
    parser.add_argument("--work-dir", type=Path, required=True)
    subcommands = parser.add_subparsers(required=True)
    source_runtime = subcommands.add_parser("verify-source-runtime")
    source_runtime.add_argument("--source-snapshot", type=Path, required=True)
    source_runtime.add_argument("--snapshot-digest", required=True)
    source_runtime.add_argument("--runtime-root", type=Path, required=True)
    source_runtime.add_argument("--runtime-digest", required=True)
    source_runtime.add_argument("--deployment-bundle", type=Path, required=True)
    source_runtime.add_argument("--bundle-digest", required=True)
    source_runtime.add_argument("--platform-tag", required=True)
    source_runtime.set_defaults(handler=_verify_source_runtime, read_only=True)

    prepare = subcommands.add_parser("prepare")
    prepare.add_argument("--kit", type=Path, required=True)
    prepare.add_argument("--handoff", type=Path, required=True)
    prepare.add_argument("--entra", type=Path)
    prepare.add_argument("--foundation-adoption", type=Path)
    prepare.add_argument("--adoption-state", type=Path)
    prepare.add_argument("--adoption-models", type=Path)
    prepare.add_argument("--adoption-descriptor", type=Path)
    prepare.add_argument("--catalog-review-profile", type=Path)
    prepare.add_argument("--catalog-review-private-key", type=Path)
    prepare.add_argument("--operational-evidence-verifier-input", type=Path)
    prepare.add_argument("--runtime-platform", default="aks")
    prepare.add_argument("--database-placement", default="postgres-flex")
    prepare.add_argument("--system-node-count", type=int, default=3)
    prepare.add_argument("--system-node-sku", default=None)
    prepare.add_argument("--user-node-min-count", type=int, default=3)
    prepare.add_argument("--user-node-max-count", type=int, default=5)
    prepare.add_argument("--user-node-sku", default="Standard_D4as_v5")
    prepare.add_argument("--database-sku")
    prepare.add_argument(
        "--product-add-on",
        action="append",
        choices=tuple(item.value for item in ProductAddOn),
        default=[],
    )
    prepare.add_argument(
        "--observation-source",
        action="append",
        choices=tuple(item.value for item in ObservationDataSource),
        default=[],
    )
    prepare.set_defaults(handler=_prepare)

    source_application_inputs.add_prepare_source_parser(subcommands, _prepare)

    prepare_runtime = subcommands.add_parser("prepare-runtime")
    prepare_runtime.set_defaults(handler=_prepare_runtime)

    prepare_database = subcommands.add_parser("prepare-database")
    prepare_database.set_defaults(handler=_prepare_database)

    prepare_application = subcommands.add_parser("prepare-application")
    prepare_application.set_defaults(handler=_prepare_aks_application)

    prepare_service_update = subcommands.add_parser("prepare-service-update")
    prepare_service_update.add_argument("--service", choices=sorted(AKS_SERVICES), required=True)
    prepare_service_update.add_argument("--image", required=True)
    prepare_service_update.add_argument("--source-commit", required=True)
    prepare_service_update.set_defaults(handler=_prepare_aks_service_update)

    adopt_historical = subcommands.add_parser("adopt-historical-aks-application")
    adopt_historical.add_argument("--binding", type=Path, required=True)
    adopt_historical.add_argument("--state", type=Path, required=True)
    adopt_historical.add_argument("--variables", type=Path, required=True)
    adopt_historical.add_argument("--live", type=Path, required=True)
    adopt_historical.add_argument("--plan", type=Path, required=True)
    adopt_historical.set_defaults(handler=_adopt_historical_aks_application)

    apply_historical = subcommands.add_parser("apply-historical-aks-reconciliation")
    apply_historical.add_argument("--approval", type=Path, required=True)
    apply_historical.set_defaults(handler=_apply_historical_aks_reconciliation)

    recover_historical = subcommands.add_parser("recover-historical-aks-reconciliation")
    recover_historical.set_defaults(handler=_recover_historical_aks_reconciliation)

    plan = subcommands.add_parser("plan")
    plan.add_argument("--stage", choices=_STAGES, required=True)
    plan.add_argument("--service", choices=sorted(AKS_SERVICES))
    plan.set_defaults(handler=_plan)

    apply = subcommands.add_parser("apply")
    apply.add_argument("--stage", choices=_STAGES, required=True)
    apply.add_argument("--service", choices=sorted(AKS_SERVICES))
    apply.add_argument("--approval", type=Path, required=True)
    apply.set_defaults(handler=_apply)

    apply_residual = subcommands.add_parser("apply-residual")
    apply_residual.add_argument("--stage", choices=_STAGES, required=True)
    apply_residual.add_argument("--approval", type=Path, required=True)
    apply_residual.set_defaults(handler=_apply_residual)

    recover = subcommands.add_parser("recover-apply")
    recover.add_argument("--stage", choices=_STAGES, required=True)
    recover.add_argument("--service", choices=sorted(AKS_SERVICES))
    recover.set_defaults(handler=_recover_apply)

    images = subcommands.add_parser("import-images")
    images.set_defaults(handler=_import_images)

    source_image = subcommands.add_parser("import-source-image")
    source_image.add_argument("--service", choices=sorted(AKS_SERVICES), required=True)
    source_image.add_argument("--archive", type=Path, required=True)
    source_image.add_argument("--archive-sha256", required=True)
    source_image.add_argument("--image-digest", required=True)
    source_image.add_argument("--source-commit", required=True)
    source_image.add_argument("--approval", type=Path, required=True)
    source_image.set_defaults(handler=_import_source_service_image)

    update_context = subcommands.add_parser("service-update-context")
    update_context.add_argument("--service", choices=sorted(AKS_SERVICES), required=True)
    update_context.set_defaults(handler=_service_update_context, read_only=True)

    binding = subcommands.add_parser("deployment-binding")
    binding.set_defaults(handler=_deployment_binding)

    migrate = subcommands.add_parser("migrate")
    migrate.set_defaults(handler=_migrate)

    subcommands.add_parser("activate-trial").set_defaults(handler=_activate_trial)

    initial_inventory = subcommands.add_parser("initial-inventory")
    initial_inventory.set_defaults(handler=_initial_inventory)

    catalog_review = subcommands.add_parser("catalog-review")
    catalog_review.set_defaults(handler=_catalog_review)

    license_command = subcommands.add_parser("install-license")
    license_command.add_argument("--image-digest", required=True)
    license_command.add_argument("--deployment-binding", required=True)
    license_command.add_argument("--installation-binding", default=None)
    license_command.set_defaults(handler=_install_license)

    verify = subcommands.add_parser("verify")
    verify.set_defaults(handler=_verify)

    args = parser.parse_args(argv)
    lock_descriptor: int | None = None
    try:
        work_dir = _absolute(args.work_dir)
        if not getattr(args, "read_only", False):
            _private_directory(work_dir)
            lock_descriptor = _acquire_checkpoint_lock(work_dir)
        result = args.handler(args, work_dir)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(
            json.dumps(
                _failure_record(exc),
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 3
    finally:
        if lock_descriptor is not None:
            os.close(lock_descriptor)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


def _verify_source_runtime(args: argparse.Namespace, _work_dir: Path) -> dict[str, object]:
    from fdai_deployment_cli.source_runtime import verify_source_runtime

    return verify_source_runtime(
        snapshot=_absolute(args.source_snapshot),
        snapshot_digest=args.snapshot_digest,
        runtime_root=_absolute(args.runtime_root),
        runtime_digest=args.runtime_digest,
        deployment_bundle=_absolute(args.deployment_bundle),
        bundle_digest=args.bundle_digest,
        platform_tag=args.platform_tag,
    )


def _prepare(args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    _private_directory(work_dir)
    handoff = _private_json(_absolute(args.handoff), "Foundation handoff")
    runtime_profile = RuntimeDeploymentProfile.from_prepare_arguments(args)
    enterprise_identity_selected = runtime_profile.product_profile.selects(
        ProductAddOn.ENTERPRISE_IDENTITY_GOVERNANCE
    )
    if enterprise_identity_selected and args.entra is None:
        raise ValueError("enterprise identity governance requires Entra bindings")
    if not enterprise_identity_selected and args.entra is not None:
        raise ValueError("Entra bindings require enterprise identity governance")
    entra = _private_json(_absolute(args.entra), "Entra bindings") if args.entra is not None else {}
    runner = _mapping(handoff.get("runner"), "Foundation runner")
    state = _mapping(handoff.get("state"), "Foundation state")
    ops = _mapping(handoff.get("ops"), "Foundation operations")
    app = _mapping(handoff.get("app_resource_group"), "Foundation application group")
    foundation = foundation_host.load_foundation_host_context(
        _absolute(args.foundation_adoption) if args.foundation_adoption is not None else None,
        handoff=handoff,
        runner=runner,
    )
    initial_inventory_binding = _initial_inventory_binding(foundation.subscription_id)
    foundation_binding_digest = _foundation_binding_digest(
        handoff,
        runner=runner,
        state=state,
        ops=ops,
        app=app,
    )
    entra_binding_digest = canonical_digest(entra) if enterprise_identity_selected else None
    adoption = _application_state_adoption(args)
    adoption_digest = canonical_digest(adoption[0]) if adoption is not None else ""
    catalog_profile_path = getattr(args, "catalog_review_profile", None)
    catalog_key_path = getattr(args, "catalog_review_private_key", None)
    catalog_profile = catalog_review_profile.staged_catalog_review_profile_from_paths(
        _absolute(catalog_profile_path) if catalog_profile_path else None,
        _absolute(catalog_key_path) if catalog_key_path else None,
    )
    verifier_input_path = getattr(args, "operational_evidence_verifier_input", None)
    verifier_input = oev.staged_operational_evidence_verifier_input_from_path(
        _absolute(verifier_input_path) if verifier_input_path else None
    )
    verifier_input_digest = verifier_input.input_digest if verifier_input is not None else ""
    foundation.login(_managed_identity_login, work_dir)
    suffix = (
        str(adoption[0]["resource_name_suffix"])
        if adoption is not None
        else hashlib.sha256(str(handoff["run_digest"]).encode()).hexdigest()[:6]
    )
    region = str(handoff["region"])
    region_short = str(handoff["region_short"])
    workload = _foundation_application_workload(
        app,
        environment="dev",
        region_short=region_short,
    )
    key_vault_name = standalone_host_values.planned_key_vault_name(
        workload=workload,
        environment="dev",
        region_short=region_short,
        resource_suffix=suffix,
    )
    document_storage_account_name = standalone_host_values.planned_document_storage_name(
        subscription_id=foundation.subscription_id,
        workload=workload,
        environment="dev",
        region_short=region_short,
    )
    key_vault_private_access = (
        runtime_profile.runtime_platform.value == "aks"
        and standalone_terraform_environment.requires_aks_key_vault_private_access(
            subscription_id=foundation.subscription_id,
            resource_group_name=str(app["name"]),
            vault_name=key_vault_name,
            work_dir=work_dir,
        )
    )
    document_storage_private_access = (
        runtime_profile.runtime_platform.value == "aks"
        and standalone_terraform_environment.requires_aks_document_storage_private_access(
            subscription_id=foundation.subscription_id,
            resource_group_name=str(app["name"]),
            account_name=document_storage_account_name,
            work_dir=work_dir,
        )
    )
    retained_context = work_dir / "context.json"
    retained_variables = work_dir / "application.auto.tfvars.json"
    if retained_context.exists() or retained_variables.exists():
        if not retained_context.exists() or not retained_variables.exists():
            raise ValueError("standalone host preparation is incomplete")
        retained = _private_json(retained_context, "standalone host context")
        retained_values = _private_json(retained_variables, "standalone host Terraform variables")
        posture_changed = _reconcile_retained_private_access(
            retained, retained_values, key_vault_private_access, document_storage_private_access
        )
        if (
            retained.get("subscription_id") != foundation.subscription_id
            or retained.get("tenant_id") != foundation.tenant_id
            or retained.get("client_id") != foundation.client_id
            or retained.get("principal_id") != foundation.principal_id
            or retained.get("foundation_binding_digest") != foundation_binding_digest
            or retained.get("entra_binding_digest") != entra_binding_digest
            or retained.get("application_state_adoption_digest", "") != adoption_digest
            or retained.get("catalog_review_profile_digest") != catalog_profile.profile_digest
            or retained.get("oev_input_digest", "") != verifier_input_digest
            or retained.get("initial_inventory_binding") != initial_inventory_binding
            or retained.get("key_vault_name") != key_vault_name
            or retained.get("document_storage_account_name") != document_storage_account_name
            or not _runtime_profile_matches(retained, runtime_profile)
        ):
            raise ValueError("standalone host retained context differs")
        if posture_changed:
            _replace_private_json(retained_context, retained)
            _replace_private_json(retained_variables, retained_values)
        foundation.adoption.require_context(retained)
        if source_application_inputs.rebind_source_tree(retained, work_dir):
            _replace_private_json(retained_context, retained)
        _terraform_init(work_dir, retained)
        if adoption is not None:
            _adopt_application_state(work_dir, retained, *adoption)
        return {
            "schema_version": "fdai.standalone-host-prepare.v1",
            "state": "prepared",
            "source_commit": retained["source_commit"],
            "kit_manifest_digest": retained["kit_manifest_digest"],
            "runtime_release_digest": retained["runtime_release_digest"],
            "runtime_profile_digest": runtime_profile.digest,
            "focused_private_access": _focused_private_access(retained),
            "mutation_performed": False,
            "subscription_ready": False,
        }
    source_mode = hasattr(args, "source_snapshot")
    if source_mode:
        source_snapshot = _absolute(args.source_snapshot)
        source_artifacts = source_application_inputs.source_host_artifacts(
            source_snapshot=source_snapshot,
            snapshot_digest=str(args.source_snapshot_digest),
            expected_source_commit=foundation.adoption.source_commit,
            work_dir=work_dir,
            runtime_requirements=_absolute(args.runtime_requirements),
            runtime_requirements_digest=str(args.runtime_requirements_digest),
        )
        source_commit = source_artifacts.source_commit
        infra = source_artifacts.infra
        terraform = source_artifacts.terraform
        provider_mirror: Path | None = None
        runtime_release_digest = source_artifacts.digest
        kit_manifest_digest = source_artifacts.digest
        kit_bin = source_artifacts.kit_bin
        provider_installation = "direct"
    else:
        kit_work = work_dir / "kit-work"
        _private_directory(kit_work)
        kit = acquire_deployment_kit(
            work_dir=kit_work,
            online=False,
            offline_kit=_absolute(args.kit),
        )
        foundation.adoption.require_kit(kit)
        _install_runtime_support(
            work_dir,
            artifact_root=kit.materialized_root,
            kit_manifest_digest=kit.verification.manifest_digest,
        )
        infra = kit.bundle_root / "infra"
        terraform = kit.materialized_root / kit.verification.terraform_binary
        provider_mirror = kit.materialized_root / kit.verification.provider_mirror_prefix
        runtime = kit.runtime.to_mapping()
        runtime_release_digest = kit.runtime.digest
        kit_manifest_digest = kit.verification.manifest_digest
        source_commit = kit.source_commit
        kit_bin = kit.materialized_root / "bin"
        provider_installation = "filesystem_mirror"
    terraform_config = work_dir / "terraform.rc"
    expected_terraform_config = source_application_inputs.terraform_configuration(
        source_mode=source_mode, provider_mirror=provider_mirror
    )
    if not terraform_config.exists():
        write_private_output(terraform_config, expected_terraform_config)
    elif (
        read_private_bytes(terraform_config, max_bytes=16_384).decode("utf-8")
        != expected_terraform_config
    ):
        raise ValueError("retained Terraform provider configuration differs")
    _ensure_backend(infra)
    registry = standalone_host_values.planned_container_registry_name(
        workload=workload, environment="dev", region_short=region_short, resource_suffix=suffix
    )
    login_server = f"{registry}.azurecr.io"
    if source_mode:
        refs = source_application_inputs.placeholder_image_refs(login_server, include_pgvector=True)
    else:
        services = _mapping(runtime.get("services"), "runtime services")
        sidecars = _mapping(runtime.get("sidecars"), "runtime sidecars")
        refs = {
            name: f"{login_server}/{name}@{_required_image_digest(services, name)}"
            for name in (
                "core-control-plane",
                "operator-service",
                "document-ingestion-api",
                "document-processing-worker",
                "isolated-executor",
            )
        }
        refs["clamav"] = f"{login_server}/clamav@{_required_image_digest(sidecars, 'clamav')}"
        if runtime_profile.database_placement.value == "postgres-aks":
            refs["pgvector"] = (
                f"{login_server}/pgvector@{_required_image_digest(sidecars, 'pgvector')}"
            )
    aks_baseline = runtime_profile.runtime_platform.value == "aks"
    values: dict[str, object] = {
        "workload": workload,
        "env": "dev",
        "region": region,
        "region_short": region_short,
        "tenant_id": foundation.tenant_id,
        "deploy_runner_principal_id": foundation.principal_id,
        "postgres_admin_login": "fdaiadmin",
        "generate_initial_postgres_password": True,
        "resource_name_suffix": suffix,
        "foundation_resource_group_context_digest": str(app["foundation_context_digest"]),
        "enable_private_networking": not aks_baseline,
        # The AKS baseline has no archive private endpoint; policy-private storage would drift.
        "enable_operational_history": not aks_baseline,
        "enable_aks_key_vault_private_access": key_vault_private_access,
        "enable_aks_document_storage_private_access": document_storage_private_access,
        "compute_kind": (
            "aks" if runtime_profile.runtime_platform.value == "aks" else "container_apps"
        ),
        "state_store_kind": (
            "postgres_aks"
            if runtime_profile.database_placement.value == "postgres-aks"
            else "postgres_flex"
        ),
        "enable_private_postgres": False,
        "runner_vnet_id": str(ops["vnet_id"]),
        "runner_vnet_name": str(ops["vnet_name"]),
        "ops_resource_group_name": str(ops["resource_group_name"]),
        "acr_sku": "Basic" if aks_baseline else "Premium",
        "core_image": refs["core-control-plane"],
        "operator_api_image": refs["operator-service"],
        "operator_api_migration_image": refs["operator-service"],
        "ingestion_image": refs["document-ingestion-api"],
        "ingestion_migration_image": refs["document-ingestion-api"],
        "clamav_image": refs["clamav"],
        "ingestion_cohost_worker": False,
        "ingestion_cors_allow_origins": "https://localhost",
        "enable_llm": adoption is not None,
    }
    values.update(
        product_terraform_values(
            runtime_profile,
            entra,
            require_guid=_required_guid,
        )
    )
    values.update(catalog_review_profile.catalog_review_terraform_values(catalog_profile))
    oev.apply_operational_evidence_verifier_input(values, verifier_input)
    if adoption is not None:
        values.update(
            resolved_capabilities=adoption[0]["resolved_capabilities"],
            resolved_models_json=read_private_bytes(adoption[2], max_bytes=8 * 1024 * 1024).decode(
                "utf-8"
            ),
            resolved_models_sha256=adoption[0]["resolved_models_sha256"],
        )
    context: dict[str, object] = {
        "source_commit": source_commit,
        "artifact_source": "operator-selected-source" if source_mode else "signed-kit",
        "target_binding": foundation.target_binding,
        "foundation_adoption_digest": foundation.adoption.digest,
        "subscription_id": foundation.subscription_id,
        "tenant_id": foundation.tenant_id,
        "client_id": foundation.client_id,
        "principal_id": foundation.principal_id,
        "foundation_binding_digest": foundation_binding_digest,
        "key_vault_private_access": key_vault_private_access,
        "key_vault_name": key_vault_name,
        "document_storage_private_access": document_storage_private_access,
        "document_storage_account_name": document_storage_account_name,
        "entra_binding_digest": entra_binding_digest,
        "application_state_adoption_digest": adoption_digest,
        "catalog_review_profile_digest": catalog_profile.profile_digest,
        "catalog_review_selected": catalog_profile.selected,
        "oev_input_digest": verifier_input_digest,
        "state_resource_group": str(ops["resource_group_name"]),
        "state_account": str(state["account_name"]),
        "state_container": str(state["container_name"]),
        "inventory_progress_container_url": str(state["progress_container_url"]),
        "initial_inventory_binding": initial_inventory_binding,
        "state_key": f"fdai-{values['env']}.tfstate",
        "kit_manifest_digest": kit_manifest_digest,
        "runtime_release_digest": runtime_release_digest,
        "runtime_profile": runtime_profile.to_mapping(),
        "runtime_profile_digest": runtime_profile.digest,
        "registry_name": registry,
        "registry_login_server": login_server,
        "image_refs": refs,
        "infra": str(infra),
        "terraform": str(terraform),
        "provider_mirror": "" if provider_mirror is None else str(provider_mirror),
        "provider_installation": provider_installation,
        "kit_bin": str(kit_bin),
        "terraform_config": str(terraform_config),
        "terraform_data": str(work_dir / "terraform-data"),
    }
    if source_mode:
        context.update(
            source_snapshot=str(source_snapshot), source_snapshot_digest=source_artifacts.digest
        )
    _replace_private_json(work_dir / "application.auto.tfvars.json", values)
    _replace_private_json(work_dir / "context.json", context)
    _terraform_init(work_dir, context)
    if adoption is not None:
        _adopt_application_state(work_dir, context, *adoption)
    return {
        "schema_version": "fdai.standalone-host-prepare.v1",
        "state": "prepared",
        "source_commit": source_commit,
        "kit_manifest_digest": kit_manifest_digest,
        "runtime_release_digest": runtime_release_digest,
        "runtime_profile_digest": runtime_profile.digest,
        "application_state_adopted": adoption is not None,
        "focused_private_access": _focused_private_access(context),
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _prepare_runtime(_args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    context = _private_json(work_dir / "context.json", "standalone host context")
    if _runtime_platform(context) != "aks":
        raise ValueError("runtime preparation is only valid for AKS")
    if not (work_dir / "substrate-receipt.json").is_file():
        raise ValueError("runtime preparation requires the applied substrate plan")
    _managed_identity_login_from_context(context, work_dir)
    substrate = Path(str(context["infra"]))
    profile = _mapping(context.get("runtime_profile"), "runtime deployment profile")
    application_values = _private_json(
        work_dir / "application.auto.tfvars.json", "application variables"
    )
    runtime_infra = substrate / "runtimes/aks/cluster"
    values = {
        "location": application_values["region"],
        "resource_group_name": _terraform_output(substrate, "resource_group_name"),
        "aks_subnet_id": _terraform_output(substrate, "aks_subnet_id"),
        "aks_api_server_subnet_id": _terraform_output(substrate, "aks_api_server_subnet_id"),
        "api_server_authorized_ip_ranges": management_egress_cidrs(context, cwd=work_dir),
        "container_registry_id": _terraform_output(substrate, "container_registry_id"),
        "log_analytics_workspace_id": _terraform_output(substrate, "log_workspace_id"),
        "managed_host_principal_id": context["principal_id"],
        "environment": application_values["env"],
        "region_short": application_values["region_short"],
        "database_placement": profile["database_placement"],
        "system_node_count": profile["system_node_count"],
        "system_node_sku": profile["system_node_sku"],
        "user_node_min_count": profile["user_node_min_count"],
        "user_node_max_count": profile["user_node_max_count"],
        "user_node_sku": profile["user_node_sku"],
        "tags": {"fdai:runtime": "aks"},
    }
    context.update(
        runtime_infra=str(runtime_infra),
        runtime_state_key=f"fdai-{application_values['env']}-aks-cluster.tfstate",
        runtime_terraform_data=str(work_dir / "terraform-data-runtime"),
        resource_group_name=values["resource_group_name"],
    )
    _replace_or_verify_private_json(work_dir / "runtime.auto.tfvars.json", values)
    _replace_private_json(work_dir / "context.json", context)
    _initialize_terraform_stage("runtime", context, work_dir)
    return {
        "schema_version": "fdai.standalone-runtime-prepare.v1",
        "state": "prepared",
        "runtime_profile_digest": _runtime_profile_digest(context),
        "state_key": context["runtime_state_key"],
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _prepare_database(_args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    context = _private_json(work_dir / "context.json", "standalone host context")
    profile = _mapping(context.get("runtime_profile"), "runtime deployment profile")
    if _runtime_platform(context) != "aks" or profile.get("database_placement") != "postgres-aks":
        raise ValueError("database preparation is only valid for postgres-aks")
    for prerequisite in ("runtime-receipt.json", "image-import-receipt.json"):
        if not (work_dir / prerequisite).is_file():
            raise ValueError("database preparation prerequisites are incomplete")
    _managed_identity_login_from_context(context, work_dir)
    substrate = Path(str(context["infra"]))
    identities = _terraform_json_output(substrate, "runtime_identity_bindings")
    if not isinstance(identities, dict):
        raise TypeError("AKS runtime identity output contract is invalid")
    principals = _runtime_principal_ids(identities, ("core", "operator", "executor", "inventory"))
    ingestion_identity = _mapping(identities.get("ingestion"), "ingestion runtime identity")
    ingestion_worker_identity = _mapping(
        identities.get("ingestion_worker"), "ingestion worker runtime identity"
    )
    key_vault_id = _terraform_output(substrate, "key_vault_id")
    _activate_terraform_stage("runtime", context, work_dir)
    runtime_infra = Path(str(context["runtime_infra"]))
    cluster_name = _terraform_output(runtime_infra, "cluster_name")
    kubeconfig = _prepare_aks_kubeconfig(
        context,
        work_dir,
        resource_group=str(context["resource_group_name"]),
        cluster_name=cluster_name,
    )
    application_values = _private_json(
        work_dir / "application.auto.tfvars.json", "application variables"
    )
    refs = _mapping(context.get("image_refs"), "runtime image references")
    database_infra = substrate / "runtimes/aks/database"
    values = {
        "kubeconfig_path": str(kubeconfig),
        "image": refs["pgvector"],
        "key_vault_id": key_vault_id,
        "runtime_principal_ids": sorted(principals),
        "ingestion_api_principal_id": str(ingestion_identity["principal_id"]),
        "ingestion_worker_principal_id": str(ingestion_worker_identity["principal_id"]),
        "tags": {"fdai:runtime": "aks", "fdai:database-placement": "postgres-aks"},
    }
    context.update(
        database_infra=str(database_infra),
        database_state_key=f"fdai-{application_values['env']}-aks-database.tfstate",
        database_terraform_data=str(work_dir / "terraform-data-database"),
        kubeconfig=str(kubeconfig),
    )
    _replace_or_verify_private_json(work_dir / "database.auto.tfvars.json", values)
    _replace_private_json(work_dir / "context.json", context)
    _initialize_terraform_stage("database", context, work_dir)
    return {
        "schema_version": "fdai.standalone-database-prepare.v1",
        "state": "prepared",
        "runtime_profile_digest": _runtime_profile_digest(context),
        "state_key": context["database_state_key"],
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _aks_core_conversation_environment(
    *,
    application_values: dict[str, Any],
    substrate_outputs: dict[str, object],
    semantic_topics: list[object],
) -> dict[str, str]:
    """Build a complete Core semantic binding or reject incomplete model outputs."""

    if len(semantic_topics) < 3:
        raise ValueError("AKS semantic topic output contract is incomplete")

    def required_text(value: object, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"AKS {label} output is unavailable")
        return value.strip()

    environment = {
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": required_text(
            semantic_topics[0], "semantic request topic"
        ),
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": required_text(
            semantic_topics[1], "semantic projection topic"
        ),
        "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": required_text(
            semantic_topics[2], "read investigation topic"
        ),
        "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC": required_text(
            substrate_outputs.get("semantic_physical"), "semantic physical topic"
        ),
    }
    enable_llm = application_values.get("enable_llm")
    if not isinstance(enable_llm, bool):
        raise TypeError("AKS enable_llm setting MUST be a boolean")
    if not enable_llm:
        return environment

    endpoint = required_text(substrate_outputs.get("llm_endpoint"), "LLM endpoint")
    digest = required_text(substrate_outputs.get("resolved_models_sha256"), "resolved-model digest")
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("AKS resolved-model digest MUST be a lowercase SHA-256 digest")
    model_endpoints = substrate_outputs.get("llm_model_endpoints")
    if (
        not isinstance(model_endpoints, dict)
        or not model_endpoints
        or any(
            not isinstance(reference, str)
            or not reference.strip()
            or not isinstance(model_endpoint, str)
            or not model_endpoint.strip()
            for reference, model_endpoint in model_endpoints.items()
        )
    ):
        raise ValueError("AKS LLM model endpoint outputs are incomplete")
    environment.update(
        {
            "LLM_MODE": "azure",
            "LLM_RESOLVED_MODELS_PATH": "/app/resolved-models.json",
            "LLM_RESOLVED_MODELS_SHA256": digest,
            "FDAI_LLM_ENDPOINT": endpoint,
            "FDAI_MODEL_ENDPOINTS_JSON": json.dumps(
                model_endpoints,
                separators=(",", ":"),
                sort_keys=True,
            ),
        }
    )
    return environment


def _prepare_aks_application(_args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    context = _private_json(work_dir / "context.json", "standalone host context")
    if _runtime_platform(context) != "aks":
        raise ValueError("AKS application preparation is only valid for AKS")
    for prerequisite in (
        "runtime-receipt.json",
        "image-import-receipt.json",
        "migration-receipt.json",
    ):
        if not (work_dir / prerequisite).is_file():
            raise ValueError("AKS application preparation prerequisites are incomplete")
    _managed_identity_login_from_context(context, work_dir)
    substrate = Path(str(context["infra"]))
    runtime_infra = Path(str(context["runtime_infra"]))
    substrate_outputs = {
        "resource_group": _terraform_output(substrate, "resource_group_name"),
        "identities": _terraform_json_output(substrate, "runtime_identity_bindings"),
        "aks_subnet_id": _terraform_output(substrate, "aks_subnet_id"),
        "console_hostname": _terraform_output(substrate, "console_default_hostname"),
        "topics": _terraform_json_output(substrate, "event_bus_topics"),
        "semantic_topics": _terraform_json_output(substrate, "event_bus_semantic_topics"),
        "operating_model_topic": _terraform_output(substrate, "event_bus_operating_model_topic"),
        "kafka": _terraform_output(substrate, "event_bus_kafka_bootstrap"),
        "operational_kafka": _terraform_output(substrate, "event_bus_operational_kafka_bootstrap"),
        "workspace": _terraform_output(substrate, "log_workspace_customer_id"),
        "semantic_physical": _terraform_output(substrate, "event_bus_semantic_physical_topic"),
        "llm_endpoint": _terraform_output(substrate, "llm_endpoint"),
        "llm_model_endpoints": _terraform_json_output(substrate, "llm_model_endpoints"),
        "resolved_models_sha256": _terraform_output(substrate, "resolved_models_sha256"),
        "key_vault_uri": _terraform_output(substrate, "key_vault_uri"),
        "application_insights_secret_name": _terraform_output(
            substrate, "application_insights_connection_string_secret_name"
        ),
        "cost_pseudonym_key_secret_name": _terraform_output(
            substrate, "cost_pseudonym_key_secret_name"
        ),
        "operational_history_container_url": _terraform_output(
            substrate, "operational_history_container_url"
        ),
        "document_store": _terraform_json_output(substrate, "document_storage_binding"),
        "document_topics": _terraform_json_output(substrate, "document_event_topics"),
        "catalog_review_gitops_binding": _terraform_json_output(
            substrate, "catalog_review_gitops_binding"
        ),
        "installation_binding": _terraform_output(substrate, "installation_binding"),
        "operator_request_receipts": _terraform_json_output(
            substrate, "operator_request_receipt_binding"
        ),
        "operational_evidence_verifier_identity": _terraform_json_output(
            substrate, "operational_evidence_verifier_identity"
        ),
    }
    if _database_placement(context) == "postgres-flex":
        substrate_outputs.update(
            postgres_fqdn=_terraform_output(substrate, "postgres_fqdn"),
            postgres_database=_terraform_output(substrate, "postgres_database"),
        )
    else:
        _activate_terraform_stage("database", context, work_dir)
        database_infra = Path(str(context["database_infra"]))
        substrate_outputs.update(
            postgres_fqdn=_terraform_output(database_infra, "private_host"),
            postgres_database=_terraform_output(database_infra, "database_name"),
        )
    resource_group = str(substrate_outputs["resource_group"])
    _activate_terraform_stage("runtime", context, work_dir)
    cluster_id = _terraform_output(runtime_infra, "cluster_id")
    cluster_name = _terraform_output(runtime_infra, "cluster_name")
    deployment_binding = deployment_binding_digest(context, cluster_name)
    oidc_issuer_url = _terraform_output(runtime_infra, "oidc_issuer_url")
    kubeconfig = _prepare_aks_kubeconfig(
        context, work_dir, resource_group=resource_group, cluster_name=cluster_name
    )
    application_values = _private_json(
        work_dir / "application.auto.tfvars.json", "application variables"
    )
    console_selected = _selects_add_on(context, ProductAddOn.READ_ONLY_CONSOLE)
    enterprise_identity_selected = _selects_add_on(
        context, ProductAddOn.ENTERPRISE_IDENTITY_GOVERNANCE
    )
    operator_api_selected = console_selected or enterprise_identity_selected
    governed_execution_selected = _selects_add_on(context, ProductAddOn.GOVERNED_EXECUTION)
    console_origin = (
        _console_origin(str(substrate_outputs["console_hostname"])) if console_selected else ""
    )
    backend_nsg_id = _subnet_network_security_group(
        str(substrate_outputs["aks_subnet_id"]),
        context=context,
        cwd=work_dir,
    )
    identities = substrate_outputs["identities"]
    topics = substrate_outputs["topics"]
    semantic_topics = substrate_outputs["semantic_topics"]
    if (
        not isinstance(identities, dict)
        or not isinstance(topics, list)
        or not isinstance(semantic_topics, list)
        or len(semantic_topics) < 3
    ):
        raise ValueError("AKS substrate output contract is invalid")
    core_identity = _mapping(identities.get("core"), "core runtime identity")
    # Terraform emits null for identities of unselected surfaces, so read only selected ones.
    operator_identity = _selected_identity(identities, "operator", operator_api_selected)
    command_identity = _selected_identity(identities, "command", operator_api_selected)
    executor_identity = _selected_identity(identities, "executor", governed_execution_selected)
    inventory_identity = _mapping(identities.get("inventory"), "inventory runtime identity")
    canary_identity = _mapping(identities.get("canary"), "canary runtime identity")
    ingestion_identity = _selected_identity(identities, "ingestion", console_selected)
    ingestion_worker_identity = _selected_identity(identities, "ingestion_worker", console_selected)
    core_environment = {
        "AZURE_TENANT_ID": context["tenant_id"],
        "AZURE_SUBSCRIPTION_ID": context["subscription_id"],
        "AZURE_RESOURCE_GROUP": resource_group,
        "AZURE_REGION": application_values["region"],
        "AZURE_CLIENT_ID": core_identity["client_id"],
        "KAFKA_BOOTSTRAP_SERVERS": substrate_outputs["kafka"],
        "KAFKA_TOPIC_EVENTS": str(topics[0]),
        "POSTGRES_HOST": substrate_outputs["postgres_fqdn"],
        "POSTGRES_DATABASE": substrate_outputs["postgres_database"],
        "RUNTIME_ENV": application_values["env"],
        "AUTONOMY_MODE_DEFAULT": "shadow",
        "FDAI_MONITOR_WORKSPACE_ID": substrate_outputs["workspace"],
        "FDAI_OPERATING_MODEL_TOPIC": substrate_outputs["operating_model_topic"],
        "FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS": substrate_outputs["operational_kafka"],
        "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER": "1",
        "FDAI_PRODUCT_PROFILE_JSON": str(application_values["product_profile_json"]),
        "FDAI_START_CONSUMER": "1",
        "FDAI_INSTALLATION_BINDING": str(substrate_outputs["installation_binding"]),
        "FDAI_LICENSE_DEPLOYMENT_BINDING": deployment_binding,
    }
    core_environment.update(
        _aks_core_conversation_environment(
            application_values=application_values,
            substrate_outputs=substrate_outputs,
            semantic_topics=semantic_topics,
        )
    )
    receipt_core_env, receipt_core_secrets, receipt_operator_env, receipt_operator_secrets = (
        aks_operator_request_receipts(substrate_outputs["operator_request_receipts"])
    )
    core_environment.update({**AKS_CORE_STARTUP_READINESS, **receipt_core_env})
    license_environment, license_secrets = aks_license_environment(application_values)
    core_environment.update(license_environment)
    operator_environment = (
        aks_operator_environment(
            application_values=application_values,
            core_environment=core_environment,
            substrate_outputs=substrate_outputs,
            semantic_topics=semantic_topics,
            operator_identity=operator_identity,
            command_identity=command_identity,
            tenant_id=str(context["tenant_id"]),
            console_origin=console_origin,
        )
        if operator_api_selected
        else {}
    )
    dsn_secret = {
        "APPLICATIONINSIGHTS_CONNECTION_STRING": str(
            substrate_outputs["application_insights_secret_name"]
        ),
        "FDAI_STATE_STORE_DSN": "fdai-state-store-dsn",
        **receipt_core_secrets,
        **license_secrets,
    }
    refs = _mapping(context.get("image_refs"), "runtime image references")
    workloads = {
        "core-control-plane": _aks_workload(
            "core", refs, core_identity, core_environment, dsn_secret, "/ready", "/live"
        ),
    }
    if operator_api_selected:
        workloads["operator-service"] = _aks_workload(
            "operator",
            refs,
            operator_identity,
            {**operator_environment, **receipt_operator_env},
            {
                "FDAI_DATABASE_URL": "fdai-state-store-dsn",
                "FDAI_COST_PSEUDONYM_KEY": str(substrate_outputs["cost_pseudonym_key_secret_name"]),
                **receipt_operator_secrets,
            },
            "/healthz",
            "/healthz",
            external=True,
            service_port=80,
            additional_identities={"command": command_identity},
        )
    if governed_execution_selected:
        workloads["isolated-executor"] = _aks_workload(
            "executor",
            refs,
            executor_identity,
            {
                "AZURE_CLIENT_ID": executor_identity["client_id"],
                "RUNTIME_ENV": application_values["env"],
                "FDAI_ISOLATED_EXECUTOR_DEPLOYED": "1",
                "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER": "1",
                "FDAI_ISOLATED_EXECUTOR_MI_CLIENT_ID": executor_identity["client_id"],
                "KAFKA_BOOTSTRAP_SERVERS": substrate_outputs["operational_kafka"],
                "FDAI_ISOLATED_EXECUTOR_HEALTH_PORT": "8000",
                **_aks_kubernetes_direct_api_environment(
                    cluster_id,
                    namespace=_AKS_RUNTIME_NAMESPACE,
                ),
            },
            {
                "FDAI_STATE_STORE_DSN": "fdai-state-store-dsn",
                "FDAI_RESOURCE_LOCK_DSN": "fdai-state-store-dsn",
            },
            "/ready",
            "/live",
        )
    if console_selected:
        workloads.update(
            _aks_document_workloads(
                refs=refs,
                ingestion_identity=ingestion_identity,
                worker_identity=ingestion_worker_identity,
                application_values=application_values,
                kafka=str(substrate_outputs["kafka"]),
                postgres_fqdn=str(substrate_outputs["postgres_fqdn"]),
                document_store=_mapping(
                    substrate_outputs["document_store"], "document storage binding"
                ),
                document_topics=_mapping(
                    substrate_outputs["document_topics"], "document event topics"
                ),
                console_origin=console_origin,
            )
        )
    _add_aks_operational_evidence_verifier_workload(
        workloads,
        refs=refs,
        identities=identities,
        substrate_outputs=substrate_outputs,
        context=context,
        application_values=application_values,
    )
    for workload in workloads.values():
        workload["source_commit"] = context["source_commit"]
    job_preparation = _prepare_aks_scheduled_jobs(
        refs=refs,
        core_identity=core_identity,
        inventory_identity=inventory_identity,
        canary_identity=canary_identity,
        core_environment=core_environment,
        substrate_outputs=substrate_outputs,
        source_revision=str(context["source_commit"]),
        tenant_id=str(context["tenant_id"]),
        subscription_id=str(context["subscription_id"]),
        catalog_review_selected=context.get("catalog_review_selected") is True,
        cluster_id=cluster_id,
        namespace=_AKS_RUNTIME_NAMESPACE,
    )
    scheduled_jobs = job_preparation.jobs
    workloads_infra = substrate / "runtimes/aks/workloads"
    values = {
        "kubeconfig_path": str(kubeconfig),
        "namespace": _AKS_RUNTIME_NAMESPACE,
        "tenant_id": context["tenant_id"],
        "oidc_issuer_url": oidc_issuer_url,
        "key_vault_name": _vault_name(str(substrate_outputs["key_vault_uri"])),
        "workloads": workloads,
        "scheduled_jobs": scheduled_jobs,
        "browser_gateway": {
            "resource_group_name": resource_group,
            "location": application_values["region"],
            "workload": application_values["workload"],
            "environment": application_values["env"],
            "region_short": application_values["region_short"],
            "resource_name_suffix": application_values["resource_name_suffix"],
            "backend_nsg_id": backend_nsg_id,
        },
        "tags": {"fdai.io/source-commit": context["source_commit"]},
    }
    context.update(
        workloads_infra=str(workloads_infra),
        workloads_state_key=f"fdai-{application_values['env']}-aks-workloads.tfstate",
        workloads_terraform_data=str(work_dir / "terraform-data-workloads"),
        kubeconfig=str(kubeconfig),
        deployment_binding=deployment_binding,
        expected_workloads={
            name: aks_readiness.workload_contract(workload) for name, workload in workloads.items()
        },
        protected_aks_job_template_digests=job_preparation.protected_template_digests,
        protected_aks_job_identity_bindings=job_preparation.protected_identity_bindings,
        catalog_review_available=job_preparation.catalog_review_available,
    )
    _replace_or_verify_private_json(work_dir / "workloads.auto.tfvars.json", values)
    _replace_private_json(work_dir / "context.json", context)
    _initialize_terraform_stage("application", context, work_dir)
    return {
        "schema_version": "fdai.standalone-aks-application-prepare.v1",
        "state": "prepared",
        "runtime_profile_digest": _runtime_profile_digest(context),
        "workload_count": len(workloads),
        "scheduled_job_count": len(scheduled_jobs),
        "state_key": context["workloads_state_key"],
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _prepare_aks_service_update(args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    """Seal one service image update against the current complete AKS workload baseline."""

    context = _private_json(work_dir / "context.json", "standalone host context")
    if _runtime_platform(context) != "aks":
        raise ValueError("AKS service update requires an AKS installation")
    _require_aks_application_baseline(work_dir, context)
    _managed_identity_login_from_context(context, work_dir)
    service = str(args.service)
    values = _private_json(work_dir / "workloads.auto.tfvars.json", "AKS workload variables")
    workloads = _mapping(values.get("workloads"), "AKS workloads")
    expected = _mapping(context.get("expected_workloads"), "expected AKS workloads")
    if set(workloads) != set(expected) or service not in workloads:
        raise ValueError("AKS service update workload inventory is incomplete")
    active = context.get("active_service_update")
    if isinstance(active, dict):
        operation = active.get("operation")
        if not isinstance(operation, str) or not (work_dir / f"{operation}-receipt.json").is_file():
            raise ValueError("AKS service update already has an incomplete active operation")
    default_source = str(context.get("source_commit", ""))
    for name, workload_value in workloads.items():
        workload = _mapping(workload_value, f"AKS workload {name}")
        contract = _mapping(expected.get(name), f"expected AKS workload {name}")
        source_commit = workload.get("source_commit", contract.get("source_commit", default_source))
        if not isinstance(source_commit, str) or _SOURCE_COMMIT.fullmatch(source_commit) is None:
            raise ValueError("AKS workload source revision is invalid")
        workload["source_commit"] = source_commit
        contract["source_commit"] = source_commit
        workloads[name] = workload
        expected[name] = contract
    selected = _mapping(workloads[service], f"AKS workload {service}")
    current_image = selected.get("image")
    if not isinstance(current_image, str):
        raise TypeError("AKS service update current image is invalid")
    validate_update_request(
        service=service,
        image=str(args.image),
        source_commit=str(args.source_commit),
        current_image=current_image,
    )
    baseline = deployment_snapshot(
        _capture_aks_deployments(context), expected_services=set(workloads)
    )
    for name, contract_value in expected.items():
        contract = _mapping(contract_value, f"expected AKS workload {name}")
        if baseline[name]["image"] != contract.get("image") or baseline[name][
            "source_commit"
        ] != contract.get("source_commit"):
            raise ValueError("AKS service update baseline differs from retained desired state")
    selected["image"] = str(args.image)
    selected["source_commit"] = str(args.source_commit)
    workloads[service] = selected
    selected_expected = _mapping(expected[service], f"expected AKS workload {service}")
    selected_expected["image"] = str(args.image)
    selected_expected["source_commit"] = str(args.source_commit)
    expected[service] = selected_expected
    values["workloads"] = workloads
    update_identity = {
        "service": service,
        "image": str(args.image),
        "source_commit": str(args.source_commit),
        "target_binding": context["target_binding"],
        "runtime_profile_digest": _runtime_profile_digest(context),
    }
    operation = f"service-update-{service}-{canonical_digest(update_identity)[:12]}"
    record: dict[str, object] = {
        "schema_version": "fdai.aks-service-update.v1",
        "operation": operation,
        **update_identity,
        "previous_image": current_image,
        "baseline": baseline,
        "prepared_at": _moment(datetime.now(UTC)),
        "mutation_performed": False,
        "subscription_ready": False,
    }
    record["update_digest"] = canonical_digest(record)
    _replace_private_json(work_dir / f"{operation}.json", record)
    context["expected_workloads"] = expected
    context["active_service_update"] = {
        "operation": operation,
        "service": service,
        "update_digest": record["update_digest"],
    }
    _replace_private_json(work_dir / "workloads.auto.tfvars.json", values)
    _replace_private_json(work_dir / "context.json", context)
    return {
        "schema_version": "fdai.aks-service-update-prepare.v1",
        "state": "prepared",
        "operation": operation,
        "service": service,
        "image": str(args.image),
        "source_commit": str(args.source_commit),
        "update_digest": record["update_digest"],
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _validate_historical_aks_baseline(
    *,
    state: dict[str, Any],
    variables: dict[str, Any],
    live: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, object]:
    """Cross-check retained Terraform state, desired inputs, live AKS, and convergence."""

    lineage = state.get("lineage")
    serial = state.get("serial")
    resources = state.get("resources")
    if (
        state.get("version") != 4
        or not isinstance(lineage, str)
        or not lineage
        or type(serial) is not int
        or serial < 0
        or not isinstance(resources, list)
    ):
        raise ValueError("historical AKS Terraform state is invalid")
    if variables.get("namespace") != _AKS_RUNTIME_NAMESPACE:
        raise ValueError("historical AKS workload namespace is invalid")
    workloads = _mapping(variables.get("workloads"), "historical AKS workloads")
    if set(workloads) != set(AKS_SERVICES):
        raise ValueError("historical AKS workload inventory is incomplete")

    expected: dict[str, dict[str, object]] = {}
    for name in sorted(AKS_SERVICES):
        workload = _mapping(workloads.get(name), f"historical AKS workload {name}")
        image = workload.get("image")
        source_commit = workload.get("source_commit")
        replicas = workload.get("replicas")
        max_replicas = workload.get("max_replicas")
        if (
            not isinstance(image, str)
            or re.fullmatch(r"[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}", image)
            is None
            or not isinstance(source_commit, str)
            or _SOURCE_COMMIT.fullmatch(source_commit) is None
            or type(replicas) is not int
            or type(max_replicas) is not int
            or replicas < 1
            or max_replicas < replicas
            or not aks_readiness.valid_secret_environment(workload.get("secret_environment", {}))
        ):
            raise ValueError("historical AKS workload contract is invalid")
        expected[name] = {
            "image": image,
            "replicas": replicas,
            "max_replicas": max_replicas,
            "source_commit": source_commit,
            "secret_environment": dict(workload.get("secret_environment", {})),
        }

    state_workloads = _historical_state_workloads(resources)
    desired_identity = {
        name: {
            "image": workload["image"],
            "source_commit": workload["source_commit"],
        }
        for name, workload in expected.items()
    }
    if state_workloads != desired_identity:
        raise ValueError("historical AKS Terraform state differs from desired workloads")
    observed = deployment_snapshot(json.dumps(live), expected_services=set(AKS_SERVICES))
    live_identity = {
        name: {
            "image": workload["image"],
            "source_commit": workload["source_commit"],
        }
        for name, workload in observed.items()
    }
    if live_identity != desired_identity:
        raise ValueError("historical AKS live baseline differs from desired workloads")

    changes = plan.get("resource_changes")
    if plan.get("errored") is not False:
        raise ValueError("historical AKS deployment plan is invalid")
    if not isinstance(changes, list) or not changes:
        raise ValueError("historical AKS deployment plan inventory is invalid")
    deployment_seen = False
    projected: list[dict[str, object]] = []
    mutating_services: list[str] = []
    out_of_scope_mutation = False
    for value in changes:
        change = _mapping(value, "historical AKS deployment change")
        actions = _mapping(change.get("change"), "historical AKS deployment actions").get("actions")
        address = change.get("address")
        if (
            not isinstance(address, str)
            or not isinstance(actions, list)
            or not all(isinstance(action, str) for action in actions)
        ):
            raise ValueError("historical AKS deployment plan change is invalid")
        reordered = secret_binding_reordered(address, change.get("change"))
        projected.append({"address": address, "actions": ["no-op"] if reordered else actions})
        if not reordered and not set(actions).issubset({"no-op", "read"}):
            out_of_scope_mutation = True
        if isinstance(address, str) and address.startswith("kubernetes_deployment_v1.workload["):
            deployment_seen = True
            if set(actions) == {"update"}:
                match = re.fullmatch(r'kubernetes_deployment_v1[.]workload\["([^"\\]+)"\]', address)
                if match is not None:
                    mutating_services.append(match.group(1))
    if not deployment_seen:
        raise ValueError("historical AKS deployment plan omits workload state")
    if mutating_services:
        if (
            plan.get("applyable") is not True
            or len(mutating_services) != 1
            or mutating_services[0] not in AKS_SERVICES
        ):
            raise ValueError("historical AKS deployment plan mutation is invalid")
        validate_plan_scope(
            {"resource_changes": projected},
            service=mutating_services[0],
        )
    else:
        if out_of_scope_mutation:
            raise ValueError("historical AKS deployment plan contains an out-of-scope mutation")
        if plan.get("complete") is not True:
            raise ValueError("historical AKS zero-change plan is incomplete")
    return {
        "expected_workloads": expected,
        "state_lineage": lineage,
        "state_serial": serial,
        "historical_plan_service": mutating_services[0] if mutating_services else None,
    }


def _adopt_historical_aks_application(
    args: argparse.Namespace, work_dir: Path
) -> dict[str, object]:
    """Adopt one verified historical AKS workload baseline without changing Azure state."""

    binding_path = _absolute(args.binding)
    state_path = _absolute(args.state)
    variables_path = _absolute(args.variables)
    live_path = _absolute(args.live)
    plan_path = _absolute(args.plan)
    binding = _private_json(binding_path, "historical AKS adoption binding")
    state = _private_json(state_path, "historical AKS Terraform state")
    variables = _private_json(variables_path, "historical AKS workload variables")
    live = _private_json(live_path, "historical AKS live baseline")
    plan = _private_json(plan_path, "historical AKS deployment plan")
    baseline = _validate_historical_aks_baseline(
        state=state,
        variables=variables,
        live=live,
        plan=plan,
    )
    expected_binding_fields = {
        "schema_version",
        "source_commit",
        "subscription_id",
        "tenant_id",
        "client_id",
        "principal_id",
        "runtime_profile",
        "source_root",
        "terraform",
        "terraform_sha256",
        "provider_mirror",
        "workloads_infra",
        "terraform_data",
        "kubeconfig",
        "kit_bin",
    }
    if set(binding) != expected_binding_fields:
        raise ValueError("historical AKS adoption binding fields are invalid")
    if binding.get("schema_version") != "fdai.historical-aks-application-binding.v1":
        raise ValueError("historical AKS adoption binding schema is invalid")
    subscription_id = _required_guid(binding, "subscription_id")
    tenant_id = _required_guid(binding, "tenant_id")
    client_id = _required_guid(binding, "client_id")
    principal_id = _required_guid(binding, "principal_id")
    source_commit = str(binding.get("source_commit", ""))
    if _SOURCE_COMMIT.fullmatch(source_commit) is None:
        raise ValueError("historical AKS adoption source revision is invalid")
    profile_value = _mapping(binding.get("runtime_profile"), "historical AKS runtime profile")
    profile = RuntimeDeploymentProfile.from_mapping(profile_value)
    if profile.runtime_platform.value != "aks" or not profile.matches_mapping(profile_value):
        raise ValueError("historical AKS adoption runtime profile differs")

    evidence_root = binding_path.parent.resolve()
    source_root = _adoption_work_path(evidence_root, binding, "source_root", directory=True)
    terraform = _adoption_work_path(evidence_root, binding, "terraform", executable=True)
    provider_mirror = _adoption_work_path(evidence_root, binding, "provider_mirror", directory=True)
    workloads_infra = _adoption_work_path(evidence_root, binding, "workloads_infra", directory=True)
    terraform_data = _adoption_work_path(evidence_root, binding, "terraform_data", directory=True)
    kubeconfig = _adoption_work_path(evidence_root, binding, "kubeconfig")
    kit_bin = _adoption_work_path(evidence_root, binding, "kit_bin", directory=True)
    if _executable_digest(terraform) != binding.get("terraform_sha256"):
        raise ValueError("historical AKS Terraform binary digest differs")
    observed_source = _capture(
        ("git", "rev-parse", "HEAD"),
        cwd=source_root,
        timeout=30,
        reason="historical AKS source revision readback failed",
    ).strip()
    if observed_source != source_commit:
        raise ValueError("historical AKS source revision differs")

    baseline_workloads = _mapping(
        baseline.get("expected_workloads"), "historical AKS expected workloads"
    )
    registry_hosts = {
        str(workload["image"]).partition("/")[0]
        for workload in baseline_workloads.values()
        if isinstance(workload, dict)
    }
    if len(registry_hosts) != 1:
        raise ValueError("historical AKS workload registries differ")
    registry_login_server = registry_hosts.pop()
    match = re.fullmatch(r"([a-z0-9]{5,50})[.]azurecr[.]io", registry_login_server)
    if match is None:
        raise ValueError("historical AKS registry is invalid")
    target_binding = compute_target_binding(
        tenant_id=tenant_id,
        subscription_id=subscription_id,
    )
    terraform_config = work_dir / "historical-adoption-terraform.rc"
    expected_config = _terraform_configuration(provider_mirror)
    if terraform_config.exists():
        if read_private_bytes(terraform_config, max_bytes=16_384).decode() != expected_config:
            raise ValueError("historical AKS Terraform configuration differs")
    else:
        write_private_output(terraform_config, expected_config)
    context: dict[str, object] = {
        "source_commit": source_commit,
        "target_binding": target_binding,
        "subscription_id": subscription_id,
        "tenant_id": tenant_id,
        "client_id": client_id,
        "principal_id": principal_id,
        "runtime_profile": profile.to_mapping(),
        "runtime_profile_digest": profile.digest,
        "registry_name": match.group(1),
        "registry_login_server": registry_login_server,
        "infra": str(workloads_infra),
        "terraform": str(terraform),
        "provider_mirror": str(provider_mirror),
        "terraform_config": str(terraform_config),
        "terraform_data": str(terraform_data),
        "kit_bin": str(kit_bin),
        "workloads_infra": str(workloads_infra),
        "workloads_terraform_data": str(terraform_data),
        "kubeconfig": str(kubeconfig),
        "expected_workloads": baseline["expected_workloads"],
    }
    reconciliation_applied = (work_dir / "historical-reconciliation-receipt.json").is_file()
    if reconciliation_applied:
        retained_context = _private_json(
            work_dir / "context.json",
            "historical AKS reconciliation context",
        )
        reconciliation = _historical_reconciliation_record(
            retained_context,
            work_dir,
            stage="application",
            service=None,
        )
        if reconciliation is None:
            raise ValueError("historical AKS reconciliation context is unavailable")
        _historical_reconciliation_receipt(work_dir, context, reconciliation)
        state_path = work_dir / "historical-reconciliation-state.json"
        variables_path = work_dir / "workloads.auto.tfvars.json"
        live_path = work_dir / "historical-reconciliation-live.json"
        plan_path = work_dir / "historical-reconciliation-zero-plan.json"
        state = _private_json(state_path, "reconciled historical AKS Terraform state")
        variables = _private_json(variables_path, "reconciled historical AKS variables")
        live = _private_json(live_path, "reconciled historical AKS live baseline")
        plan = _private_json(plan_path, "reconciled historical AKS zero-change plan")
        baseline = _validate_historical_aks_baseline(
            state=state,
            variables=variables,
            live=live,
            plan=plan,
        )
    _managed_identity_login_from_context(context, work_dir)
    remote_state = json.loads(
        _capture(
            ("terraform", "state", "pull"),
            cwd=workloads_infra,
            timeout=300,
            reason="historical AKS remote state readback failed",
        )
    )
    if not isinstance(remote_state, dict):
        raise TypeError("historical AKS remote state readback is invalid")
    if (
        remote_state.get("lineage") != baseline["state_lineage"]
        or type(remote_state.get("serial")) is not int
        or remote_state["serial"] < baseline["state_serial"]
        or canonical_digest(remote_state.get("resources"))
        != canonical_digest(state.get("resources"))
    ):
        raise ValueError("historical AKS remote state differs from retained evidence")
    observed_live = json.loads(_capture_aks_deployments(context))
    if not isinstance(observed_live, dict):
        raise TypeError("historical AKS live readback is invalid")
    current_variables = reconciled_variables(
        state=state,
        variables=variables,
        live=observed_live,
    )
    current_variables_path = work_dir / "historical-reconciliation.auto.tfvars.json"
    _replace_private_json(current_variables_path, current_variables)
    _activate_terraform_stage("application", context, work_dir)
    current_plan_path = work_dir / (
        "historical-adoption-current.tfplan"
        if reconciliation_applied
        else "historical-reconciliation.tfplan"
    )
    current_plan_path.unlink(missing_ok=True)
    current_plan = subprocess.run(
        (
            "terraform",
            "plan",
            "-detailed-exitcode",
            "-input=false",
            "-no-color",
            f"-var-file={current_variables_path}",
            f"-out={current_plan_path}",
        ),
        cwd=workloads_infra,
        check=False,
        capture_output=True,
        timeout=1800,
    )
    if current_plan.returncode not in {0, 2}:
        raise ValueError("historical AKS current plan failed")
    current_plan_document = json.loads(
        _capture(
            ("terraform", "show", "-json", str(current_plan_path)),
            cwd=workloads_infra,
            timeout=300,
            reason="historical AKS current plan projection failed",
        )
    )
    if not isinstance(current_plan_document, dict):
        raise TypeError("historical AKS current plan projection is invalid")
    if current_plan.returncode == 2:
        mutations = validate_reconciliation_plan(
            current_plan_document,
            variables=current_variables,
        )
        summary = _plan_summary(current_plan_document)
        review: dict[str, object] = {
            "schema_version": "fdai.standalone-application-plan.v1",
            "stage": "application",
            "plan_digest": _file_digest(current_plan_path),
            "target_binding": target_binding,
            "source_commit": source_commit,
            "runtime_profile_digest": profile.digest,
            "runtime_platform": "aks",
            "summary": summary,
            "expires_at": _moment(datetime.now(UTC) + timedelta(hours=1)),
            "mutation_performed": False,
            "subscription_ready": False,
            "historical_reconciliation": {
                "operation": "historical-reconciliation",
                "variables_digest": canonical_digest(current_variables),
                "mutations": list(mutations),
            },
        }
        review["review_digest"] = canonical_digest(review)
        context["active_historical_reconciliation"] = {
            "operation": "historical-reconciliation",
            "variables_digest": canonical_digest(current_variables),
            "mutations": list(mutations),
            "review_digest": review["review_digest"],
        }
        _replace_private_json(work_dir / "context.json", context)
        _replace_private_json(work_dir / "workloads.auto.tfvars.json", current_variables)
        _replace_private_json(work_dir / "application.auto.tfvars.json", {"env": "dev"})
        _replace_private_json(work_dir / "historical-reconciliation-review.json", review)
        return {
            "schema_version": "fdai.historical-aks-application-adoption.v1",
            "state": "reconciliation-required",
            "reconciliation_review": review,
            "mutation_performed": False,
            "subscription_ready": False,
        }
    _validate_historical_aks_baseline(
        state=remote_state,
        variables=current_variables,
        live=observed_live,
        plan=current_plan_document,
    )
    current_plan_summary = _plan_summary(current_plan_document)

    context.pop("active_historical_reconciliation", None)
    context_digest = canonical_digest(context)
    receipt: dict[str, object] = {
        "schema_version": "fdai.historical-aks-application-adoption.v1",
        "state": "adopted",
        "target_binding": target_binding,
        "source_commit": source_commit,
        "runtime_profile_digest": profile.digest,
        "context_digest": context_digest,
        "binding_sha256": _file_digest(binding_path),
        "retained_state_sha256": _file_digest(state_path),
        "retained_variables_sha256": _file_digest(variables_path),
        "retained_live_sha256": _file_digest(live_path),
        "retained_plan_sha256": _file_digest(plan_path),
        "remote_state_lineage": remote_state["lineage"],
        "remote_state_serial": remote_state["serial"],
        "historical_plan_service": baseline["historical_plan_service"],
        "current_plan_summary": current_plan_summary,
        "managed_identity_verified": True,
        "remote_state_verified": True,
        "live_baseline_verified": True,
        "terraform_zero_change_verified": True,
        "azure_resource_mutation_performed": False,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    retained_receipt = work_dir / "historical-aks-application-adoption-receipt.json"
    if retained_receipt.exists():
        if _private_json(retained_receipt, "historical AKS adoption receipt") != receipt:
            raise ValueError("retained historical AKS adoption receipt differs")
    else:
        _replace_private_json(work_dir / "context.json", context)
        _replace_private_json(work_dir / "workloads.auto.tfvars.json", current_variables)
        _replace_private_json(work_dir / "application.auto.tfvars.json", {"env": "dev"})
        _replace_private_json(retained_receipt, receipt)
    return receipt


def _adoption_work_path(
    evidence_root: Path,
    binding: dict[str, Any],
    name: str,
    *,
    directory: bool = False,
    executable: bool = False,
) -> Path:
    value = binding.get(name)
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(f"historical AKS adoption {name} path is invalid")
    selected = Path(value)
    candidate = evidence_root
    for part in selected.parts:
        candidate /= part
        if candidate.is_symlink():
            raise ValueError(
                f"historical AKS adoption {name} path is outside the evidence directory"
            )
    path = candidate.resolve()
    if not path.is_relative_to(evidence_root):
        raise ValueError(f"historical AKS adoption {name} path is outside the evidence directory")
    details = path.stat()
    if directory and not stat.S_ISDIR(details.st_mode):
        raise ValueError(f"historical AKS adoption {name} directory is unavailable")
    if not directory and not stat.S_ISREG(details.st_mode):
        raise ValueError(f"historical AKS adoption {name} file is unavailable")
    if executable and not details.st_mode & stat.S_IXUSR:
        raise ValueError(f"historical AKS adoption {name} file is not executable")
    return path


def _require_aks_application_baseline(work_dir: Path, context: dict[str, object]) -> None:
    if (work_dir / "application-receipt.json").is_file():
        return
    path = work_dir / "historical-aks-application-adoption-receipt.json"
    if not path.is_file():
        raise ValueError("AKS service update requires an applied or adopted application baseline")
    receipt = _private_json(path, "historical AKS adoption receipt")
    digest = receipt.get("receipt_digest")
    document = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    summary = _mapping(receipt.get("current_plan_summary"), "historical AKS plan summary")
    action_counts = _mapping(summary.get("action_counts"), "historical AKS plan action counts")
    resource_types = _mapping(
        summary.get("resource_type_counts"), "historical AKS plan resource types"
    )
    expected_fields = {
        "schema_version",
        "state",
        "target_binding",
        "source_commit",
        "runtime_profile_digest",
        "context_digest",
        "binding_sha256",
        "retained_state_sha256",
        "retained_variables_sha256",
        "retained_live_sha256",
        "retained_plan_sha256",
        "remote_state_lineage",
        "remote_state_serial",
        "historical_plan_service",
        "current_plan_summary",
        "managed_identity_verified",
        "remote_state_verified",
        "live_baseline_verified",
        "terraform_zero_change_verified",
        "azure_resource_mutation_performed",
        "mutation_performed",
        "subscription_ready",
        "receipt_digest",
    }
    if (
        set(receipt) != expected_fields
        or receipt.get("schema_version") != "fdai.historical-aks-application-adoption.v1"
        or receipt.get("state") != "adopted"
        or receipt.get("target_binding") != context.get("target_binding")
        or receipt.get("source_commit") != context.get("source_commit")
        or receipt.get("runtime_profile_digest") != _runtime_profile_digest(context)
        or receipt.get("context_digest") != canonical_digest(context)
        or receipt.get("managed_identity_verified") is not True
        or receipt.get("remote_state_verified") is not True
        or receipt.get("live_baseline_verified") is not True
        or receipt.get("terraform_zero_change_verified") is not True
        or receipt.get("azure_resource_mutation_performed") is not False
        or receipt.get("mutation_performed") is not True
        or receipt.get("subscription_ready") is not False
        or receipt.get("historical_plan_service") not in {*AKS_SERVICES, None}
        or not isinstance(receipt.get("remote_state_lineage"), str)
        or type(receipt.get("remote_state_serial")) is not int
        or any(
            not isinstance(receipt.get(field), str)
            or _DIGEST.fullmatch(str(receipt[field])) is None
            for field in (
                "binding_sha256",
                "retained_state_sha256",
                "retained_variables_sha256",
                "retained_live_sha256",
                "retained_plan_sha256",
            )
        )
        or set(action_counts) != {"create", "update", "delete", "replace", "read", "no-op"}
        or any(type(value) is not int or value < 0 for value in action_counts.values())
        or any(action_counts[action] != 0 for action in ("create", "update", "delete", "replace"))
        or resource_types.get("kubernetes_deployment_v1") != len(AKS_SERVICES)
        or not isinstance(summary.get("resource_changes"), list)
        or digest != canonical_digest(document)
    ):
        raise ValueError("historical AKS adoption receipt is invalid")


def _historical_state_workloads(resources: list[object]) -> dict[str, dict[str, str]]:
    deployments = [
        _mapping(value, "historical AKS Terraform resource")
        for value in resources
        if isinstance(value, dict)
        and value.get("mode") == "managed"
        and value.get("type") == "kubernetes_deployment_v1"
        and value.get("name") == "workload"
    ]
    if len(deployments) != 1 or not isinstance(deployments[0].get("instances"), list):
        raise ValueError("historical AKS Terraform workload resource is invalid")
    result: dict[str, dict[str, str]] = {}
    for value in deployments[0]["instances"]:
        instance = _mapping(value, "historical AKS Terraform workload instance")
        name = instance.get("index_key")
        attributes = _mapping(
            instance.get("attributes"), "historical AKS Terraform workload attributes"
        )
        try:
            metadata = _mapping(
                _single(attributes.get("metadata")), "historical AKS Terraform metadata"
            )
            template = _mapping(
                _single(_single(attributes.get("spec")).get("template")),
                "historical AKS Terraform Pod template",
            )
            labels = _mapping(
                _single(template.get("metadata")).get("labels"),
                "historical AKS Terraform Pod labels",
            )
            containers = _single(template.get("spec")).get("container")
        except (AttributeError, TypeError) as exc:
            raise ValueError("historical AKS Terraform workload structure is invalid") from exc
        if (
            not isinstance(name, str)
            or name not in AKS_SERVICES
            or name in result
            or metadata.get("name") != name
            or not isinstance(containers, list)
        ):
            raise ValueError("historical AKS Terraform workload identity is invalid")
        selected = [
            _mapping(container, "historical AKS Terraform container")
            for container in containers
            if isinstance(container, dict) and container.get("name") == name
        ]
        if len(selected) != 1:
            raise ValueError("historical AKS Terraform workload container is invalid")
        image = selected[0].get("image")
        source_commit = labels.get("fdai.io/source-commit")
        if not isinstance(image, str) or not isinstance(source_commit, str):
            raise TypeError("historical AKS Terraform rollout identity is invalid")
        result[name] = {"image": image, "source_commit": source_commit}
    if set(result) != set(AKS_SERVICES):
        raise ValueError("historical AKS Terraform workload inventory is incomplete")
    return dict(sorted(result.items()))


def _single(value: object) -> dict[str, Any]:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ValueError("historical AKS Terraform nested block is invalid")
    return dict(value[0])


def _service_update_record(
    context: dict[str, object],
    work_dir: Path,
    *,
    stage: str,
    service: str | None,
) -> dict[str, Any] | None:
    if service is None:
        return None
    if stage != "application" or _runtime_platform(context) != "aks":
        raise ValueError("--service is supported only for an AKS application stage")
    active = _mapping(context.get("active_service_update"), "active AKS service update")
    operation = active.get("operation")
    if (
        active.get("service") != service
        or not isinstance(operation, str)
        or re.fullmatch(rf"service-update-{re.escape(service)}-[0-9a-f]{{12}}", operation) is None
    ):
        raise ValueError("active AKS service update does not match the selected service")
    record = _private_json(work_dir / f"{operation}.json", "AKS service update")
    update_digest = record.get("update_digest")
    document = {key: value for key, value in record.items() if key != "update_digest"}
    if (
        record.get("schema_version") != "fdai.aks-service-update.v1"
        or record.get("operation") != operation
        or record.get("service") != service
        or active.get("update_digest") != update_digest
        or update_digest != canonical_digest(document)
        or record.get("target_binding") != context.get("target_binding")
        or record.get("runtime_profile_digest") != _runtime_profile_digest(context)
        or not isinstance(record.get("baseline"), dict)
    ):
        raise ValueError("active AKS service update record is invalid")
    image = record.get("image")
    source_commit = record.get("source_commit")
    previous_image = record.get("previous_image")
    if not all(isinstance(value, str) for value in (image, source_commit, previous_image)):
        raise ValueError("active AKS service update binding is invalid")
    validate_update_request(
        service=service,
        image=str(image),
        source_commit=str(source_commit),
        current_image=str(previous_image),
    )
    return record


def _historical_reconciliation_record(
    context: dict[str, object],
    work_dir: Path,
    *,
    stage: str,
    service: str | None,
) -> dict[str, Any] | None:
    value = context.get("active_historical_reconciliation")
    if value is None:
        return None
    if stage != "application" or service is not None:
        raise ValueError("historical AKS reconciliation blocks another application operation")
    record = _mapping(value, "active historical AKS reconciliation")
    mutations = record.get("mutations")
    variables = _private_json(
        work_dir / "workloads.auto.tfvars.json",
        "historical AKS reconciliation variables",
    )
    review = _private_json(
        work_dir / "historical-reconciliation-review.json",
        "historical AKS reconciliation review",
    )
    review_binding = review.get("historical_reconciliation")
    if (
        set(record) != {"operation", "variables_digest", "mutations", "review_digest"}
        or record.get("operation") != "historical-reconciliation"
        or record.get("variables_digest") != canonical_digest(variables)
        or not isinstance(mutations, list)
        or not mutations
        or len(mutations) > 64
        or mutations != sorted(set(mutations))
        or any(not isinstance(item, str) or not item for item in mutations)
        or record.get("review_digest") != review.get("review_digest")
        or review_binding
        != {
            "operation": record.get("operation"),
            "variables_digest": record.get("variables_digest"),
            "mutations": mutations,
        }
    ):
        raise ValueError("active historical AKS reconciliation is invalid")
    return record


def _application_operation(
    context: dict[str, object],
    work_dir: Path,
    *,
    stage: str,
    service: str | None,
    update: dict[str, Any] | None,
) -> tuple[str, dict[str, Any] | None]:
    reconciliation = _historical_reconciliation_record(
        context,
        work_dir,
        stage=stage,
        service=service,
    )
    if reconciliation is not None:
        return str(reconciliation["operation"]), reconciliation
    return (str(update["operation"]) if update is not None else stage), None


def _service_update_review(update: dict[str, Any]) -> dict[str, str]:
    return {
        "service": str(update["service"]),
        "image": str(update["image"]),
        "source_commit": str(update["source_commit"]),
        "update_digest": str(update["update_digest"]),
    }


def _service_update_target(service: str) -> str:
    if service not in AKS_SERVICES:
        raise ValueError("AKS service update target is unsupported")
    return f'kubernetes_deployment_v1.workload["{service}"]'


def _capture_aks_deployments(context: dict[str, object], *, service: str | None = None) -> str:
    kubeconfig = Path(str(context.get("kubeconfig", "")))
    if not kubeconfig.is_file():
        raise ValueError("AKS kubeconfig is unavailable for service update readback")
    endpoint = f"/apis/apps/v1/namespaces/{_AKS_RUNTIME_NAMESPACE}/deployments"
    if service is not None:
        endpoint = f"{endpoint}?{urlencode({'labelSelector': f'app.kubernetes.io/name={service}'})}"
    command = [
        "kubectl",
        "get",
        f"--raw={endpoint}",
        "--request-timeout=60s",
        f"--kubeconfig={kubeconfig}",
    ]
    return _capture(
        tuple(command),
        cwd=kubeconfig.parent,
        timeout=90,
        reason="AKS Deployment observation failed",
    )


def _capture_aks_pods(context: dict[str, object], *, service: str) -> str:
    kubeconfig = Path(str(context.get("kubeconfig", "")))
    if not kubeconfig.is_file():
        raise ValueError("AKS kubeconfig is unavailable for service update readback")
    return _capture(
        (
            "kubectl",
            "get",
            "pods",
            "--namespace",
            _AKS_RUNTIME_NAMESPACE,
            "--output",
            "json",
            "--request-timeout=60s",
            f"--selector=app.kubernetes.io/name={service}",
            f"--kubeconfig={kubeconfig}",
        ),
        cwd=kubeconfig.parent,
        timeout=90,
        reason="AKS Pod observation failed",
    )


def _readback_aks_service_update(context: dict[str, object], update: dict[str, Any]) -> bool:
    service = str(update["service"])
    expected = _mapping(context.get("expected_workloads"), "expected AKS workloads")
    contract = _mapping(expected.get(service), f"expected AKS workload {service}")
    if contract.get("image") != update.get("image") or contract.get("source_commit") != update.get(
        "source_commit"
    ):
        return False
    try:
        before = _mapping(update.get("baseline"), "AKS service update baseline")
        after = deployment_snapshot(
            _capture_aks_deployments(context), expected_services=set(expected)
        )
    except ValueError:
        return False
    if not peers_unchanged(before=before, after=after, service=service):
        return False
    return aks_readiness.verify_workload_health(
        deployments=_capture_aks_deployments(context, service=service),
        pods=_capture_aks_pods(context, service=service),
        expected={service: contract},
    )


def _service_update_zero_change(
    context: dict[str, object], work_dir: Path, update: dict[str, Any]
) -> bool:
    infra, variables = _stage_paths("application", context, work_dir)
    _activate_terraform_stage("application", context, work_dir)
    completed = subprocess.run(
        (
            "terraform",
            "plan",
            "-detailed-exitcode",
            "-input=false",
            "-no-color",
            f"-var-file={variables}",
            f"-target={_service_update_target(str(update['service']))}",
        ),
        cwd=infra,
        check=False,
        capture_output=True,
        timeout=1800,
    )
    return completed.returncode == 0


def _historical_reconciliation_postconditions(
    context: dict[str, object],
    work_dir: Path,
    reconciliation: dict[str, Any],
) -> dict[str, str]:
    """Retain authoritative state, typed live readback, and a full zero-change plan."""

    infra, variables_path = _stage_paths("application", context, work_dir)
    variables = _private_json(variables_path, "historical AKS reconciliation variables")
    if reconciliation.get("variables_digest") != canonical_digest(variables):
        raise ValueError("historical AKS reconciliation variables changed")
    _activate_terraform_stage("application", context, work_dir)
    zero_plan_path = work_dir / "historical-reconciliation-zero.tfplan"
    zero_plan_path.unlink(missing_ok=True)
    completed = subprocess.run(
        (
            "terraform",
            "plan",
            "-detailed-exitcode",
            "-input=false",
            "-no-color",
            f"-var-file={variables_path}",
            f"-out={zero_plan_path}",
        ),
        cwd=infra,
        check=False,
        capture_output=True,
        timeout=1800,
    )
    if completed.returncode != 0:
        raise ValueError("historical AKS reconciliation is not zero-change")
    zero_plan = json.loads(
        _capture(
            ("terraform", "show", "-json", str(zero_plan_path)),
            cwd=infra,
            timeout=300,
            reason="historical AKS reconciliation plan projection failed",
        )
    )
    state = json.loads(
        _capture(
            ("terraform", "state", "pull"),
            cwd=infra,
            timeout=300,
            reason="historical AKS reconciliation state readback failed",
        )
    )
    live = json.loads(_capture_aks_deployments(context))
    if not all(isinstance(value, dict) for value in (zero_plan, state, live)):
        raise ValueError("historical AKS reconciliation readback is invalid")
    _validate_historical_aks_baseline(
        state=state,
        variables=variables,
        live=live,
        plan=zero_plan,
    )
    outputs = {
        "state": work_dir / "historical-reconciliation-state.json",
        "live": work_dir / "historical-reconciliation-live.json",
        "plan": work_dir / "historical-reconciliation-zero-plan.json",
    }
    for name, path in outputs.items():
        value = {"state": state, "live": live, "plan": zero_plan}[name]
        _replace_private_json(path, value)
    return {
        "post_state_sha256": _file_digest(outputs["state"]),
        "post_variables_sha256": _file_digest(variables_path),
        "post_live_sha256": _file_digest(outputs["live"]),
        "zero_plan_sha256": _file_digest(outputs["plan"]),
    }


def _validate_historical_reconciliation_plan(
    context: dict[str, object],
    work_dir: Path,
    reconciliation: dict[str, Any],
    plan_path: Path,
) -> None:
    infra, variables_path = _stage_paths("application", context, work_dir)
    document = json.loads(
        _capture(
            ("terraform", "show", "-json", str(plan_path)),
            cwd=infra,
            timeout=300,
            reason="historical AKS reconciliation plan projection failed",
        )
    )
    if not isinstance(document, dict):
        raise TypeError("historical AKS reconciliation plan projection is invalid")
    mutations = validate_reconciliation_plan(
        document,
        variables=_private_json(variables_path, "historical AKS reconciliation variables"),
    )
    if list(mutations) != reconciliation.get("mutations"):
        raise ValueError("historical AKS reconciliation plan scope changed")


def _historical_reconciliation_receipt(
    work_dir: Path,
    context: dict[str, object],
    reconciliation: dict[str, Any],
) -> dict[str, object]:
    path = work_dir / "historical-reconciliation-receipt.json"
    receipt = _private_json(path, "historical AKS reconciliation receipt")
    required = {
        "schema_version",
        "state",
        "stage",
        "operation",
        "plan_digest",
        "runtime_profile_digest",
        "claim_digest",
        "control_plane_readback_verified",
        "effect_verified",
        "terraform_zero_change_verified",
        "mutations",
        "post_state_sha256",
        "post_variables_sha256",
        "post_live_sha256",
        "zero_plan_sha256",
        "mutation_performed",
        "subscription_ready",
        "receipt_digest",
    }
    optional = {"verification_only_recovery"}
    document = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    expected_files = {
        "post_state_sha256": work_dir / "historical-reconciliation-state.json",
        "post_variables_sha256": work_dir / "workloads.auto.tfvars.json",
        "post_live_sha256": work_dir / "historical-reconciliation-live.json",
        "zero_plan_sha256": work_dir / "historical-reconciliation-zero-plan.json",
    }
    review = _private_json(
        work_dir / "historical-reconciliation-review.json",
        "historical AKS reconciliation review",
    )
    claim = _private_json(
        work_dir / "historical-reconciliation-claim.json",
        "historical AKS reconciliation claim",
    )
    if (
        not required.issubset(receipt)
        or set(receipt) - required != set(receipt).intersection(optional)
        or receipt.get("schema_version") != "fdai.historical-aks-reconciliation-receipt.v1"
        or receipt.get("state") != "applied"
        or receipt.get("stage") != "application"
        or receipt.get("operation") != reconciliation.get("operation")
        or receipt.get("plan_digest") != review.get("plan_digest")
        or receipt.get("claim_digest") != canonical_digest(claim)
        or receipt.get("runtime_profile_digest") != _runtime_profile_digest(context)
        or receipt.get("control_plane_readback_verified") is not True
        or receipt.get("effect_verified") is not True
        or receipt.get("terraform_zero_change_verified") is not True
        or receipt.get("mutations") != reconciliation.get("mutations")
        or receipt.get("mutation_performed") is not True
        or receipt.get("subscription_ready") is not False
        or receipt.get("receipt_digest") != canonical_digest(document)
        or any(
            not isinstance(receipt.get(field), str) or receipt[field] != _file_digest(file_path)
            for field, file_path in expected_files.items()
        )
    ):
        raise ValueError("historical AKS reconciliation receipt is invalid")
    return receipt


def _plan(args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    stage = str(args.stage)
    service = getattr(args, "service", None)
    historical_baseline = (work_dir / "historical-aks-application-adoption-receipt.json").is_file()
    if stage == "runtime" and not (work_dir / "substrate-receipt.json").is_file():
        raise ValueError("runtime plan prerequisites are incomplete")
    if stage == "database":
        for prerequisite in ("runtime-receipt.json", "image-import-receipt.json"):
            if not (work_dir / prerequisite).is_file():
                raise ValueError("database plan prerequisites are incomplete")
    if stage == "application":
        context = _private_json(work_dir / "context.json", "standalone host context")
        if historical_baseline:
            _require_aks_application_baseline(work_dir, context)
        else:
            for prerequisite in (
                "substrate-receipt.json",
                "image-import-receipt.json",
                "migration-receipt.json",
            ):
                if not (work_dir / prerequisite).is_file():
                    raise ValueError("application plan prerequisites are incomplete")
            if (
                _runtime_platform(context) == "aks"
                and not (work_dir / "runtime-receipt.json").is_file()
            ):
                raise ValueError("AKS application plan requires the applied runtime plan")
            if (
                _database_placement(context) == "postgres-aks"
                and not (work_dir / "database-receipt.json").is_file()
            ):
                raise ValueError("AKS application plan requires the applied database plan")
    context = _private_json(work_dir / "context.json", "standalone host context")
    update = _service_update_record(context, work_dir, stage=stage, service=service)
    operation, reconciliation = _application_operation(
        context,
        work_dir,
        stage=stage,
        service=service,
        update=update,
    )
    if reconciliation is not None:
        raise ValueError("historical AKS reconciliation requires its retained exact review")
    if not (stage == "runtime" and update is None):
        claim_path = work_dir / f"{operation}-claim.json"
        receipt_path = work_dir / f"{operation}-receipt.json"
        if (claim_path.exists() or claim_path.is_symlink()) and not (
            receipt_path.exists() or receipt_path.is_symlink()
        ):
            raise ValueError("claimed standalone apply requires verification-only recovery")
    _managed_identity_login_from_context(context, work_dir)
    infra, variables = _stage_paths(stage, context, work_dir)
    _activate_terraform_stage(stage, context, work_dir)
    if stage == "runtime" and update is None:
        operation = _runtime_operation(work_dir, infra)
    claim_path = work_dir / f"{operation}-claim.json"
    receipt_path = work_dir / f"{operation}-receipt.json"
    if (claim_path.exists() or claim_path.is_symlink()) and not (
        receipt_path.exists() or receipt_path.is_symlink()
    ):
        raise ValueError("claimed standalone apply requires verification-only recovery")
    plan_path = work_dir / f"{operation}.tfplan"
    plan_path.unlink(missing_ok=True)
    command = [
        "terraform",
        "plan",
        "-input=false",
        "-no-color",
        f"-var-file={variables}",
        f"-out={plan_path}",
    ]
    command.extend(f"-target={target}" for target in _operation_targets(stage, context, operation))
    if update is not None:
        command.append(f"-target={_service_update_target(str(update['service']))}")
    if stage == "runtime":
        _guard_existing_runtime_node_pools(context, work_dir)
    _run(command, cwd=infra, timeout=3600, reason=f"{stage} Terraform plan failed")
    _seal_terraform_plan(plan_path)
    show = _capture(
        ("terraform", "show", "-json", str(plan_path)),
        cwd=infra,
        timeout=300,
        reason="Terraform plan projection failed",
    )
    value = json.loads(show)
    summary = _plan_summary(value)
    if update is not None:
        validate_plan_scope(summary, service=str(update["service"]))
    digest = _file_digest(plan_path)
    review: dict[str, object] = {
        "schema_version": "fdai.standalone-application-plan.v1",
        "stage": stage,
        "plan_digest": digest,
        "target_binding": context["target_binding"],
        "source_commit": context["source_commit"],
        "runtime_profile_digest": _runtime_profile_digest(context),
        "runtime_platform": _mapping(context.get("runtime_profile"), "runtime deployment profile")[
            "runtime_platform"
        ],
        "operation": operation,
        "summary": summary,
        "expires_at": _moment(datetime.now(UTC) + timedelta(hours=1)),
        "mutation_performed": False,
        "subscription_ready": False,
    }
    if update is not None:
        review["service_update"] = _service_update_review(update)
    review["review_digest"] = canonical_digest(review)
    _replace_private_json(work_dir / f"{operation}-review.json", review)
    return review


def _apply(args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    stage = str(args.stage)
    context = _private_json(work_dir / "context.json", "standalone host context")
    service = getattr(args, "service", None)
    update = _service_update_record(context, work_dir, stage=stage, service=service)
    operation, reconciliation = _application_operation(
        context,
        work_dir,
        stage=stage,
        service=service,
        update=update,
    )
    if stage == "runtime" and update is None:
        operation = (
            "runtime-cluster"
            if (work_dir / "runtime-cluster-review.json").exists()
            and not (work_dir / "runtime-cluster-receipt.json").exists()
            else "runtime"
        )
    review = _private_json(work_dir / f"{operation}-review.json", "standalone plan review")
    if update is not None and review.get("service_update") != _service_update_review(update):
        raise ValueError("AKS service update review differs from the prepared operation")
    approval = _private_json(_absolute(args.approval), "standalone plan approval")
    _validate_approval(review, approval, context=context)
    _managed_identity_login_from_context(context, work_dir)
    infra, _variables = _stage_paths(stage, context, work_dir)
    _activate_terraform_stage(stage, context, work_dir)
    plan_path = work_dir / f"{operation}.tfplan"
    if _file_digest(plan_path) != review["plan_digest"]:
        raise ValueError("standalone application plan changed before apply")
    if stage == "runtime":
        _guard_existing_runtime_node_pools(context, work_dir)
    if reconciliation is not None:
        _validate_historical_reconciliation_plan(
            context,
            work_dir,
            reconciliation,
            plan_path,
        )
    claim_path = work_dir / f"{operation}-claim.json"
    receipt_path = work_dir / f"{operation}-receipt.json"
    if receipt_path.exists():
        if reconciliation is not None:
            return _historical_reconciliation_receipt(work_dir, context, reconciliation)
        return _private_json(receipt_path, "standalone apply receipt")
    claim = {
        "schema_version": "fdai.standalone-application-claim.v1",
        "stage": stage,
        "operation": operation,
        "plan_digest": review["plan_digest"],
        "approval_digest": canonical_digest(approval),
        "idempotency_key": canonical_digest(
            {"target_binding": context["target_binding"], "plan_digest": review["plan_digest"]}
        ),
        "claimed_at": _moment(datetime.now(UTC)),
        "mutation_performed": False,
    }
    try:
        write_private_output(
            claim_path,
            json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n",
        )
    except FileExistsError as exc:
        raise ValueError(
            "standalone apply claim already exists; automatic retry is blocked"
        ) from exc
    _run(
        ("terraform", "apply", "-input=false", "-no-color", str(plan_path)),
        cwd=infra,
        timeout=7200,
        reason=f"{stage} exact apply failed; verification-only recovery is required",
    )
    effect_verified = (
        _readback_aks_service_update(context, update)
        if update is not None
        else _readback_stage(stage, context)
    )
    if not effect_verified:
        raise ValueError(f"{stage} apply effect readback is incomplete")
    if update is not None and not _service_update_zero_change(context, work_dir, update):
        raise ValueError("AKS service update did not converge to a zero-change targeted plan")
    reconciliation_evidence = (
        _historical_reconciliation_postconditions(context, work_dir, reconciliation)
        if reconciliation is not None
        else None
    )
    recovery_receipt: dict[str, object] = {
        "schema_version": "fdai.standalone-application-apply-receipt.v1",
        "state": "applied",
        "stage": stage,
        "operation": operation,
        "plan_digest": review["plan_digest"],
        "runtime_profile_digest": _runtime_profile_digest(context),
        "claim_digest": canonical_digest(claim),
        "control_plane_readback_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    if update is not None:
        recovery_receipt["service_update"] = _service_update_review(update)
        recovery_receipt["peer_state_unchanged_verified"] = True
        recovery_receipt["terraform_zero_change_verified"] = True
    if reconciliation is not None and reconciliation_evidence is not None:
        recovery_receipt.update(
            {
                "schema_version": "fdai.historical-aks-reconciliation-receipt.v1",
                "operation": operation,
                "effect_verified": True,
                "terraform_zero_change_verified": True,
                "mutations": reconciliation["mutations"],
                **reconciliation_evidence,
            }
        )
    recovery_receipt["receipt_digest"] = canonical_digest(recovery_receipt)
    _replace_private_json(receipt_path, recovery_receipt)
    return recovery_receipt


def _apply_residual(args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    stage = str(args.stage)
    context = _private_json(work_dir / "context.json", "standalone host context")
    receipt_path = work_dir / f"{stage}-receipt.json"
    if receipt_path.exists():
        return _private_json(receipt_path, "standalone residual apply receipt")
    original_review = _private_json(
        work_dir / f"{stage}-review.json", "standalone original plan review"
    )
    original_claim = _private_json(
        work_dir / f"{stage}-claim.json", "standalone original apply claim"
    )
    residual_review = _private_json(
        work_dir / f"{stage}-residual-review.json", "standalone residual plan review"
    )
    approval = _private_json(_absolute(args.approval), "standalone residual plan approval")
    _validate_approval(residual_review, approval, context=context)
    _managed_identity_login_from_context(context, work_dir)
    infra, variables = _stage_paths(stage, context, work_dir)
    _activate_terraform_stage(stage, context, work_dir)
    targets = _stage_targets(stage, context)
    if stage == "runtime":
        _guard_existing_runtime_node_pools(context, work_dir)
    return _apply_residual_plan(
        work_dir=work_dir,
        stage=stage,
        context=context,
        infra=infra,
        variables=variables,
        targets=targets,
        original_review=original_review,
        original_claim=original_claim,
        residual_review=residual_review,
        approval=approval,
        effect_readback=lambda: _readback_stage(stage, context),
    )


def _apply_historical_aks_reconciliation(
    args: argparse.Namespace, work_dir: Path
) -> dict[str, object]:
    context = _private_json(work_dir / "context.json", "standalone host context")
    if context.get("active_historical_reconciliation") is None:
        raise ValueError("no active historical AKS reconciliation is pending")
    return _apply(
        argparse.Namespace(stage="application", service=None, approval=args.approval),
        work_dir,
    )


def _recover_apply(args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    """Verify an ambiguous prior apply without repeating its mutation."""

    stage = str(args.stage)
    context = _private_json(work_dir / "context.json", "standalone host context")
    service = getattr(args, "service", None)
    update = _service_update_record(context, work_dir, stage=stage, service=service)
    operation, reconciliation = _application_operation(
        context,
        work_dir,
        stage=stage,
        service=service,
        update=update,
    )
    if (
        stage == "runtime"
        and update is None
        and (work_dir / "runtime-cluster-claim.json").exists()
        and not (work_dir / "runtime-cluster-receipt.json").exists()
    ):
        operation = "runtime-cluster"
    receipt_path = work_dir / f"{operation}-receipt.json"
    if receipt_path.exists():
        if reconciliation is not None:
            return _historical_reconciliation_receipt(work_dir, context, reconciliation)
        receipt = _private_json(receipt_path, "standalone apply receipt")
        if receipt.get("operation") == "runtime-cluster":
            return _not_required_recovery(stage)
        return receipt
    claim_path = work_dir / f"{operation}-claim.json"
    if not claim_path.exists():
        return _not_required_recovery(stage)
    review = _private_json(work_dir / f"{operation}-review.json", "standalone plan review")
    claim = _private_json(claim_path, "standalone apply claim")
    if (
        claim.get("schema_version") != "fdai.standalone-application-claim.v1"
        or claim.get("stage") != stage
        or claim.get("plan_digest") != review.get("plan_digest")
        or claim.get("idempotency_key")
        != canonical_digest(
            {
                "target_binding": context["target_binding"],
                "plan_digest": review["plan_digest"],
            }
        )
    ):
        raise ValueError("standalone apply recovery claim is invalid")
    _managed_identity_login_from_context(context, work_dir)
    infra, variables = _stage_paths(stage, context, work_dir)
    _activate_terraform_stage(stage, context, work_dir)
    if stage == "runtime" and update is None:
        operation = _runtime_operation(work_dir, infra)
        receipt_path = work_dir / f"{operation}-receipt.json"
        if receipt_path.exists():
            retained_receipt = _private_json(receipt_path, "standalone apply receipt")
            if retained_receipt.get("operation") == "runtime-cluster":
                return _not_required_recovery(stage)
            return retained_receipt
    targets = _operation_targets(stage, context, operation)
    if stage == "runtime":
        _guard_existing_runtime_node_pools(context, work_dir)
    if reconciliation is not None:
        plan_path = work_dir / f"{operation}.tfplan"
        if _file_digest(plan_path) != review.get("plan_digest"):
            raise ValueError("historical AKS reconciliation plan changed before recovery")
        _validate_historical_reconciliation_plan(
            context,
            work_dir,
            reconciliation,
            plan_path,
        )
    elif update is None:
        if _residual_claim_exists(work_dir, stage):
            return _recover_residual_apply(
                work_dir=work_dir,
                stage=stage,
                context=context,
                infra=infra,
                variables=variables,
                targets=targets,
                original_review=review,
                original_claim=claim,
                effect_readback=lambda: _readback_stage(stage, context),
            )
        residual_review = _prepare_residual_review(
            work_dir=work_dir,
            stage=stage,
            context=context,
            infra=infra,
            variables=variables,
            targets=targets,
            original_review=review,
            original_claim=claim,
        )
        if residual_review is not None:
            return residual_review
    else:
        command = [
            "terraform",
            "plan",
            "-detailed-exitcode",
            "-input=false",
            "-no-color",
            f"-var-file={variables}",
        ]
        if update is not None:
            command.append(f"-target={_service_update_target(str(update['service']))}")
        completed = subprocess.run(
            command,
            cwd=infra,
            check=False,
            capture_output=True,
            timeout=1800,
        )
        if completed.returncode != 0:
            raise ValueError("standalone apply effect is not recoverably converged")
    effect_verified = (
        _readback_aks_service_update(context, update)
        if update is not None
        else _readback_stage(stage, context)
    )
    if not effect_verified:
        raise ValueError("standalone apply effect readback is incomplete")
    reconciliation_evidence = (
        _historical_reconciliation_postconditions(context, work_dir, reconciliation)
        if reconciliation is not None
        else None
    )
    recovery_receipt: dict[str, object] = {
        "schema_version": "fdai.standalone-application-apply-receipt.v1",
        "state": "applied",
        "stage": stage,
        "plan_digest": review["plan_digest"],
        "runtime_profile_digest": _runtime_profile_digest(context),
        "claim_digest": canonical_digest(claim),
        "control_plane_readback_verified": True,
        "verification_only_recovery": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    if update is not None:
        recovery_receipt["service_update"] = _service_update_review(update)
        recovery_receipt["peer_state_unchanged_verified"] = True
        recovery_receipt["terraform_zero_change_verified"] = True
    if reconciliation is not None and reconciliation_evidence is not None:
        recovery_receipt.update(
            {
                "schema_version": "fdai.historical-aks-reconciliation-receipt.v1",
                "operation": operation,
                "effect_verified": True,
                "terraform_zero_change_verified": True,
                "mutations": reconciliation["mutations"],
                **reconciliation_evidence,
            }
        )
    recovery_receipt["receipt_digest"] = canonical_digest(recovery_receipt)
    _replace_private_json(receipt_path, recovery_receipt)
    return recovery_receipt


def _recover_historical_aks_reconciliation(
    _args: argparse.Namespace, work_dir: Path
) -> dict[str, object]:
    context = _private_json(work_dir / "context.json", "standalone host context")
    if context.get("active_historical_reconciliation") is None:
        raise ValueError("no active historical AKS reconciliation is pending")
    return _recover_apply(
        argparse.Namespace(stage="application", service=None),
        work_dir,
    )


def _import_images(_args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    context = _private_json(work_dir / "context.json", "standalone host context")
    _managed_identity_login_from_context(context, work_dir)
    if not (work_dir / "substrate-receipt.json").exists():
        raise ValueError("image import requires the applied substrate plan")
    if context.get("artifact_source") == "operator-selected-source":
        return source_application_inputs.write_source_image_import_receipt(
            context=context, work_dir=work_dir, write_json=_replace_private_json
        )
    token = _capture(
        (
            "az",
            "acr",
            "login",
            "--name",
            str(context["registry_name"]),
            "--subscription",
            str(context["subscription_id"]),
            "--expose-token",
            "--query",
            "accessToken",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        cwd=work_dir,
        timeout=120,
        reason="ACR token acquisition failed",
    ).strip()
    if not token or any(character in token for character in "\r\n"):
        raise ValueError("ACR token response is invalid")
    registry_config = work_dir / "oras-auth.json"
    registry_config.unlink(missing_ok=True)
    login = subprocess.run(
        (
            "oras",
            "login",
            "--registry-config",
            str(registry_config),
            str(context["registry_login_server"]),
            "--username",
            "00000000-0000-0000-0000-000000000000",
            "--password-stdin",
        ),
        input=token,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    token = ""
    if login.returncode != 0:
        registry_config.unlink(missing_ok=True)
        raise ValueError("ACR login failed")
    kit_root = work_dir / "kit-work/verified"
    runtime = _private_json(kit_root / "runtime/release.json", "runtime release")
    records = {
        **_mapping(runtime.get("services"), "runtime services"),
        **_mapping(runtime.get("sidecars"), "runtime sidecars"),
    }
    imported: dict[str, str] = {}
    image_root = work_dir / "oci"
    image_root.mkdir(mode=0o700, exist_ok=True)
    try:
        for name, record_raw in sorted(records.items()):
            record = _mapping(record_raw, f"runtime image {name}")
            archive = kit_root / str(record["archive"])
            layout = image_root / name
            if not layout.exists():
                layout.mkdir(mode=0o700)
                _run(
                    ("tar", "-xf", str(archive), "-C", str(layout), "--no-same-owner"),
                    cwd=work_dir,
                    timeout=300,
                    reason="OCI archive extraction failed",
                )
            digest = str(record["image_digest"])
            destination = (
                f"{context['registry_login_server']}/{name}:sha-{context['source_commit']}"
            )
            _run(
                (
                    "oras",
                    "cp",
                    "--to-registry-config",
                    str(registry_config),
                    "--from-oci-layout",
                    f"{layout}@{digest}",
                    destination,
                ),
                cwd=work_dir,
                timeout=1800,
                reason="verified OCI image import failed",
            )
            observed = _capture(
                (
                    "az",
                    "acr",
                    "manifest",
                    "show-metadata",
                    "--registry",
                    str(context["registry_name"]),
                    "--name",
                    f"{name}@{digest}",
                    "--query",
                    "digest",
                    "--output",
                    "tsv",
                    "--only-show-errors",
                ),
                cwd=work_dir,
                timeout=120,
                reason="imported OCI image readback failed",
            ).strip()
            if observed != digest:
                raise ValueError("imported OCI image digest differs from the signed release")
            imported[name] = f"{context['registry_login_server']}/{name}@{digest}"
    finally:
        registry_config.unlink(missing_ok=True)
    result: dict[str, object] = {
        "schema_version": "fdai.standalone-image-import-receipt.v1",
        "state": "imported",
        "image_digests": {name: value.rsplit("@", 1)[1] for name, value in imported.items()},
        "effect_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    result["receipt_digest"] = canonical_digest(result)
    _replace_private_json(work_dir / "image-import-receipt.json", result)
    return result


def _import_source_service_image(args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    """Import one source-built OCI archive through the retained deployment identity."""

    context = _private_json(work_dir / "context.json", "standalone host context")
    if _runtime_platform(context) != "aks":
        raise ValueError("source service image import requires an AKS installation")
    _require_source_service_update_dev_environment(work_dir)
    if not (work_dir / "substrate-receipt.json").is_file():
        _require_aks_application_baseline(work_dir, context)
    service = str(args.service)
    source_commit = str(args.source_commit)
    archive_digest = str(args.archive_sha256)
    image_digest = str(args.image_digest)
    if (
        service not in AKS_SERVICES
        or _SOURCE_COMMIT.fullmatch(source_commit) is None
        or _DIGEST.fullmatch(archive_digest) is None
        or re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest) is None
    ):
        raise ValueError("source service image identity is invalid")
    archive = _absolute(args.archive)
    verified = validate_oci_archive(
        archive,
        expected_archive_sha256=archive_digest,
        expected_manifest_digest=image_digest,
        expected_source_commit=source_commit,
        expected_platform_tag="linux-x86_64",
    )
    target_binding = context.get("target_binding")
    if not isinstance(target_binding, str) or _DIGEST.fullmatch(target_binding) is None:
        raise ValueError("source service image target binding is invalid")
    claim_path = work_dir / f"source-image-import-{service}-claim.json"
    receipt_path = work_dir / f"source-image-import-{service}-receipt.json"
    verification_only = claim_path.exists() or claim_path.is_symlink()
    approval = _private_json(_absolute(args.approval), "source service image import approval")
    approval_digest = _validate_source_image_import_approval(
        approval,
        service=service,
        source_commit=source_commit,
        archive_digest=verified.archive_sha256,
        image_digest=verified.manifest.digest,
        target_binding=target_binding,
        allow_expired=verification_only,
    )
    claim: dict[str, object] = {
        "schema_version": "fdai.source-service-image-import-claim.v1",
        "service": service,
        "source_commit": source_commit,
        "archive_sha256": verified.archive_sha256,
        "image_digest": verified.manifest.digest,
        "target_binding": target_binding,
        "approval_digest": approval_digest,
        "mutation_performed": False,
    }
    if verification_only:
        retained_claim = _private_json(claim_path, "source service image import claim")
        if retained_claim != claim:
            raise ValueError("source service image import claim differs")
    elif receipt_path.exists() or receipt_path.is_symlink():
        raise ValueError("source service image import receipt exists without its claim")

    _managed_identity_login_from_context(context, work_dir)
    token = _capture(
        (
            "az",
            "acr",
            "login",
            "--name",
            str(context["registry_name"]),
            "--subscription",
            str(context["subscription_id"]),
            "--expose-token",
            "--query",
            "accessToken",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        cwd=work_dir,
        timeout=120,
        reason="ACR token acquisition failed",
    ).strip()
    if not token or any(character in token for character in "\r\n"):
        raise ValueError("ACR token response is invalid")
    registry_config = work_dir / f"oras-auth-{service}.json"
    registry_config.unlink(missing_ok=True)
    login = subprocess.run(
        (
            "oras",
            "login",
            "--registry-config",
            str(registry_config),
            str(context["registry_login_server"]),
            "--username",
            "00000000-0000-0000-0000-000000000000",
            "--password-stdin",
        ),
        input=token,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    token = ""
    if login.returncode != 0:
        registry_config.unlink(missing_ok=True)
        raise ValueError("ACR login failed")
    try:
        if not verification_only:
            write_private_output(
                claim_path,
                json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n",
            )
            layout = work_dir / "source-oci" / f"{service}-{image_digest[7:19]}"
            layout.mkdir(mode=0o700, parents=True)
            _run(
                ("tar", "-xf", str(archive), "-C", str(layout), "--no-same-owner"),
                cwd=work_dir,
                timeout=300,
                reason="source OCI archive extraction failed",
            )
            _run(
                (
                    "oras",
                    "cp",
                    "--to-registry-config",
                    str(registry_config),
                    "--from-oci-layout",
                    f"{layout}@{image_digest}",
                    f"{context['registry_login_server']}/{service}:sha-{source_commit}",
                ),
                cwd=work_dir,
                timeout=1800,
                reason=("source OCI image import failed; verification-only recovery is required"),
            )
        observed = _capture(
            (
                "az",
                "acr",
                "manifest",
                "show-metadata",
                "--registry",
                str(context["registry_name"]),
                "--name",
                f"{service}@{image_digest}",
                "--query",
                "digest",
                "--output",
                "tsv",
                "--only-show-errors",
            ),
            cwd=work_dir,
            timeout=120,
            reason="source OCI image readback failed",
        ).strip()
        if observed != image_digest:
            raise ValueError("source OCI image digest readback differs")
    finally:
        registry_config.unlink(missing_ok=True)
    receipt: dict[str, object] = {
        "schema_version": "fdai.source-service-image-import-receipt.v1",
        "state": "imported",
        "service": service,
        "source_commit": source_commit,
        "archive_sha256": archive_digest,
        "image_digest": image_digest,
        "image": f"{context['registry_login_server']}/{service}@{image_digest}",
        "claim_digest": canonical_digest(claim),
        "effect_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    if receipt_path.exists() or receipt_path.is_symlink():
        retained_receipt = _private_json(receipt_path, "source service image import receipt")
        if retained_receipt != receipt:
            raise ValueError("source service image import receipt differs")
        return retained_receipt
    else:
        _replace_private_json(receipt_path, receipt)
    return receipt


def _validate_source_image_import_approval(
    approval: dict[str, object],
    *,
    service: str,
    source_commit: str,
    archive_digest: str,
    image_digest: str,
    target_binding: str,
    allow_expired: bool = False,
) -> str:
    digest = approval.get("approval_digest")
    document = {key: value for key, value in approval.items() if key != "approval_digest"}
    if (
        set(approval)
        != {
            "schema_version",
            "service",
            "source_commit",
            "archive_sha256",
            "image_digest",
            "target_binding",
            "actor_digest",
            "approved_at",
            "expires_at",
            "approval_digest",
        }
        or approval.get("schema_version") != "fdai.source-service-image-import-approval.v1"
        or approval.get("service") != service
        or approval.get("source_commit") != source_commit
        or approval.get("archive_sha256") != archive_digest
        or approval.get("image_digest") != image_digest
        or approval.get("target_binding") != target_binding
        or not isinstance(approval.get("actor_digest"), str)
        or _DIGEST.fullmatch(str(approval["actor_digest"])) is None
        or not isinstance(digest, str)
        or digest != canonical_digest(document)
    ):
        raise ValueError("source service image import approval is invalid")
    try:
        approved_at = datetime.fromisoformat(str(approval["approved_at"]))
        expires_at = datetime.fromisoformat(str(approval["expires_at"]))
    except ValueError as exc:
        raise ValueError("source service image import approval is invalid") from exc
    now = datetime.now(UTC)
    if (
        approved_at.tzinfo is None
        or expires_at.tzinfo is None
        or approved_at > now
        or (expires_at <= now and not allow_expired)
        or expires_at > approved_at + timedelta(hours=1)
    ):
        raise ValueError("source service image import approval is invalid or expired")
    return digest


def _service_update_context(args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    """Return sanitized retained state needed to bind one source service update."""

    context = _private_json(work_dir / "context.json", "standalone host context")
    if _runtime_platform(context) != "aks":
        raise ValueError("source service update requires an applied AKS application baseline")
    _require_aks_application_baseline(work_dir, context)
    _require_source_service_update_dev_environment(work_dir)
    service = str(args.service)
    expected = _mapping(context.get("expected_workloads"), "expected AKS workloads")
    selected = _mapping(expected.get(service), f"expected AKS workload {service}")
    active = context.get("active_service_update")
    active_review = None
    if isinstance(active, dict):
        record = _service_update_record(context, work_dir, stage="application", service=service)
        if record is not None:
            active_review = _service_update_review(record)
    return {
        "schema_version": "fdai.source-service-update-context.v1",
        "state": "verified",
        "service": service,
        "target_binding": context["target_binding"],
        "current_image": selected["image"],
        "current_source_commit": selected["source_commit"],
        "active_service_update": active_review,
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _require_source_service_update_dev_environment(work_dir: Path) -> None:
    values = _private_json(work_dir / "application.auto.tfvars.json", "application variables")
    if values.get("env") != "dev":
        raise ValueError("source service updates are supported only for retained dev installations")


def _migrate(_args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    receipt_path = work_dir / "migration-receipt.json"
    if receipt_path.exists():
        return _private_json(receipt_path, "standalone migration receipt")
    context = _private_json(work_dir / "context.json", "standalone host context")
    _managed_identity_login_from_context(context, work_dir)
    if not (work_dir / "substrate-receipt.json").exists():
        raise ValueError("database migration requires the applied substrate plan")
    if (
        _database_placement(context) == "postgres-aks"
        and not (work_dir / "database-receipt.json").exists()
    ):
        raise ValueError("database migration requires the applied postgres-aks plan")
    infra = Path(str(context["infra"]))
    bundle = infra.parent
    vault_name = _vault_name(_terraform_output(infra, "key_vault_uri"))
    dsn = _capture(
        (
            "az",
            "keyvault",
            "secret",
            "show",
            "--vault-name",
            vault_name,
            "--name",
            "fdai-state-store-dsn",
            "--query",
            "value",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        cwd=work_dir,
        timeout=120,
        reason="database migration secret is unavailable",
    ).strip()
    if not dsn or any(character in dsn for character in "\r\n"):
        raise ValueError("database migration secret is invalid")
    runtime_python = work_dir / "runtime-venv/bin/python"
    environment = {
        **os.environ,
        "FDAI_DATABASE_URL": dsn,
        "FDAI_STATE_STORE_DSN": dsn,
        "FDAI_MIGRATION_PYTHON": str(runtime_python),
        "PYTHONPATH": os.pathsep.join(
            (
                str(bundle / "services/core-control-plane/src"),
                str(bundle / "packages/service-contracts/src"),
            )
        ),
    }
    _run_env(
        (
            str(runtime_python),
            "-m",
            "alembic",
            "-c",
            str(bundle / "alembic.ini"),
            "upgrade",
            "head",
        ),
        cwd=bundle,
        env=environment,
        timeout=1200,
        reason="legacy database migration failed",
    )
    order = _capture_env(
        (str(runtime_python), str(bundle / "service-migrations/migrate.py"), "all", "order"),
        cwd=bundle,
        env=environment,
        timeout=120,
        reason="service migration order is unavailable",
    ).splitlines()
    evidence = work_dir / "migration-evidence"
    evidence.mkdir(mode=0o700, exist_ok=True)
    for service in order:
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", service):
            raise ValueError("service migration order is invalid")
        _run_env(
            (
                "/bin/sh",
                str(bundle / f"service-migrations/bin/{service}"),
                "bootstrap",
                "--evidence-output",
                str(evidence / f"{service}.json"),
                "--schema-output",
                str(evidence / f"{service}-schema.json"),
                "--rollback-reference",
                f"bundle:{context['source_commit']}:service-migrations/branches/{service}/adoption.json#rollback",
            ),
            cwd=bundle,
            env=environment,
            timeout=1200,
            reason="service database migration failed",
        )
        verify_service_evidence(evidence, service)
    _run_env(
        (
            str(runtime_python),
            str(bundle / "scripts/deployment/local/materialize-authoritative-catalogs.py"),
        ),
        cwd=bundle,
        env=environment,
        timeout=600,
        reason="authoritative catalog materialization failed",
    )
    dsn = ""
    receipt: dict[str, object] = {
        "schema_version": "fdai.standalone-migration-receipt.v1",
        "state": "migrated",
        "service_count": len(order),
        "catalogs_materialized": True,
        "effect_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    _replace_private_json(receipt_path, receipt)
    return receipt


def _initial_inventory(_args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    """Run and independently process-check one explicit full-subscription inventory."""

    receipt_path = work_dir / "initial-inventory-receipt.json"
    if receipt_path.exists():
        return _private_json(receipt_path, "standalone initial inventory receipt")
    context = _private_json(work_dir / "context.json", "standalone host context")
    _managed_identity_login_from_context(context, work_dir)
    for prerequisite in ("migration-receipt.json", "application-receipt.json"):
        if not (work_dir / prerequisite).exists():
            raise ValueError("initial inventory prerequisites are incomplete")
    if _runtime_platform(context) == "aks":
        return _initial_aks_inventory(context, work_dir, receipt_path=receipt_path)
    infra = Path(str(context["infra"]))
    bundle = infra.parent
    vault_name = _vault_name(_terraform_output(infra, "key_vault_uri"))
    dsn = _capture(
        (
            "az",
            "keyvault",
            "secret",
            "show",
            "--vault-name",
            vault_name,
            "--name",
            "fdai-state-store-dsn",
            "--query",
            "value",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        cwd=work_dir,
        timeout=120,
        reason="initial inventory database reference is unavailable",
    ).strip()
    if not dsn or any(character in dsn for character in "\r\n"):
        raise ValueError("initial inventory database reference is invalid")
    progress_url = str(context["inventory_progress_container_url"])
    if not progress_url.startswith("https://"):
        raise ValueError("initial inventory progress endpoint is invalid")
    runtime_python = work_dir / "runtime-venv/bin/python"
    attempt_id = f"attempt.{uuid.uuid4().hex}"
    environment = {
        **os.environ,
        "AZURE_CLIENT_ID": str(context["client_id"]),
        "FDAI_MI_CLIENT_ID": str(context["client_id"]),
        "FDAI_EXECUTION_VENUE": "deployed",
        "FDAI_INVENTORY_DSN": dsn,
        "FDAI_INVENTORY_SCOPES": str(context["subscription_id"]),
        "FDAI_INVENTORY_SOURCES": "arg,arm",
        "FDAI_INVENTORY_PROGRESS_CONTAINER_URL": progress_url,
        "FDAI_INVENTORY_PROGRESS_RUN_ID": f"genesis.{context['source_commit']}",
        "FDAI_INVENTORY_PROGRESS_ATTEMPT_ID": attempt_id,
        "KAFKA_BOOTSTRAP_SERVERS": _terraform_output(
            infra, "event_bus_operational_kafka_bootstrap"
        ),
        "PYTHONPATH": os.pathsep.join(
            (
                str(bundle / "services/core-control-plane/src"),
                str(bundle / "packages/service-contracts/src"),
            )
        ),
    }
    _run_env(
        (str(runtime_python), "-m", "fdai.delivery.inventory_sync_cli", "--initial"),
        cwd=bundle,
        env=environment,
        timeout=3600,
        reason="initial inventory reconciliation failed",
    )
    closure_raw = _capture_env(
        (str(runtime_python), "-m", "fdai.delivery.inventory_closure_cli"),
        cwd=bundle,
        env=environment,
        timeout=300,
        reason="initial inventory independent closure failed",
    )
    try:
        closure = json.loads(closure_raw)
    except json.JSONDecodeError as exc:
        raise ValueError("initial inventory closure receipt is invalid") from exc
    if (
        not isinstance(closure, dict)
        or closure.get("observer_distinct") is not True
        or closure.get("active_generation_matches") is not True
        or closure.get("provider_coverage_complete") is not True
        or closure.get("receipt_digest") is None
    ):
        raise ValueError("initial inventory closure receipt is incomplete")
    dsn = ""
    receipt: dict[str, object] = {
        "schema_version": "fdai.standalone-initial-inventory-receipt.v1",
        "state": "inventory-verified",
        "run_id": f"genesis.{context['source_commit']}",
        "attempt_id": attempt_id,
        "full_subscription": True,
        "resource_type_filter": False,
        "progress_persisted": True,
        "active_generation_readback_verified": True,
        "closure_receipt_digest": closure["receipt_digest"],
        "effect_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    _replace_private_json(receipt_path, receipt)
    return receipt


def _catalog_review(_args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    context = _private_json(work_dir / "context.json", "standalone host context")
    return run_catalog_review(context, work_dir, login=_managed_identity_login_from_context)


def _activate_trial(_args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    context = _private_json(work_dir / "context.json", "standalone host context")
    return activate_trial(context, work_dir, login=_managed_identity_login_from_context)


def _install_license(args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    return install_license(args, work_dir, login=_managed_identity_login_from_context)


def _verify(_args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    context = _private_json(work_dir / "context.json", "standalone host context")
    _managed_identity_login_from_context(context, work_dir)
    stages: tuple[str, ...]
    if _runtime_platform(context) == "aks":
        stages = (
            ("substrate", "runtime", "database", "application")
            if _database_placement(context) == "postgres-aks"
            else ("substrate", "runtime", "application")
        )
        if _focused_private_access(context):
            stages = ("access", *stages)
    else:
        stages = ("application",)
    for stage in stages:
        infra, variables = _stage_paths(stage, context, work_dir)
        _activate_terraform_stage(stage, context, work_dir)
        command: tuple[str, ...] = (
            "terraform",
            "plan",
            "-detailed-exitcode",
            "-input=false",
            "-no-color",
            f"-var-file={variables}",
        )
        command += tuple(f"-target={target}" for target in _stage_targets(stage, context))
        completed = subprocess.run(
            command, cwd=infra, check=False, capture_output=True, timeout=1800
        )
        if completed.returncode != 0:
            raise ValueError(f"standalone {stage} second plan is not zero-change")
    health = _readback_stage("application", context)
    if not health:
        raise ValueError("standalone application runtime health is incomplete")
    browser_console = (
        _browser_console_binding(context, work_dir)
        if _runtime_platform(context) == "aks"
        and _selects_add_on(context, ProductAddOn.READ_ONLY_CONSOLE)
        else None
    )
    receipt: dict[str, object] = {
        "schema_version": "fdai.standalone-application-verification.v1",
        "state": "verified",
        "terraform_zero_change_verified": True,
        "runtime_health_verified": True,
        "runtime_profile_digest": _runtime_profile_digest(context),
        "effect_verified": True,
        "mutation_performed": False,
        "subscription_ready": False,
    }
    if browser_console is not None:
        receipt["browser_console"] = browser_console
    receipt["receipt_digest"] = canonical_digest(receipt)
    _replace_private_json(work_dir / "application-verification-receipt.json", receipt)
    return receipt


def _browser_console_binding(context: dict[str, object], work_dir: Path) -> dict[str, str]:
    """Read and validate the public SWA and APIM bindings across their owning states."""

    _activate_terraform_stage("substrate", context, work_dir)
    substrate = Path(str(context["infra"]))
    hostname = _terraform_output(substrate, "console_default_hostname")
    resource_id = _terraform_output(substrate, "console_static_web_app_id")
    static_site_match = re.fullmatch(
        r"/subscriptions/([^/]+)/resourceGroups/[^/]+/providers/"
        r"Microsoft[.]Web/staticSites/[^/]+",
        resource_id,
        flags=re.IGNORECASE,
    )
    if static_site_match is None:
        raise ValueError("Console Static Web App resource ID is invalid")
    if static_site_match.group(1).casefold() != str(context["subscription_id"]).casefold():
        raise ValueError("Console Static Web App belongs to a different subscription")

    _activate_terraform_stage("application", context, work_dir)
    workloads = Path(str(context["workloads_infra"]))
    operator_url = _terraform_output(workloads, "browser_gateway_operator_url").rstrip("/")
    ingestion_url = _terraform_output(workloads, "browser_gateway_ingestion_url").rstrip("/")
    operator_match = re.fullmatch(
        r"https://([a-z0-9](?:[a-z0-9-]*[a-z0-9])?[.]azure-api[.]net)",
        operator_url,
    )
    if operator_match is None:
        raise ValueError("browser gateway Operator URL is invalid")
    if ingestion_url != f"{operator_url}/ingestion":
        raise ValueError("browser gateway ingestion URL is not bound to the Operator gateway")
    return {
        "console_hostname": hostname,
        "console_origin": _console_origin(hostname),
        "console_static_web_app_id": resource_id,
        "operator_api_base_url": operator_url,
        "ingestion_api_base_url": ingestion_url,
    }


def _ensure_backend(infra: Path) -> None:
    # A source resume re-extracts the snapshot, so the generated backend file must be recreated.
    backend = infra / "backend.tf"
    if not backend.exists():
        shutil.copyfile(infra / "backend.azurerm.tf.example", backend)
        backend.chmod(0o600)


def _terraform_init(work_dir: Path, context: dict[str, object]) -> None:
    infra = Path(str(context["infra"]))
    _ensure_backend(infra)
    _configure_terraform(context)
    _run(
        (
            "terraform",
            "init",
            "-input=false",
            f"-backend-config=resource_group_name={context['state_resource_group']}",
            f"-backend-config=storage_account_name={context['state_account']}",
            f"-backend-config=container_name={context['state_container']}",
            f"-backend-config=key={context['state_key']}",
        ),
        cwd=infra,
        timeout=600,
        reason="standalone application remote state initialization failed",
    )


def _stage_paths(stage: str, context: dict[str, object], work_dir: Path) -> tuple[Path, Path]:
    platform = _runtime_platform(context)
    if stage == "runtime":
        if platform != "aks":
            raise ValueError("runtime stage is only valid for AKS")
        return Path(str(context["runtime_infra"])), work_dir / "runtime.auto.tfvars.json"
    if stage == "database":
        if platform != "aks":
            raise ValueError("database stage is only valid for AKS")
        return (
            Path(str(context["database_infra"])),
            work_dir / "database.auto.tfvars.json",
        )
    if stage == "application" and platform == "aks":
        return (
            Path(str(context["workloads_infra"])),
            work_dir / "workloads.auto.tfvars.json",
        )
    return Path(str(context["infra"])), work_dir / "application.auto.tfvars.json"


def _activate_terraform_stage(stage: str, context: dict[str, object], work_dir: Path) -> None:
    platform = _runtime_platform(context)
    if stage == "runtime":
        data = context.get("runtime_terraform_data")
    elif stage == "database":
        data = context.get("database_terraform_data")
    elif stage == "application" and platform == "aks":
        data = context.get("workloads_terraform_data")
    else:
        data = context.get("terraform_data", str(work_dir / "terraform-data"))
    if not isinstance(data, str) or not data:
        raise ValueError(f"{stage} Terraform data path is unavailable")
    path = Path(data)
    if not path.is_absolute() or work_dir not in path.parents:
        raise ValueError(f"{stage} Terraform data path is outside the managed work directory")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.environ["TF_DATA_DIR"] = str(path)


def _initialize_terraform_stage(stage: str, context: dict[str, object], work_dir: Path) -> None:
    infra, _variables = _stage_paths(stage, context, work_dir)
    if stage == "runtime":
        state_key = context.get("runtime_state_key")
    elif stage == "database":
        state_key = context.get("database_state_key")
    elif stage == "application" and _runtime_platform(context) == "aks":
        state_key = context.get("workloads_state_key")
    else:
        state_key = context.get("state_key")
    if not isinstance(state_key, str) or not state_key:
        raise ValueError(f"{stage} Terraform state key is unavailable")
    _ensure_backend(infra)
    _configure_terraform(context)
    _activate_terraform_stage(stage, context, work_dir)
    _run(
        (
            "terraform",
            "init",
            "-input=false",
            f"-backend-config=resource_group_name={context['state_resource_group']}",
            f"-backend-config=storage_account_name={context['state_account']}",
            f"-backend-config=container_name={context['state_container']}",
            f"-backend-config=key={state_key}",
        ),
        cwd=infra,
        timeout=600,
        reason=f"{stage} Terraform remote state initialization failed",
    )


def _runtime_platform(context: dict[str, object]) -> str:
    value = context.get("runtime_profile")
    if value is None:
        return "container-apps"
    profile = _mapping(value, "runtime deployment profile")
    platform = profile.get("runtime_platform")
    if platform not in {"container-apps", "aks"}:
        raise ValueError("runtime deployment platform is invalid")
    return str(platform)


def _prepare_aks_kubeconfig(
    context: dict[str, object], work_dir: Path, *, resource_group: str, cluster_name: str
) -> Path:
    """Select explicit managed-host MSI authentication before any Kubernetes operation."""
    client_id = _required_guid(context, "client_id")
    subscription_id = _required_guid(context, "subscription_id")
    kubeconfig = work_dir / "aks.kubeconfig"
    if kubeconfig.exists() or kubeconfig.is_symlink():
        read_private_bytes(kubeconfig, max_bytes=1024 * 1024)
    else:
        write_private_output(kubeconfig, "")
    _run(
        (
            "az",
            "aks",
            "get-credentials",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--name",
            cluster_name,
            "--file",
            str(kubeconfig),
            "--overwrite-existing",
            "--format",
            "exec",
            "--only-show-errors",
        ),
        cwd=work_dir,
        timeout=180,
        reason="private AKS kubeconfig acquisition failed",
    )
    read_private_bytes(kubeconfig, max_bytes=1024 * 1024)
    _run(
        (
            "kubelogin",
            "convert-kubeconfig",
            "--kubeconfig",
            str(kubeconfig),
            "--login",
            "msi",
            "--client-id",
            client_id,
        ),
        cwd=work_dir,
        timeout=60,
        reason="private AKS managed-host authentication setup failed",
    )
    read_private_bytes(kubeconfig, max_bytes=1024 * 1024)
    rendered = _capture(
        (
            "kubectl",
            "config",
            "view",
            "--minify",
            "--output",
            "json",
            "--kubeconfig",
            str(kubeconfig),
        ),
        cwd=work_dir,
        timeout=30,
        reason="private AKS authentication configuration readback failed",
    )
    configuration = load_json_object(
        rendered.encode(), label="AKS authentication configuration", max_bytes=1024 * 1024
    )
    users = configuration.get("users")
    if not isinstance(users, list) or len(users) != 1 or not isinstance(users[0], dict):
        raise ValueError("AKS authentication configuration has ambiguous users")
    user = _mapping(users[0].get("user"), "AKS authentication user")
    execution = _mapping(user.get("exec"), "AKS authentication command")
    arguments = execution.get("args")
    if (
        set(user) != {"exec"}
        or execution.get("command") != "kubelogin"
        or not isinstance(arguments, list)
        or not all(isinstance(value, str) for value in arguments)
        or arguments[:1] != ["get-token"]
        or execution.get("env") not in (None, [])
        or "-l" in arguments
        or any(value.startswith(("--login=", "--client-id=")) for value in arguments)
    ):
        raise ValueError("AKS authentication must use only the selected managed identity")
    for flag, expected in (("--login", "msi"), ("--client-id", client_id)):
        if arguments.count(flag) != 1 or arguments[
            arguments.index(flag) + 1 : arguments.index(flag) + 2
        ] != [expected]:
            raise ValueError("AKS authentication does not match the managed host identity")
    return kubeconfig


def _aks_document_workloads(
    *,
    refs: dict[str, Any],
    ingestion_identity: dict[str, Any],
    worker_identity: dict[str, Any],
    application_values: dict[str, Any],
    kafka: str,
    postgres_fqdn: str,
    document_store: dict[str, Any],
    document_topics: dict[str, Any],
    console_origin: str,
) -> dict[str, dict[str, object]]:
    common = {
        "RUNTIME_ENV": application_values["env"],
        "FDAI_KAFKA_BOOTSTRAP_SERVERS": kafka,
        "FDAI_DOCUMENT_EVENT_TOPIC": document_topics["pipeline_stages"],
        "FDAI_DOCUMENT_RETRIEVAL_MODE": "lexical",
        "FDAI_ADLS_ACCOUNT_NAME": document_store["account_name"],
        "FDAI_ADLS_ACCOUNT_URL": document_store["account_url"],
        "FDAI_ADLS_SOURCE_FILE_SYSTEM": document_store["source_file_system"],
        "POSTGRES_HOST": postgres_fqdn,
    }
    api_environment = {
        **common,
        "FDAI_MI_CLIENT_ID": ingestion_identity["client_id"],
        "FDAI_INGESTION_DEPLOYMENT_ROLE": "api",
        "FDAI_INGESTION_COHOST_WORKER": "0",
        "FDAI_ENTRA_TENANT_ID": application_values["tenant_id"],
        "FDAI_API_AUDIENCE": application_values["operator_api_audience"],
        "FDAI_RBAC_READERS_GROUP_ID": application_values["rbac_readers_group_id"],
        "FDAI_RBAC_CONTRIBUTORS_GROUP_ID": application_values["rbac_contributors_group_id"],
        "FDAI_RBAC_APPROVERS_GROUP_ID": application_values["rbac_approvers_group_id"],
        "FDAI_RBAC_OWNERS_GROUP_ID": application_values["rbac_owners_group_id"],
        "FDAI_RBAC_BREAK_GLASS_GROUP_ID": application_values["rbac_break_glass_group_id"],
        "FDAI_INGESTION_CORS_ALLOW_ORIGINS": console_origin,
    }
    worker_environment = {
        **common,
        "FDAI_MI_CLIENT_ID": worker_identity["client_id"],
        "FDAI_INGESTION_DEPLOYMENT_ROLE": "worker",
        "FDAI_PANTHEON_OBJECT_TOPIC": document_topics["pantheon_objects"],
        "FDAI_ADLS_DERIVED_FILE_SYSTEM": document_store["derived_file_system"],
        "FDAI_INGESTION_WORKER_HEALTH_PORT": "8000",
        "FDAI_CLAMAV_HOST": "127.0.0.1",
        "FDAI_CLAMAV_PORT": "3310",
    }
    return {
        "document-ingestion-api": _aks_workload(
            "ingestion",
            refs,
            ingestion_identity,
            api_environment,
            {"FDAI_DATABASE_URL": "fdai-ingestion-api-dsn"},
            "/healthz",
            "/healthz",
            external=True,
            service_port=80,
        ),
        "document-processing-worker": _aks_workload(
            "worker",
            refs,
            worker_identity,
            worker_environment,
            {"FDAI_DATABASE_URL": "fdai-ingestion-worker-dsn"},
            "/ready",
            "/live",
            fs_group=101,
            sidecars={
                "clamav": {
                    "image": refs["clamav"],
                    # The image entrypoint chowns its database and exits as non-root; start
                    # clamd directly. The bundled signatures load in about 950 MiB.
                    "command": ["clamd"],
                    "args": ["--foreground=true"],
                    "cpu": "500m",
                    "memory": "2Gi",
                    "port": 3310,
                    "run_as_user": 100,
                    "run_as_group": 101,
                    "init": {
                        "name": "clamav-database",
                        "command": ["/bin/sh", "-c"],
                        "args": ["cp -a /var/lib/clamav/. /target/"],
                        "image_pull_policy": "IfNotPresent",
                        "run_as_user": 100,
                        "run_as_group": 101,
                        "writable_path": "database",
                        "mount_path": "/target",
                    },
                    "writable_paths": {
                        "database": {"mount_path": "/var/lib/clamav", "size_limit": "1Gi"},
                        "log": {"mount_path": "/var/log/clamav", "size_limit": "64Mi"},
                        "run": {"mount_path": "/run/clamav", "size_limit": "64Mi"},
                        "tmp": {"mount_path": "/tmp", "size_limit": "256Mi"},
                    },
                }
            },
        ),
    }


def _application_state_adoption(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], Path, Path, Path] | None:
    paths = tuple(
        getattr(args, name) for name in ("adoption_state", "adoption_models", "adoption_descriptor")
    )
    if not any(path is not None for path in paths):
        return None
    if not all(isinstance(path, Path) for path in paths):
        raise ValueError("standalone application state adoption inputs are incomplete")
    state_path, models_path, descriptor_path = (_absolute(path) for path in paths)
    descriptor = _private_json(descriptor_path, "application state adoption descriptor")
    expected_fields = {
        "schema_version",
        "state",
        "source_state_sha256",
        "staged_state_sha256",
        "resolved_models_sha256",
        "recovery_receipt_sha256",
        "source_commit",
        "verified_source_commit",
        "resource_name_suffix",
        "managed_resource_count",
        "removed_addresses",
        "resolved_capabilities",
        "original_state_retained",
        "remote_backend_authority_verified",
        "mutation_performed",
        "subscription_ready",
    }
    if (
        set(descriptor) != expected_fields
        or descriptor.get("schema_version") != "fdai.application-state-adoption.v1"
        or descriptor.get("state") != "staged"
        or descriptor.get("staged_state_sha256") != _file_digest(state_path)
        or descriptor.get("resolved_models_sha256") != _file_digest(models_path)
        or _DIGEST.fullmatch(str(descriptor.get("source_state_sha256", ""))) is None
        or _DIGEST.fullmatch(str(descriptor.get("recovery_receipt_sha256", ""))) is None
        or _SOURCE_COMMIT.fullmatch(str(descriptor.get("source_commit", ""))) is None
        or _SOURCE_COMMIT.fullmatch(str(descriptor.get("verified_source_commit", ""))) is None
        or re.fullmatch(r"[a-z0-9]{6}", str(descriptor.get("resource_name_suffix", ""))) is None
        or type(descriptor.get("managed_resource_count")) is not int
        or descriptor["managed_resource_count"] <= 0
        or descriptor.get("removed_addresses")
        != [
            "module.resource_group.terraform_data.ownership",
            "module.resource_group.azurerm_resource_group.primary[0]",
        ]
        or not isinstance(descriptor.get("resolved_capabilities"), list)
        or not descriptor["resolved_capabilities"]
        or descriptor.get("original_state_retained") is not True
        or descriptor.get("remote_backend_authority_verified") is not False
        or descriptor.get("mutation_performed") is not False
        or descriptor.get("subscription_ready") is not False
    ):
        raise ValueError("standalone application state adoption descriptor is invalid")
    _validate_staged_application_state(state_path, descriptor)
    return descriptor, state_path, models_path, descriptor_path


def _validate_staged_application_state(state_path: Path, descriptor: dict[str, Any]) -> None:
    state = json.loads(read_private_bytes(state_path, max_bytes=64 * 1024 * 1024))
    if (
        not isinstance(state, dict)
        or state.get("version") != 4
        or type(state.get("serial")) is not int
        or not isinstance(state.get("lineage"), str)
        or not state["lineage"]
        or not isinstance(state.get("resources"), list)
    ):
        raise ValueError("standalone application staged state is invalid")
    managed_count = 0
    owner_addresses = {
        ("module.resource_group", "terraform_data", "ownership"),
        ("module.resource_group", "azurerm_resource_group", "primary"),
    }
    for value in state["resources"]:
        if not isinstance(value, dict) or not isinstance(value.get("instances"), list):
            raise ValueError(  # noqa: TRY004 - normalize state JSON into a stable CLI error
                "standalone application staged state resource is invalid"
            )
        instances = value["instances"]
        if (
            instances
            and (
                value.get("module"),
                value.get("type"),
                value.get("name"),
            )
            in owner_addresses
        ):
            raise ValueError("standalone application staged state retains a resource-group owner")
        if value.get("mode") == "managed":
            managed_count += len(instances)
    if managed_count != descriptor["managed_resource_count"]:
        raise ValueError("standalone application staged state count differs")


def _adopt_application_state(
    work_dir: Path,
    context: dict[str, object],
    descriptor: dict[str, Any],
    state_path: Path,
    models_path: Path,
    descriptor_path: Path,
) -> None:
    infra = Path(str(context["infra"]))
    claim_path = work_dir / "application-state-adoption-claim.json"
    receipt_path = work_dir / "application-state-adoption-receipt.json"
    claim: dict[str, object] = {
        "schema_version": "fdai.application-state-adoption-claim.v1",
        "target_binding": context["target_binding"],
        "foundation_binding_digest": context["foundation_binding_digest"],
        "adoption_descriptor_digest": canonical_digest(descriptor),
        "staged_state_sha256": descriptor["staged_state_sha256"],
        "managed_resource_count": descriptor["managed_resource_count"],
        "mutation_performed": False,
    }
    if receipt_path.exists():
        retained_receipt = _private_json(receipt_path, "application state adoption receipt")
        if (
            retained_receipt.get("schema_version") != "fdai.application-state-adoption-receipt.v1"
            or retained_receipt.get("claim_digest") != canonical_digest(claim)
            or retained_receipt.get("state") != "adopted"
            or retained_receipt.get("remote_backend_authority_verified") is not True
            or retained_receipt.get("original_state_retained") is not True
        ):
            raise ValueError("retained application state adoption receipt differs")
        _verify_remote_application_state_continuity(infra, retained_receipt)
        _remove_adoption_inputs(state_path, models_path, descriptor_path)
        return
    if claim_path.exists():
        retained_claim = _private_json(claim_path, "application state adoption claim")
        if retained_claim != claim:
            raise ValueError("retained application state adoption claim differs")
    else:
        exists = _capture(
            (
                "az",
                "storage",
                "blob",
                "exists",
                "--auth-mode",
                "login",
                "--account-name",
                str(context["state_account"]),
                "--container-name",
                str(context["state_container"]),
                "--name",
                str(context["state_key"]),
                "--query",
                "exists",
                "--output",
                "tsv",
                "--only-show-errors",
            ),
            cwd=infra,
            timeout=120,
            reason="standalone application remote state existence read failed",
        ).strip()
        if exists not in {"true", "false"}:
            raise ValueError("standalone application remote state existence is invalid")
        if exists == "true":
            raise ValueError("standalone application remote state is not empty")
        write_private_output(
            claim_path,
            json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n",
        )
        _run(
            ("terraform", "state", "push", str(state_path)),
            cwd=infra,
            timeout=600,
            reason="standalone application state push failed; verification-only recovery is required",
        )
    remote_digest, remote_lineage, remote_serial = _verify_remote_application_state(
        infra, state_path, descriptor
    )
    adoption_receipt: dict[str, object] = {
        "schema_version": "fdai.application-state-adoption-receipt.v1",
        "state": "adopted",
        "claim_digest": canonical_digest(claim),
        "remote_state_sha256": remote_digest,
        "remote_state_lineage": remote_lineage,
        "remote_state_serial": remote_serial,
        "managed_resource_count": descriptor["managed_resource_count"],
        "remote_backend_authority_verified": True,
        "original_state_retained": True,
        "azure_resource_mutation_performed": False,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    write_private_output(
        receipt_path,
        json.dumps(adoption_receipt, sort_keys=True, separators=(",", ":")) + "\n",
    )
    _remove_adoption_inputs(state_path, models_path, descriptor_path)


def _verify_remote_application_state(
    infra: Path, state_path: Path, descriptor: dict[str, Any]
) -> tuple[str, str, int]:
    expected = json.loads(read_private_bytes(state_path, max_bytes=64 * 1024 * 1024))
    remote = json.loads(
        _capture(
            ("terraform", "state", "pull"),
            cwd=infra,
            timeout=300,
            reason="standalone application remote state readback failed",
        )
    )
    if not isinstance(expected, dict) or not isinstance(remote, dict):
        raise ValueError(  # noqa: TRY004 - normalize untrusted state into a stable CLI error
            "standalone application state readback is invalid"
        )
    expected_serial = expected.get("serial")
    if type(expected_serial) is not int or remote.get("serial") != expected_serial + 1:
        raise ValueError("standalone application remote state serial differs after adoption")
    remote_serial = remote["serial"]
    remote_lineage = remote.get("lineage")
    if not isinstance(remote_lineage, str) or remote_lineage != expected.get("lineage"):
        raise ValueError("standalone application remote state lineage differs after adoption")
    expected.pop("serial", None)
    remote.pop("serial", None)
    expected.pop("check_results", None)
    remote.pop("check_results", None)
    if canonical_digest(expected) != canonical_digest(remote):
        raise ValueError("standalone application remote state differs after adoption")
    count = sum(
        len(resource.get("instances", []))
        for resource in remote.get("resources", [])
        if isinstance(resource, dict) and resource.get("mode") == "managed"
    )
    if count != descriptor["managed_resource_count"]:
        raise ValueError("standalone application remote state count differs")
    return canonical_digest(remote), remote_lineage, remote_serial


def _verify_remote_application_state_continuity(infra: Path, receipt: dict[str, Any]) -> None:
    remote = json.loads(
        _capture(
            ("terraform", "state", "pull"),
            cwd=infra,
            timeout=300,
            reason="standalone application remote state continuity readback failed",
        )
    )
    if (
        not isinstance(remote, dict)
        or remote.get("lineage") != receipt.get("remote_state_lineage")
        or type(remote.get("serial")) is not int
        or type(receipt.get("remote_state_serial")) is not int
        or remote["serial"] < receipt["remote_state_serial"]
    ):
        raise ValueError("standalone application remote state continuity differs")


def _remove_adoption_inputs(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _deployment_binding(_args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    if not (work_dir / "substrate-receipt.json").is_file():
        raise ValueError("deployment binding requires verified substrate")
    context = _private_json(work_dir / "context.json", "standalone host context")
    _managed_identity_login_from_context(context, work_dir)
    installation_binding = _terraform_output(Path(str(context["infra"])), "installation_binding")
    if _runtime_platform(context) == "aks":
        _activate_terraform_stage("runtime", context, work_dir)
        runtime_name = _terraform_output(Path(str(context["runtime_infra"])), "cluster_name")
    else:
        runtime_name = _terraform_output(Path(str(context["infra"])), "core_app_name")
    deployment_binding = deployment_binding_digest(context, runtime_name)
    return {
        "schema_version": "fdai.standalone-deployment-binding.v1",
        "state": "verified",
        "deployment_binding": deployment_binding,
        "installation_binding": installation_binding,
        "terraform_name_verified": True,
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _managed_identity_login_from_context(context: dict[str, object], work_dir: Path) -> None:
    _configure_terraform(context)
    standalone_planned_outputs.bind(
        Path(str(context["infra"])),
        variables=work_dir / "application.auto.tfvars.json",
        data_dir=Path(str(context.get("terraform_data", work_dir / "terraform-data"))),
    )
    _managed_identity_login(
        str(context["subscription_id"]),
        str(context["tenant_id"]),
        str(context["client_id"]),
        str(context["principal_id"]),
        work_dir,
    )


def _managed_identity_login(
    subscription: str, tenant: str, client_id: str, principal_id: str, work_dir: Path
) -> None:
    config = work_dir / "azure"
    config.mkdir(mode=0o700, exist_ok=True)
    os.environ["AZURE_CONFIG_DIR"] = str(config)
    _run(
        (
            "az",
            "login",
            "--identity",
            "--client-id",
            client_id,
            "--allow-no-subscriptions",
            "--output",
            "none",
            "--only-show-errors",
        ),
        cwd=work_dir,
        timeout=120,
        reason="managed identity login failed",
    )
    _run(
        ("az", "account", "set", "--subscription", subscription),
        cwd=work_dir,
        timeout=60,
        reason="managed identity subscription selection failed",
    )
    value = json.loads(
        _capture(
            (
                "az",
                "account",
                "show",
                "--subscription",
                subscription,
                "--query",
                "{id:id,tenantId:tenantId}",
                "--output",
                "json",
                "--only-show-errors",
            ),
            cwd=work_dir,
            timeout=60,
            reason="managed identity target readback failed",
        )
    )
    if (
        value.get("id", "").casefold() != subscription.casefold()
        or value.get("tenantId", "").casefold() != tenant.casefold()
    ):
        raise ValueError("managed identity target differs from the Foundation handoff")
    token = _capture(
        (
            "az",
            "account",
            "get-access-token",
            "--subscription",
            subscription,
            "--resource",
            "https://management.azure.com/",
            "--query",
            "accessToken",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        cwd=work_dir,
        timeout=60,
        reason="managed identity token readback failed",
    ).strip()
    parts = token.split(".")
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (IndexError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("managed identity token readback is invalid") from exc
    if (
        not isinstance(claims, dict)
        or str(claims.get("oid", "")).casefold() != principal_id.casefold()
    ):
        raise ValueError("managed identity principal differs from the Foundation handoff")


def _validate_approval(
    review: dict[str, object],
    approval: dict[str, object],
    *,
    context: dict[str, object],
) -> None:
    expected = {
        "schema_version",
        "stage",
        "plan_digest",
        "review_digest",
        "target_binding",
        "source_commit",
        "actor_digest",
        "approved_at",
        "expires_at",
    }
    review_document = {key: value for key, value in review.items() if key != "review_digest"}
    now = datetime.now(UTC)
    try:
        review_expiry = _parse_moment(str(review["expires_at"]))
        approved_at = _parse_moment(str(approval["approved_at"]))
        approval_expiry = _parse_moment(str(approval["expires_at"]))
    except KeyError as exc:
        raise ValueError("standalone application approval is invalid or expired") from exc
    if (
        review.get("schema_version") != "fdai.standalone-application-plan.v1"
        or review.get("review_digest") != canonical_digest(review_document)
        or review.get("target_binding") != context.get("target_binding")
        or review.get("source_commit") != context.get("source_commit")
        or _runtime_profile_digest(review) != _runtime_profile_digest(context)
        or review_expiry <= now
        or set(approval) != expected
        or approval.get("schema_version") != "fdai.standalone-plan-approval.v1"
        or approval.get("stage") != review.get("stage")
        or approval.get("plan_digest") != review.get("plan_digest")
        or approval.get("review_digest") != review.get("review_digest")
        or approval.get("target_binding") != review.get("target_binding")
        or approval.get("source_commit") != review.get("source_commit")
        or not isinstance(approval.get("actor_digest"), str)
        or _DIGEST.fullmatch(str(approval["actor_digest"])) is None
        or approved_at > now + timedelta(minutes=5)
        or approval_expiry <= now
        or approval_expiry > review_expiry
        or approval_expiry > approved_at + timedelta(hours=1)
    ):
        raise ValueError("standalone application approval is invalid or expired")


def _readback_stage(stage: str, context: dict[str, object]) -> bool:
    if stage == "access":
        if not _focused_private_access(context):
            raise ValueError("focused private-access readback was not selected")
        cwd = Path(str(context["infra"]))
        if context["key_vault_private_access"] is True:
            _capture(
                (
                    "az",
                    "keyvault",
                    "secret",
                    "list",
                    "--vault-name",
                    str(context["key_vault_name"]),
                    "--output",
                    "none",
                    "--only-show-errors",
                ),
                cwd=cwd,
                timeout=120,
                reason="focused Key Vault private-access readback failed",
            )
        if context["document_storage_private_access"] is True:
            _capture(
                (
                    "az",
                    "storage",
                    "fs",
                    "list",
                    "--account-name",
                    str(context["document_storage_account_name"]),
                    "--auth-mode",
                    "login",
                    "--output",
                    "none",
                    "--only-show-errors",
                ),
                cwd=cwd,
                timeout=120,
                reason="focused document storage private-access readback failed",
            )
        return True
    if stage == "substrate":
        infra = Path(str(context["infra"]))
        value = _capture(
            (
                "az",
                "acr",
                "show",
                *_terraform_registry_selector(infra, str(context["registry_name"])),
                "--query",
                "provisioningState",
                "--output",
                "tsv",
                "--only-show-errors",
            ),
            cwd=infra,
            timeout=60,
            reason="standalone substrate ACR readback failed",
        )
        return value.strip() == "Succeeded"
    if stage == "database":
        kubeconfig = Path(str(context.get("kubeconfig", "")))
        if not kubeconfig.is_file():
            raise ValueError("AKS kubeconfig is unavailable for database readback")
        result = subprocess.run(
            (
                "kubectl",
                "rollout",
                "status",
                "statefulset/postgres",
                "--namespace",
                "fdai-data",
                "--timeout=5m",
                f"--kubeconfig={kubeconfig}",
            ),
            check=False,
            capture_output=True,
            timeout=360,
        )
        return result.returncode == 0
    if stage == "runtime":
        value = _capture(
            (
                "az",
                "aks",
                "show",
                "--resource-group",
                str(context["resource_group_name"]),
                "--name",
                _terraform_output(Path(str(context["runtime_infra"])), "cluster_name"),
                "--subscription",
                str(context["subscription_id"]),
                "--query",
                "provisioningState",
                "--output",
                "tsv",
                "--only-show-errors",
            ),
            cwd=Path(str(context["runtime_infra"])),
            timeout=60,
            reason="standalone AKS cluster readback failed",
        )
        return value.strip() == "Succeeded"
    if _runtime_platform(context) == "aks":
        kubeconfig = Path(str(context.get("kubeconfig", "")))
        if not kubeconfig.is_file():
            raise ValueError("AKS kubeconfig is unavailable for workload readback")
        expected = _mapping(context.get("expected_workloads"), "expected AKS workloads")
        # The rendered set follows the product profile; health requires it exactly.
        if "core-control-plane" not in expected:
            return False
        observed = []
        for resource in ("deployments", "pods"):
            observed.append(
                _capture(
                    (
                        "kubectl",
                        "get",
                        resource,
                        "--namespace",
                        "fdai-runtime",
                        "--output",
                        "json",
                        "--request-timeout=60s",
                        f"--kubeconfig={kubeconfig}",
                    ),
                    cwd=kubeconfig.parent,
                    timeout=90,
                    reason="AKS workload observation failed",
                )
            )
        return aks_readiness.verify_workload_health(
            deployments=observed[0],
            pods=observed[1],
            expected=expected,
            source_commit=str(context["source_commit"]),
        )
    return _container_app_health(context, Path(str(context["infra"])))


def _runtime_profile_digest(context: dict[str, object]) -> str:
    """Return the sealed profile digest, treating legacy context as the ACA default."""

    value = context.get("runtime_profile_digest")
    if value is None:
        return legacy_runtime_profile_digest(
            RuntimeDeploymentProfile.create(
                runtime_platform="container-apps",
                database_placement="postgres-flex",
            )
        )
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError("standalone runtime profile digest is invalid")
    return value


def _runtime_profile_matches(
    context: dict[str, object],
    profile: RuntimeDeploymentProfile,
) -> bool:
    retained = _runtime_profile_digest(context)
    if retained == profile.digest:
        return True
    return legacy_full_product_matches(profile, retained)


def _container_app_health(context: dict[str, object], infra: Path) -> bool:
    resource_group = _terraform_output(infra, "resource_group_name")
    names = (_terraform_output(infra, "core_app_name"),)
    for name in names:
        app = json.loads(
            _capture(
                (
                    "az",
                    "containerapp",
                    "show",
                    "--resource-group",
                    resource_group,
                    "--name",
                    name,
                    "--output",
                    "json",
                    "--only-show-errors",
                ),
                cwd=infra,
                timeout=60,
                reason="standalone runtime health readback failed",
            )
        )
        properties = app.get("properties") if isinstance(app, dict) else None
        revision = (
            properties.get("latestReadyRevisionName") if isinstance(properties, dict) else None
        )
        if (
            not isinstance(properties, dict)
            or properties.get("provisioningState") != "Succeeded"
            or not isinstance(revision, str)
            or not revision
        ):
            return False
        observed = json.loads(
            _capture(
                (
                    "az",
                    "containerapp",
                    "revision",
                    "show",
                    "--resource-group",
                    resource_group,
                    "--name",
                    name,
                    "--revision",
                    revision,
                    "--output",
                    "json",
                    "--only-show-errors",
                ),
                cwd=infra,
                timeout=60,
                reason="standalone runtime revision readback failed",
            )
        )
        revision_properties = observed.get("properties") if isinstance(observed, dict) else None
        if (
            not isinstance(revision_properties, dict)
            or revision_properties.get("active") is not True
            or revision_properties.get("provisioningState") != "Provisioned"
            or revision_properties.get("healthState") != "Healthy"
        ):
            return False
    return True


def _subnet_network_security_group(
    subnet_id: str,
    *,
    context: dict[str, object],
    cwd: Path,
) -> str:
    """Read the optional policy-attached NSG ID for one exact AKS subnet."""

    subnet_match = re.fullmatch(
        r"/subscriptions/([^/]+)/resourceGroups/[^/]+/providers/"
        r"Microsoft[.]Network/virtualNetworks/[^/]+/subnets/[^/]+",
        subnet_id,
        flags=re.IGNORECASE,
    )
    if subnet_match is None:
        raise ValueError("AKS subnet resource ID is invalid")
    subscription_id = str(context["subscription_id"])
    if subnet_match.group(1).casefold() != subscription_id.casefold():
        raise ValueError("AKS subnet belongs to a different subscription")
    value = _capture(
        (
            "az",
            "network",
            "vnet",
            "subnet",
            "show",
            "--ids",
            subnet_id,
            "--subscription",
            subscription_id,
            "--query",
            "networkSecurityGroup.id",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        cwd=cwd,
        timeout=60,
        reason="AKS subnet network security group readback failed",
    ).strip()
    if value:
        nsg_match = re.fullmatch(
            r"/subscriptions/([^/]+)/resourceGroups/[^/]+/providers/"
            r"Microsoft[.]Network/networkSecurityGroups/[^/]+",
            value,
            flags=re.IGNORECASE,
        )
        if nsg_match is None:
            raise ValueError("AKS subnet network security group ID is invalid")
        if nsg_match.group(1).casefold() != subscription_id.casefold():
            raise ValueError("AKS subnet network security group belongs to another subscription")
    return value


def _terraform_output(infra: Path, name: str) -> str:
    value = standalone_planned_outputs.read_output(
        infra, name, raw=True, reason="Terraform output readback failed"
    )
    return str(value)


def _terraform_registry_selector(infra: Path, expected_name: str) -> tuple[str, ...]:
    registry_id = _terraform_output(infra, "container_registry_id")
    return standalone_host_values.registry_selector(registry_id, expected_name)


def _terraform_json_output(infra: Path, name: str) -> object:
    return standalone_planned_outputs.read_output(
        infra, name, raw=False, reason="Terraform JSON output readback failed"
    )


def _run(command: tuple[str, ...] | list[str], *, cwd: Path, timeout: int, reason: str) -> None:
    result = subprocess.run(command, cwd=cwd, check=False, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise (
            _terraform_failure(reason, result) if "terraform" in command[0] else ValueError(reason)
        )


def _capture(command: tuple[str, ...], *, cwd: Path, timeout: int, reason: str) -> str:
    result = subprocess.run(
        command, cwd=cwd, check=False, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        raise (
            _terraform_failure(reason, result) if "terraform" in command[0] else ValueError(reason)
        )
    return result.stdout


def _run_env(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    reason: str,
) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ValueError(reason)


def _capture_env(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    reason: str,
) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ValueError(reason)
    return result.stdout


def _selected_identity(identities: dict[str, Any], name: str, selected: bool) -> dict[str, Any]:
    if not selected:
        return {}
    return _mapping(identities.get(name), f"{name.replace('_', ' ')} runtime identity")


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} is invalid")
    return {str(key): item for key, item in value.items()}


def _required_guid(value: dict[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or _GUID.fullmatch(item) is None:
        raise ValueError(f"{field} is invalid")
    return item


if __name__ == "__main__":
    raise SystemExit(main())

"""Execute standalone application checkpoints on the Bastion-reachable managed host."""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from fdai_deployment_cli.aks_readiness import verify_workload_health
from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.deployment_kit import acquire_deployment_kit
from fdai_deployment_cli.license import inspect_license
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.target import compute_target_binding
from fdai_deployment_cli.trust_roots import license_public_key_pem

_DIGEST = re.compile(r"[0-9a-f]{64}")
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_SOURCE_COMMIT = re.compile(r"[0-9a-f]{40}")
_STAGES: Final = ("substrate", "runtime", "database", "application")
_SUBSTRATE_TARGETS: Final = (
    "module.resource_group",
    "module.log_analytics",
    "azurerm_application_insights.core",
    "module.network",
    "module.container_registry",
    "module.acr_private_endpoint",
    "azurerm_role_assignment.deploy_runner_acr_push",
    "module.identity",
    "module.identity_change",
    "module.identity_resilience",
    "module.identity_finops",
    "module.command_api_identity",
    "module.inventory_identity",
    "module.canary_identity",
    "module.operator_api_identity",
    "module.isolated_executor_identity",
    "module.ingestion_identity",
    "module.ingestion_worker_identity",
    "module.key_vault",
    "azurerm_role_assignment.kv_officer_self",
    "module.kv_private_endpoint",
    "module.state_store",
    "module.postgres_public_mode_private_endpoint",
    "module.event_bus",
    "module.event_bus_auxiliary",
    "module.event_bus_private_endpoint",
    "azurerm_key_vault_secret.state_store_dsn",
    "azurerm_role_assignment.command_api_eventhubs_sender",
    "azurerm_role_assignment.command_api_eventhubs_receiver",
    "azurerm_role_assignment.inventory_reader",
    "azurerm_role_assignment.inventory_monitoring_reader",
    "azurerm_role_assignment.inventory_log_analytics_reader",
    "azurerm_role_assignment.inventory_cost_reader",
    "azurerm_role_assignment.inventory_kubernetes_reader",
    "azurerm_role_assignment.inventory_eventhubs_sender",
    "azurerm_role_assignment.inventory_stage_sender",
    "azurerm_role_assignment.inventory_eventhubs_raw_sender",
    "azurerm_role_assignment.canary_eventhubs_sender",
    "azurerm_role_assignment.inventory_kv_secrets_user",
    "azurerm_role_assignment.operator_api_kv_secrets_user",
    "azurerm_role_assignment.isolated_executor_kv_secrets_user",
    "module.document_storage",
    "azurerm_role_assignment.ingestion_document_data",
    "azurerm_role_assignment.ingestion_worker_document_data",
    "azurerm_key_vault_secret.ingestion_api_dsn",
    "azurerm_key_vault_secret.ingestion_worker_dsn",
    "azurerm_role_assignment.ingestion_api_kv_secrets_user",
    "azurerm_role_assignment.ingestion_worker_kv_secrets_user",
    "azurerm_role_assignment.ingestion_aks_eventhubs_sender",
    "azurerm_role_assignment.ingestion_worker_aks_eventhubs_receiver",
    "azurerm_role_assignment.ingestion_worker_eventhubs_sender",
    "azurerm_role_assignment.ingestion_worker_pantheon_receiver",
    "azurerm_role_assignment.executor_eventhubs_data_owner",
)


def main(argv: list[str] | None = None) -> int:
    """Run one remote checkpoint and emit only sanitized JSON."""

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
    prepare.add_argument("--entra", type=Path, required=True)
    prepare.add_argument("--adoption-state", type=Path)
    prepare.add_argument("--adoption-models", type=Path)
    prepare.add_argument("--adoption-descriptor", type=Path)
    prepare.add_argument("--runtime-platform", default="aks")
    prepare.add_argument("--database-placement", default="postgres-flex")
    prepare.add_argument("--system-node-count", type=int, default=3)
    prepare.add_argument("--system-node-sku", default=None)
    prepare.add_argument("--user-node-min-count", type=int, default=3)
    prepare.add_argument("--user-node-max-count", type=int, default=5)
    prepare.add_argument("--user-node-sku", default="Standard_D4as_v5")
    prepare.set_defaults(handler=_prepare)

    prepare_runtime = subcommands.add_parser("prepare-runtime")
    prepare_runtime.set_defaults(handler=_prepare_runtime)

    prepare_database = subcommands.add_parser("prepare-database")
    prepare_database.set_defaults(handler=_prepare_database)

    prepare_application = subcommands.add_parser("prepare-application")
    prepare_application.set_defaults(handler=_prepare_aks_application)

    plan = subcommands.add_parser("plan")
    plan.add_argument("--stage", choices=_STAGES, required=True)
    plan.set_defaults(handler=_plan)

    apply = subcommands.add_parser("apply")
    apply.add_argument("--stage", choices=_STAGES, required=True)
    apply.add_argument("--approval", type=Path, required=True)
    apply.set_defaults(handler=_apply)

    recover = subcommands.add_parser("recover-apply")
    recover.add_argument("--stage", choices=_STAGES, required=True)
    recover.set_defaults(handler=_recover_apply)

    images = subcommands.add_parser("import-images")
    images.set_defaults(handler=_import_images)

    binding = subcommands.add_parser("deployment-binding")
    binding.set_defaults(handler=_deployment_binding)

    migrate = subcommands.add_parser("migrate")
    migrate.set_defaults(handler=_migrate)

    license_command = subcommands.add_parser("install-license")
    license_command.add_argument("--image-digest", required=True)
    license_command.add_argument("--deployment-binding", required=True)
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
        print(f"standalone-host: {exc}", file=sys.stderr)
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
    entra = _private_json(_absolute(args.entra), "Entra bindings")
    runner = _mapping(handoff.get("runner"), "Foundation runner")
    state = _mapping(handoff.get("state"), "Foundation state")
    ops = _mapping(handoff.get("ops"), "Foundation operations")
    app = _mapping(handoff.get("app_resource_group"), "Foundation application group")
    subscription = _required_guid(handoff, "subscription_id")
    tenant = _required_guid(handoff, "tenant_id")
    client_id = _required_guid(runner, "client_id")
    principal_id = _required_guid(runner, "principal_id")
    runtime_profile = RuntimeDeploymentProfile.create(
        runtime_platform=str(args.runtime_platform),
        database_placement=str(args.database_placement),
        system_node_count=int(args.system_node_count),
        system_node_sku=args.system_node_sku,
        user_node_min_count=int(args.user_node_min_count),
        user_node_max_count=int(args.user_node_max_count),
        user_node_sku=str(args.user_node_sku),
    )
    foundation_binding_digest = _foundation_binding_digest(
        handoff,
        runner=runner,
        state=state,
        ops=ops,
        app=app,
    )
    entra_binding_digest = canonical_digest(entra)
    adoption = _application_state_adoption(args)
    adoption_digest = canonical_digest(adoption[0]) if adoption is not None else ""
    _managed_identity_login(subscription, tenant, client_id, principal_id, work_dir)
    retained_context = work_dir / "context.json"
    retained_variables = work_dir / "application.auto.tfvars.json"
    if retained_context.exists() or retained_variables.exists():
        if not retained_context.exists() or not retained_variables.exists():
            raise ValueError("standalone host preparation is incomplete")
        retained = _private_json(retained_context, "standalone host context")
        if (
            retained.get("source_commit") != handoff.get("source_commit")
            or retained.get("subscription_id") != subscription
            or retained.get("tenant_id") != tenant
            or retained.get("client_id") != client_id
            or retained.get("principal_id") != principal_id
            or retained.get("foundation_binding_digest") != foundation_binding_digest
            or retained.get("entra_binding_digest") != entra_binding_digest
            or retained.get("application_state_adoption_digest", "") != adoption_digest
            or _runtime_profile_digest(retained) != runtime_profile.digest
        ):
            raise ValueError("standalone host retained context differs")
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
            "mutation_performed": False,
            "subscription_ready": False,
        }
    kit_work = work_dir / "kit-work"
    _private_directory(kit_work)
    kit = acquire_deployment_kit(
        work_dir=kit_work,
        online=False,
        offline_kit=_absolute(args.kit),
    )
    if handoff.get("source_commit") != kit.source_commit:
        raise ValueError("Foundation and deployment kit source revisions differ")
    _install_runtime_support(work_dir, artifact_root=kit.materialized_root)
    infra = kit.bundle_root / "infra"
    terraform = kit.materialized_root / kit.verification.terraform_binary
    provider_mirror = kit.materialized_root / kit.verification.provider_mirror_prefix
    terraform_config = work_dir / "terraform.rc"
    expected_terraform_config = _terraform_configuration(provider_mirror)
    if not terraform_config.exists():
        write_private_output(terraform_config, expected_terraform_config)
    elif (
        read_private_bytes(terraform_config, max_bytes=16_384).decode("utf-8")
        != expected_terraform_config
    ):
        raise ValueError("retained Terraform provider configuration differs")
    backend_example = infra / "backend.azurerm.tf.example"
    backend = infra / "backend.tf"
    if not backend.exists():
        shutil.copyfile(backend_example, backend)
        backend.chmod(0o600)
    suffix = (
        str(adoption[0]["resource_name_suffix"])
        if adoption is not None
        else hashlib.sha256(str(handoff["run_digest"]).encode()).hexdigest()[:6]
    )
    region = str(handoff["region"])
    region_short = str(handoff["region_short"])
    registry = f"crfdaidev{region_short}{suffix}"
    login_server = f"{registry}.azurecr.io"
    runtime = kit.runtime.to_mapping()
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
        refs["pgvector"] = f"{login_server}/pgvector@{_required_image_digest(sidecars, 'pgvector')}"
    aks_baseline = runtime_profile.runtime_platform.value == "aks"
    operator_id = _required_guid(entra, "CURRENT_OPERATOR_OBJECT_ID")
    steward_names = (
        "Odin",
        "Thor",
        "Forseti",
        "Huginn",
        "Heimdall",
        "Vidar",
        "Var",
        "Bragi",
        "Saga",
        "Mimir",
        "Muninn",
        "Norns",
        "Njord",
        "Freyr",
    )
    values: dict[str, object] = {
        "workload": _foundation_application_workload(
            app,
            environment="dev",
            region_short=region_short,
        ),
        "env": "dev",
        "region": region,
        "region_short": region_short,
        "tenant_id": tenant,
        "deploy_runner_principal_id": principal_id,
        "postgres_admin_login": "fdaiadmin",
        "generate_initial_postgres_password": True,
        "resource_name_suffix": suffix,
        "foundation_resource_group_context_digest": str(app["foundation_context_digest"]),
        "enable_private_networking": not aks_baseline,
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
        "enable_console": True,
        "enable_operator_api": True,
        "enable_isolated_executor": True,
        "enable_document_ingestion": runtime_profile.runtime_platform.value == "aks",
        "ingestion_cohost_worker": False,
        "ingestion_cors_allow_origins": "https://localhost",
        "enable_llm": adoption is not None,
        "operator_api_audience": str(entra["OPERATOR_API_AUDIENCE"]),
        "rbac_readers_group_id": str(entra["RBAC_READERS_GROUP_ID"]),
        "rbac_contributors_group_id": str(entra["RBAC_CONTRIBUTORS_GROUP_ID"]),
        "rbac_approvers_group_id": str(entra["RBAC_APPROVERS_GROUP_ID"]),
        "rbac_owners_group_id": str(entra["RBAC_OWNERS_GROUP_ID"]),
        "rbac_break_glass_group_id": str(entra["RBAC_BREAK_GLASS_GROUP_ID"]),
        "stewardship_maintainers": operator_id,
        "stewardship_agent_bindings": {name: f"user:{operator_id}" for name in steward_names},
    }
    if adoption is not None:
        values.update(
            resolved_capabilities=adoption[0]["resolved_capabilities"],
            resolved_models_json=read_private_bytes(adoption[2], max_bytes=8 * 1024 * 1024).decode(
                "utf-8"
            ),
            resolved_models_sha256=adoption[0]["resolved_models_sha256"],
        )
    context: dict[str, object] = {
        "source_commit": kit.source_commit,
        "target_binding": compute_target_binding(
            tenant_id=tenant,
            subscription_id=subscription,
        ),
        "subscription_id": subscription,
        "tenant_id": tenant,
        "client_id": client_id,
        "principal_id": principal_id,
        "foundation_binding_digest": foundation_binding_digest,
        "entra_binding_digest": entra_binding_digest,
        "application_state_adoption_digest": adoption_digest,
        "state_resource_group": str(ops["resource_group_name"]),
        "state_account": str(state["account_name"]),
        "state_container": str(state["container_name"]),
        "state_key": f"fdai-{values['env']}.tfstate",
        "kit_manifest_digest": kit.verification.manifest_digest,
        "runtime_release_digest": kit.runtime.digest,
        "runtime_profile": runtime_profile.to_mapping(),
        "runtime_profile_digest": runtime_profile.digest,
        "registry_name": registry,
        "registry_login_server": login_server,
        "image_refs": refs,
        "infra": str(infra),
        "terraform": str(terraform),
        "provider_mirror": str(provider_mirror),
        "kit_bin": str(kit.materialized_root / "bin"),
        "terraform_config": str(terraform_config),
        "terraform_data": str(work_dir / "terraform-data"),
    }
    _replace_private_json(work_dir / "application.auto.tfvars.json", values)
    _replace_private_json(work_dir / "context.json", context)
    _terraform_init(work_dir, context)
    if adoption is not None:
        _adopt_application_state(work_dir, context, *adoption)
    return {
        "schema_version": "fdai.standalone-host-prepare.v1",
        "state": "prepared",
        "source_commit": kit.source_commit,
        "kit_manifest_digest": kit.verification.manifest_digest,
        "runtime_release_digest": kit.runtime.digest,
        "runtime_profile_digest": runtime_profile.digest,
        "application_state_adopted": adoption is not None,
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
    principals = {
        str(_mapping(identities.get(name), f"{name} runtime identity")["principal_id"])
        for name in ("core", "operator", "executor", "inventory")
    }
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


def _aks_core_semantic_environment(
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
        "operational_history_container_url": _terraform_output(
            substrate, "operational_history_container_url"
        ),
        "document_store": _terraform_json_output(substrate, "document_storage_binding"),
        "document_topics": _terraform_json_output(substrate, "document_event_topics"),
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
    cluster_name = _terraform_output(runtime_infra, "cluster_name")
    oidc_issuer_url = _terraform_output(runtime_infra, "oidc_issuer_url")
    kubeconfig = _prepare_aks_kubeconfig(
        context, work_dir, resource_group=resource_group, cluster_name=cluster_name
    )
    application_values = _private_json(
        work_dir / "application.auto.tfvars.json", "application variables"
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
    operator_identity = _mapping(identities.get("operator"), "operator runtime identity")
    command_identity = _mapping(identities.get("command"), "command runtime identity")
    executor_identity = _mapping(identities.get("executor"), "executor runtime identity")
    inventory_identity = _mapping(identities.get("inventory"), "inventory runtime identity")
    canary_identity = _mapping(identities.get("canary"), "canary runtime identity")
    ingestion_identity = _mapping(identities.get("ingestion"), "ingestion runtime identity")
    ingestion_worker_identity = _mapping(
        identities.get("ingestion_worker"), "ingestion worker runtime identity"
    )
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
    }
    core_environment.update(
        _aks_core_semantic_environment(
            application_values=application_values,
            substrate_outputs=substrate_outputs,
            semantic_topics=semantic_topics,
        )
    )
    operator_environment = {
        "AZURE_CLIENT_ID": operator_identity["client_id"],
        "FDAI_COMMAND_MI_CLIENT_ID": command_identity["client_id"],
        "FDAI_ENTRA_TENANT_ID": context["tenant_id"],
        "FDAI_API_AUDIENCE": application_values["operator_api_audience"],
        "FDAI_RBAC_READERS_GROUP_ID": application_values["rbac_readers_group_id"],
        "FDAI_RBAC_CONTRIBUTORS_GROUP_ID": application_values["rbac_contributors_group_id"],
        "FDAI_RBAC_APPROVERS_GROUP_ID": application_values["rbac_approvers_group_id"],
        "FDAI_RBAC_OWNERS_GROUP_ID": application_values["rbac_owners_group_id"],
        "FDAI_RBAC_BREAK_GLASS_GROUP_ID": application_values["rbac_break_glass_group_id"],
        "FDAI_STEWARDSHIP_REQUIRE_BINDINGS": "1",
        "FDAI_MAINTAINERS": application_values["stewardship_maintainers"],
        "FDAI_KAFKA_BOOTSTRAP_SERVERS": core_environment["KAFKA_BOOTSTRAP_SERVERS"],
        "KAFKA_TOPIC_EVENTS": core_environment["KAFKA_TOPIC_EVENTS"],
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": str(semantic_topics[0]),
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": str(semantic_topics[1]),
        "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC": substrate_outputs["semantic_physical"],
        "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": str(semantic_topics[2]),
    }
    operator_environment.update(
        {
            f"FDAI_STEWARD_{name.upper()}": binding
            for name, binding in _mapping(
                application_values["stewardship_agent_bindings"],
                "stewardship bindings",
            ).items()
        }
    )
    dsn_secret = {"FDAI_STATE_STORE_DSN": "fdai-state-store-dsn"}
    refs = _mapping(context.get("image_refs"), "runtime image references")
    workloads = {
        "core-control-plane": _aks_workload(
            "core", refs, core_identity, core_environment, dsn_secret, "/ready", "/live"
        ),
        "operator-service": _aks_workload(
            "operator",
            refs,
            operator_identity,
            operator_environment,
            {"FDAI_DATABASE_URL": "fdai-state-store-dsn"},
            "/healthz",
            "/healthz",
            external=True,
            additional_identities={"command": command_identity},
        ),
        "isolated-executor": _aks_workload(
            "executor",
            refs,
            executor_identity,
            {
                "AZURE_CLIENT_ID": executor_identity["client_id"],
                "RUNTIME_ENV": application_values["env"],
                "FDAI_ISOLATED_EXECUTOR_DEPLOYED": "1",
                "FDAI_ISOLATED_EXECUTOR_MI_CLIENT_ID": executor_identity["client_id"],
                "KAFKA_BOOTSTRAP_SERVERS": core_environment["KAFKA_BOOTSTRAP_SERVERS"],
                "FDAI_ISOLATED_EXECUTOR_HEALTH_PORT": "8000",
            },
            {
                "FDAI_STATE_STORE_DSN": "fdai-state-store-dsn",
                "FDAI_RESOURCE_LOCK_DSN": "fdai-state-store-dsn",
            },
            "/ready",
            "/live",
        ),
    }
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
            document_topics=_mapping(substrate_outputs["document_topics"], "document event topics"),
        )
    )
    inventory_environment = {
        **core_environment,
        "AZURE_CLIENT_ID": inventory_identity["client_id"],
        "FDAI_MI_CLIENT_ID": inventory_identity["client_id"],
    }
    scheduled_jobs = {
        "analyzer": _aks_job(
            refs,
            inventory_identity,
            ["python", "-m", "fdai.delivery.analyzer_tick_cli"],
            "* * * * *",
            {
                **inventory_environment,
                "FDAI_ANALYZER_SCHEDULING_MODE": "kubernetes_cronjob",
                "FDAI_TRACE_CONTINUITY_LOOKBACK_SECONDS": "900",
            },
            {
                "FDAI_STATE_STORE_DSN": "fdai-state-store-dsn",
                "FDAI_INVENTORY_DSN": "fdai-state-store-dsn",
            },
            component="analysis",
            deadline_seconds=240,
        ),
        "canary": _aks_job(
            refs,
            canary_identity,
            ["python", "-m", "fdai.delivery.canary_cli"],
            "*/5 * * * *",
            {
                "AZURE_CLIENT_ID": canary_identity["client_id"],
                "KAFKA_BOOTSTRAP_SERVERS": substrate_outputs["operational_kafka"],
                "FDAI_CANARY_TOPIC": "fdai.control.canary",
                "FDAI_MI_CLIENT_ID": canary_identity["client_id"],
            },
            {},
            component="canary",
            deadline_seconds=120,
            retry_limit=2,
        ),
        "inventory": _aks_job(
            refs,
            inventory_identity,
            ["python", "-m", "fdai.delivery.inventory_sync_cli"],
            "* * * * *",
            {
                **inventory_environment,
                "FDAI_INVENTORY_SCOPES": context["subscription_id"],
                "FDAI_INVENTORY_SOURCES": "arg,arm",
                "FDAI_MONITOR_WORKSPACE_ID": substrate_outputs["workspace"],
            },
            {"FDAI_INVENTORY_DSN": "fdai-state-store-dsn"},
            component="inventory",
            deadline_seconds=900,
        ),
        "observation-campaign": _aks_job(
            refs,
            inventory_identity,
            ["python", "-m", "fdai.delivery.observation_campaign_cli"],
            "* * * * *",
            {
                **inventory_environment,
                "FDAI_OBSERVATION_SCOPES": context["subscription_id"],
            },
            {"FDAI_OBSERVATION_DSN": "fdai-state-store-dsn"},
            component="observation",
            deadline_seconds=900,
        ),
    }
    operational_history_container_url = str(substrate_outputs["operational_history_container_url"])
    if operational_history_container_url:
        scheduled_jobs["operational-history-lifecycle"] = _aks_job(
            refs,
            inventory_identity,
            ["python", "-m", "fdai.delivery.operational_history_lifecycle_runner"],
            "0 * * * *",
            {
                **inventory_environment,
                "FDAI_OPERATIONAL_HISTORY_CONTAINER_URL": operational_history_container_url,
                "FDAI_OPERATIONAL_HISTORY_MODE": "shadow",
                "FDAI_OPERATIONAL_HISTORY_MAX_PARTITIONS": "32",
            },
            {"FDAI_DATABASE_URL": "fdai-state-store-dsn"},
            component="operational-history",
            deadline_seconds=1800,
            retry_limit=0,
        )
    workloads_infra = substrate / "runtimes/aks/workloads"
    values = {
        "kubeconfig_path": str(kubeconfig),
        "tenant_id": context["tenant_id"],
        "oidc_issuer_url": oidc_issuer_url,
        "key_vault_name": _vault_name(str(substrate_outputs["key_vault_uri"])),
        "workloads": workloads,
        "scheduled_jobs": scheduled_jobs,
        "tags": {"fdai.io/source-commit": context["source_commit"]},
    }
    context.update(
        workloads_infra=str(workloads_infra),
        workloads_state_key=f"fdai-{application_values['env']}-aks-workloads.tfstate",
        workloads_terraform_data=str(work_dir / "terraform-data-workloads"),
        kubeconfig=str(kubeconfig),
        expected_workloads={
            name: {key: workload[key] for key in ("image", "replicas", "max_replicas")}
            for name, workload in workloads.items()
        },
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


def _plan(args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    stage = str(args.stage)
    if stage == "runtime" and not (work_dir / "substrate-receipt.json").is_file():
        raise ValueError("runtime plan prerequisites are incomplete")
    if stage == "database":
        for prerequisite in ("runtime-receipt.json", "image-import-receipt.json"):
            if not (work_dir / prerequisite).is_file():
                raise ValueError("database plan prerequisites are incomplete")
    if stage == "application":
        for prerequisite in (
            "substrate-receipt.json",
            "image-import-receipt.json",
            "migration-receipt.json",
        ):
            if not (work_dir / prerequisite).is_file():
                raise ValueError("application plan prerequisites are incomplete")
        context = _private_json(work_dir / "context.json", "standalone host context")
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
    _managed_identity_login_from_context(context, work_dir)
    infra, variables = _stage_paths(stage, context, work_dir)
    _activate_terraform_stage(stage, context, work_dir)
    plan_path = work_dir / f"{stage}.tfplan"
    plan_path.unlink(missing_ok=True)
    command = [
        "terraform",
        "plan",
        "-input=false",
        "-no-color",
        f"-var-file={variables}",
        f"-out={plan_path}",
    ]
    if stage == "substrate":
        command.extend(f"-target={target}" for target in _substrate_targets(context))
    _run(command, cwd=infra, timeout=3600, reason=f"{stage} Terraform plan failed")
    show = _capture(
        ("terraform", "show", "-json", str(plan_path)),
        cwd=infra,
        timeout=300,
        reason="Terraform plan projection failed",
    )
    value = json.loads(show)
    summary = _plan_summary(value)
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
        "summary": summary,
        "expires_at": _moment(datetime.now(UTC) + timedelta(hours=1)),
        "mutation_performed": False,
        "subscription_ready": False,
    }
    review["review_digest"] = canonical_digest(review)
    _replace_private_json(work_dir / f"{stage}-review.json", review)
    return review


def _apply(args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    stage = str(args.stage)
    context = _private_json(work_dir / "context.json", "standalone host context")
    review = _private_json(work_dir / f"{stage}-review.json", "standalone plan review")
    approval = _private_json(_absolute(args.approval), "standalone plan approval")
    _validate_approval(review, approval, context=context)
    _managed_identity_login_from_context(context, work_dir)
    infra, _variables = _stage_paths(stage, context, work_dir)
    _activate_terraform_stage(stage, context, work_dir)
    plan_path = work_dir / f"{stage}.tfplan"
    if _file_digest(plan_path) != review["plan_digest"]:
        raise ValueError("standalone application plan changed before apply")
    claim_path = work_dir / f"{stage}-claim.json"
    receipt_path = work_dir / f"{stage}-receipt.json"
    if receipt_path.exists():
        return _private_json(receipt_path, "standalone apply receipt")
    claim = {
        "schema_version": "fdai.standalone-application-claim.v1",
        "stage": stage,
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
    effect_verified = _readback_stage(stage, context)
    if not effect_verified:
        raise ValueError(f"{stage} apply effect readback is incomplete")
    receipt: dict[str, object] = {
        "schema_version": "fdai.standalone-application-apply-receipt.v1",
        "state": "applied",
        "stage": stage,
        "plan_digest": review["plan_digest"],
        "runtime_profile_digest": _runtime_profile_digest(context),
        "claim_digest": canonical_digest(claim),
        "control_plane_readback_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    _replace_private_json(receipt_path, receipt)
    return receipt


def _recover_apply(args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    """Verify an ambiguous prior apply without repeating its mutation."""

    stage = str(args.stage)
    receipt_path = work_dir / f"{stage}-receipt.json"
    if receipt_path.exists():
        return _private_json(receipt_path, "standalone apply receipt")
    claim_path = work_dir / f"{stage}-claim.json"
    if not claim_path.exists():
        return {
            "schema_version": "fdai.standalone-application-recovery.v1",
            "state": "not-required",
            "stage": stage,
            "mutation_performed": False,
            "subscription_ready": False,
        }
    context = _private_json(work_dir / "context.json", "standalone host context")
    review = _private_json(work_dir / f"{stage}-review.json", "standalone plan review")
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
    command = [
        "terraform",
        "plan",
        "-detailed-exitcode",
        "-input=false",
        "-no-color",
        f"-var-file={variables}",
    ]
    if stage == "substrate":
        command.extend(f"-target={target}" for target in _substrate_targets(context))
    completed = subprocess.run(command, cwd=infra, check=False, capture_output=True, timeout=1800)
    if completed.returncode != 0:
        raise ValueError("standalone apply effect is not recoverably converged")
    effect_verified = _readback_stage(stage, context)
    if not effect_verified:
        raise ValueError("standalone apply effect readback is incomplete")
    receipt: dict[str, object] = {
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
    receipt["receipt_digest"] = canonical_digest(receipt)
    _replace_private_json(receipt_path, receipt)
    return receipt


def _import_images(_args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    context = _private_json(work_dir / "context.json", "standalone host context")
    _managed_identity_login_from_context(context, work_dir)
    if not (work_dir / "substrate-receipt.json").exists():
        raise ValueError("image import requires the applied substrate plan")
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
                    "--registry-config",
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
        (evidence / f"{service}.json").chmod(0o600)
        (evidence / f"{service}-schema.json").chmod(0o600)
        migration_evidence = _private_json(
            evidence / f"{service}.json", f"{service} migration evidence"
        )
        schema_evidence = _private_json(
            evidence / f"{service}-schema.json", f"{service} migration schema"
        )
        if (
            migration_evidence.get("service_id") != service
            or not isinstance(migration_evidence.get("observed_schema_fingerprint"), str)
            or schema_evidence.get("schema_version") != 1
            or schema_evidence.get("service_id") != service
            or schema_evidence.get("observed_schema_fingerprint")
            != migration_evidence.get("observed_schema_fingerprint")
        ):
            raise ValueError("service migration evidence is incomplete")
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


def _install_license(args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    context = _private_json(work_dir / "context.json", "standalone host context")
    _managed_identity_login_from_context(context, work_dir)
    token = sys.stdin.read(8193)
    if len(token) > 8192 or token != token.strip():
        raise ValueError("license token stdin is invalid")
    inspect_license(
        token,
        public_key_pem=license_public_key_pem(),
        expected_image_digest=args.image_digest,
        expected_tenant_binding=args.deployment_binding,
    )
    token_digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    infra = Path(str(context["infra"]))
    vault_uri = _terraform_output(infra, "key_vault_uri")
    vault_name = _vault_name(vault_uri)
    result = subprocess.run(
        (
            "az",
            "keyvault",
            "secret",
            "set",
            "--vault-name",
            vault_name,
            "--name",
            "fdai-capability-license",
            "--file",
            "/dev/stdin",
            "--encoding",
            "utf-8",
            "--query",
            "id",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        input=token,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    token = ""
    if result.returncode != 0:
        raise ValueError("license token Key Vault installation failed")
    versioned_secret_id = result.stdout.strip()
    match = re.fullmatch(
        rf"https://{re.escape(vault_name)}[.]vault[.]azure[.]net/secrets/"
        r"fdai-capability-license/([0-9a-f]{32})",
        versioned_secret_id,
    )
    if match is None:
        raise ValueError("license token Key Vault readback is invalid")
    readback = _capture(
        (
            "az",
            "keyvault",
            "secret",
            "show",
            "--id",
            versioned_secret_id,
            "--query",
            "value",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        cwd=work_dir,
        timeout=120,
        reason="license token Key Vault content readback failed",
    ).strip()
    inspect_license(
        readback,
        public_key_pem=license_public_key_pem(),
        expected_image_digest=args.image_digest,
        expected_tenant_binding=args.deployment_binding,
    )
    if hashlib.sha256(readback.encode("ascii")).hexdigest() != token_digest:
        raise ValueError("license token Key Vault content differs")
    secret_id = versioned_secret_id.rsplit("/", 1)[0]
    values = _private_json(work_dir / "application.auto.tfvars.json", "application variables")
    values["license"] = {
        "token_secret_id": secret_id,
        "image_digest": args.image_digest,
        "deployment_digest": args.deployment_binding,
        "token_revision": hashlib.sha256(
            f"{args.image_digest}:{args.deployment_binding}".encode()
        ).hexdigest(),
    }
    _replace_private_json(work_dir / "application.auto.tfvars.json", values)
    return {
        "schema_version": "fdai.standalone-license-installation.v1",
        "state": "installed",
        "secret_metadata_verified": True,
        "secret_content_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }


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
        if stage == "substrate":
            command += tuple(f"-target={target}" for target in _substrate_targets(context))
        completed = subprocess.run(
            command, cwd=infra, check=False, capture_output=True, timeout=1800
        )
        if completed.returncode != 0:
            raise ValueError(f"standalone {stage} second plan is not zero-change")
    health = _readback_stage("application", context)
    if not health:
        raise ValueError("standalone application runtime health is incomplete")
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
    receipt["receipt_digest"] = canonical_digest(receipt)
    _replace_private_json(work_dir / "application-verification-receipt.json", receipt)
    return receipt


def _terraform_init(work_dir: Path, context: dict[str, object]) -> None:
    infra = Path(str(context["infra"]))
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
    backend_example = infra / "backend.azurerm.tf.example"
    backend = infra / "backend.tf"
    if not backend.exists():
        shutil.copyfile(backend_example, backend)
        backend.chmod(0o600)
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


def _database_placement(context: dict[str, object]) -> str:
    value = context.get("runtime_profile")
    if value is None:
        return "postgres-flex"
    profile = _mapping(value, "runtime deployment profile")
    placement = profile.get("database_placement")
    if placement not in {"postgres-flex", "postgres-aks"}:
        raise ValueError("database placement is invalid")
    return str(placement)


def _substrate_targets(context: dict[str, object]) -> tuple[str, ...]:
    if _database_placement(context) == "postgres-flex":
        return _SUBSTRATE_TARGETS
    excluded = {
        "module.state_store",
        "module.postgres_public_mode_private_endpoint",
        "azurerm_key_vault_secret.state_store_dsn",
        "azurerm_role_assignment.inventory_kv_secrets_user",
        "azurerm_role_assignment.operator_api_kv_secrets_user",
        "azurerm_role_assignment.isolated_executor_kv_secrets_user",
    }
    return tuple(target for target in _SUBSTRATE_TARGETS if target not in excluded)


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


def _aks_workload(
    component: str,
    refs: dict[str, Any],
    identity: dict[str, Any],
    environment: dict[str, object],
    secret_environment: dict[str, str],
    readiness_path: str,
    liveness_path: str,
    *,
    external: bool = False,
    additional_identities: dict[str, dict[str, Any]] | None = None,
    sidecars: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    image_names = {
        "core": "core-control-plane",
        "operator": "operator-service",
        "executor": "isolated-executor",
        "ingestion": "document-ingestion-api",
        "worker": "document-processing-worker",
    }
    image_name = image_names.get(component)
    if image_name is None or not isinstance(refs.get(image_name), str):
        raise ValueError(f"AKS {component} workload image is unavailable")
    cpu, memory = {
        "core": ("1000m", "2Gi"),
        "operator": ("500m", "1Gi"),
        "executor": ("500m", "1Gi"),
        "ingestion": ("500m", "1Gi"),
        "worker": ("500m", "1Gi"),
    }[component]
    runtime_environment = {name: str(value) for name, value in environment.items()}
    runtime_environment["FDAI_EXECUTION_VENUE"] = "deployed"
    database_role = {
        "operator": "fdai_operator",
        "executor": "fdai_executor",
        "ingestion": "fdai_ingestion_api",
        "worker": "fdai_ingestion_worker",
    }.get(component)
    if database_role is not None:
        runtime_environment["FDAI_DATABASE_ROLE"] = database_role
        runtime_environment["PGOPTIONS"] = f"-c role={database_role}"
    return {
        "component": component,
        "image": refs[image_name],
        "identity_resource_id": identity["resource_id"],
        "identity_client_id": identity["client_id"],
        "additional_identities": additional_identities or {},
        "command": [],
        "args": [],
        "replicas": 2,
        "max_replicas": 4,
        "cpu": cpu,
        "memory": memory,
        "port": 8000,
        "external": external,
        "readiness_path": readiness_path,
        "liveness_path": liveness_path,
        "environment": runtime_environment,
        "secret_environment": secret_environment,
        "sidecars": sidecars or {},
    }


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
        "FDAI_INGESTION_CORS_ALLOW_ORIGINS": application_values["ingestion_cors_allow_origins"],
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
    database_secret = {"FDAI_DATABASE_URL": "fdai-state-store-dsn"}
    return {
        "document-ingestion-api": _aks_workload(
            "ingestion",
            refs,
            ingestion_identity,
            api_environment,
            database_secret,
            "/healthz",
            "/healthz",
            external=True,
        ),
        "document-processing-worker": _aks_workload(
            "worker",
            refs,
            worker_identity,
            worker_environment,
            database_secret,
            "/ready",
            "/live",
            sidecars={
                "clamav": {
                    "image": refs["clamav"],
                    "cpu": "500m",
                    "memory": "1Gi",
                    "port": 3310,
                    "writable_paths": {
                        "database": {"mount_path": "/var/lib/clamav", "size_limit": "1Gi"},
                        "run": {"mount_path": "/run/clamav", "size_limit": "64Mi"},
                        "tmp": {"mount_path": "/tmp", "size_limit": "256Mi"},
                    },
                }
            },
        ),
    }


def _aks_job(
    refs: dict[str, Any],
    identity: dict[str, Any],
    command: list[str],
    schedule: str,
    environment: dict[str, object],
    secret_environment: dict[str, str],
    *,
    component: str,
    deadline_seconds: int,
    retry_limit: int = 1,
) -> dict[str, object]:
    image = refs.get("core-control-plane")
    if not isinstance(image, str):
        raise TypeError("AKS scheduled job image is unavailable")
    return {
        "component": component,
        "image": image,
        "identity_resource_id": identity["resource_id"],
        "identity_client_id": identity["client_id"],
        "command": command,
        "args": [],
        "schedule": schedule,
        "deadline_seconds": deadline_seconds,
        "retry_limit": retry_limit,
        "cpu": "500m",
        "memory": "1Gi",
        "environment": {name: str(value) for name, value in environment.items()},
        "secret_environment": secret_environment,
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


def _install_runtime_support(work_dir: Path, *, artifact_root: Path) -> None:
    """Install already-admitted local support without selecting its trust mechanism."""
    environment = work_dir / "runtime-venv"
    if (environment / "bin/python").exists():
        return
    wheels = sorted((artifact_root / "support/python").rglob("*.whl"))
    if not wheels:
        raise ValueError("runtime migration support wheelhouse is empty")
    _run(
        (sys.executable, "-m", "venv", str(environment)),
        cwd=work_dir,
        timeout=120,
        reason="runtime migration environment creation failed",
    )
    _run(
        (
            str(environment / "bin/pip"),
            "install",
            "--no-index",
            "--no-cache-dir",
            *(str(wheel) for wheel in wheels),
        ),
        cwd=work_dir,
        timeout=900,
        reason="runtime migration support installation failed",
    )


def _deployment_binding(_args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    if not (work_dir / "substrate-receipt.json").is_file():
        raise ValueError("deployment binding requires verified substrate")
    context = _private_json(work_dir / "context.json", "standalone host context")
    _managed_identity_login_from_context(context, work_dir)
    if _runtime_platform(context) == "aks":
        _activate_terraform_stage("runtime", context, work_dir)
        runtime_name = _terraform_output(Path(str(context["runtime_infra"])), "cluster_name")
    else:
        runtime_name = _terraform_output(Path(str(context["infra"])), "core_app_name")
    if re.fullmatch(r"[a-z][a-z0-9-]{1,62}", runtime_name) is None:
        raise ValueError("Terraform runtime name is invalid")
    deployment_binding = hashlib.sha256(
        (f"{context['tenant_id']}\0{context['subscription_id']}\0{runtime_name}").encode()
    ).hexdigest()
    return {
        "schema_version": "fdai.standalone-deployment-binding.v1",
        "state": "verified",
        "deployment_binding": deployment_binding,
        "terraform_name_verified": True,
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _managed_identity_login_from_context(context: dict[str, object], work_dir: Path) -> None:
    _configure_terraform(context)
    _managed_identity_login(
        str(context["subscription_id"]),
        str(context["tenant_id"]),
        str(context["client_id"]),
        str(context["principal_id"]),
        work_dir,
    )


def _configure_terraform(context: dict[str, object]) -> None:
    terraform = Path(str(context["terraform"]))
    provider_mirror = Path(str(context["provider_mirror"]))
    config = Path(str(context["terraform_config"]))
    data = Path(str(context["terraform_data"]))
    if not terraform.is_file() or not config.is_file():
        raise ValueError("verified Terraform execution context is unavailable")
    if read_private_bytes(config, max_bytes=16_384).decode("utf-8") != _terraform_configuration(
        provider_mirror
    ):
        raise ValueError("Terraform provider configuration differs from the verified kit")
    data.mkdir(mode=0o700, exist_ok=True)
    kit_bin = Path(str(context.get("kit_bin", terraform.parent)))
    os.environ["PATH"] = os.pathsep.join(
        (str(terraform.parent), str(kit_bin), "/usr/local/bin", "/usr/bin", "/bin")
    )
    os.environ["TF_CLI_CONFIG_FILE"] = str(config)
    os.environ["TF_DATA_DIR"] = str(data)
    os.environ["TF_IN_AUTOMATION"] = "1"
    os.environ["ARM_SUBSCRIPTION_ID"] = str(context["subscription_id"])
    os.environ["ARM_TENANT_ID"] = str(context["tenant_id"])
    os.environ["ARM_USE_CLI"] = "true"
    os.environ["ARM_RESOURCE_PROVIDER_REGISTRATIONS"] = "none"


def _terraform_configuration(provider_mirror: Path) -> str:
    return (
        "provider_installation {\n"
        "  filesystem_mirror {\n"
        f'    path = "{provider_mirror}"\n'
        '    include = ["*/*"]\n'
        "  }\n"
        "  direct {\n"
        '    exclude = ["*/*"]\n'
        "  }\n"
        "}\n"
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
    if stage == "substrate":
        value = _capture(
            (
                "az",
                "acr",
                "show",
                "--name",
                str(context["registry_name"]),
                "--subscription",
                str(context["subscription_id"]),
                "--query",
                "provisioningState",
                "--output",
                "tsv",
                "--only-show-errors",
            ),
            cwd=Path(str(context["infra"])),
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
        if not {
            "core-control-plane",
            "operator-service",
            "document-ingestion-api",
            "document-processing-worker",
            "isolated-executor",
        }.issubset(expected):
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
        return verify_workload_health(
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
        return RuntimeDeploymentProfile.create(
            runtime_platform="container-apps",
            database_placement="postgres-flex",
        ).digest
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError("standalone runtime profile digest is invalid")
    return value


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


def _plan_summary(value: object) -> dict[str, object]:
    changes = value.get("resource_changes") if isinstance(value, dict) else None
    if not isinstance(changes, list) or len(changes) > 5000:
        raise ValueError("Terraform plan resource change inventory is invalid")
    counts = {name: 0 for name in ("create", "update", "delete", "replace", "read", "no-op")}
    types: dict[str, int] = {}
    projected: list[dict[str, object]] = []
    for item in changes:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("type"), str)
            or not isinstance(item.get("address"), str)
            or not item["address"]
        ):
            raise ValueError("Terraform plan resource change is invalid")
        change = item.get("change")
        actions = change.get("actions") if isinstance(change, dict) else None
        if not isinstance(actions, list) or not all(isinstance(action, str) for action in actions):
            raise ValueError("Terraform plan action is invalid")
        action_set = set(actions)
        if action_set == {"create", "delete"}:
            counts["replace"] += 1
        else:
            for action in action_set:
                if action in counts:
                    counts[action] += 1
        types[item["type"]] = types.get(item["type"], 0) + 1
        projected.append({"address": item["address"], "actions": actions})
    return {
        "action_counts": counts,
        "resource_type_counts": dict(sorted(types.items())),
        "resource_changes": projected,
    }


def _required_image_digest(records: dict[str, object], name: str) -> str:
    record = _mapping(records.get(name), f"runtime image {name}")
    digest = record.get("image_digest")
    if not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
        raise ValueError("runtime image digest is invalid")
    return digest


def _foundation_binding_digest(
    handoff: dict[str, object],
    *,
    runner: dict[str, object],
    state: dict[str, object],
    ops: dict[str, object],
    app: dict[str, object],
) -> str:
    return canonical_digest(
        {
            "source_commit": handoff.get("source_commit"),
            "run_digest": handoff.get("run_digest"),
            "region": handoff.get("region"),
            "region_short": handoff.get("region_short"),
            "runner": runner,
            "state": state,
            "ops": ops,
            "app_resource_group": app,
        }
    )


def _foundation_application_workload(
    app: dict[str, object], *, environment: str, region_short: str
) -> str:
    name = app.get("name")
    suffix = f"-{environment}-{region_short}"
    if not isinstance(name, str) or not name.startswith("rg-") or not name.endswith(suffix):
        raise ValueError("Foundation application resource-group name is invalid")
    workload = name[3 : -len(suffix)]
    if re.fullmatch(r"[a-z][a-z0-9]{1,11}", workload) is None:
        raise ValueError("Foundation application workload is invalid")
    return workload


def _vault_name(uri: str) -> str:
    match = re.fullmatch(r"https://([a-z0-9-]{3,24})[.]vault[.]azure[.]net/?", uri)
    if match is None:
        raise ValueError("Terraform Key Vault URI is invalid")
    return match.group(1)


def _terraform_output(infra: Path, name: str) -> str:
    return _capture(
        ("terraform", "output", "-raw", name),
        cwd=infra,
        timeout=120,
        reason="Terraform output readback failed",
    ).strip()


def _terraform_json_output(infra: Path, name: str) -> object:
    raw = _capture(
        ("terraform", "output", "-json", name),
        cwd=infra,
        timeout=120,
        reason="Terraform JSON output readback failed",
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Terraform JSON output is invalid") from exc


def _run(command: tuple[str, ...] | list[str], *, cwd: Path, timeout: int, reason: str) -> None:
    result = subprocess.run(command, cwd=cwd, check=False, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise ValueError(reason)


def _capture(command: tuple[str, ...], *, cwd: Path, timeout: int, reason: str) -> str:
    result = subprocess.run(
        command, cwd=cwd, check=False, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        raise ValueError(reason)
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


def _private_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(read_private_bytes(path, max_bytes=4 * 1024 * 1024))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError(  # noqa: TRY004 - normalize untrusted JSON into a stable CLI error
            f"{label} is invalid"
        )
    return {str(key): item for key, item in value.items()}


def _replace_private_json(path: Path, value: dict[str, object]) -> None:
    temporary = path.parent / f".{path.name}.tmp-{os.getpid()}"
    temporary.unlink(missing_ok=True)
    write_private_output(
        temporary,
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
    )
    os.replace(temporary, path)
    path.chmod(0o600)


def _replace_or_verify_private_json(path: Path, value: dict[str, object]) -> None:
    if path.exists():
        if _private_json(path, path.name) != value:
            raise ValueError(f"retained {path.name} differs")
        return
    _replace_private_json(path, value)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} is invalid")
    return {str(key): item for key, item in value.items()}


def _required_guid(value: dict[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or _GUID.fullmatch(item) is None:
        raise ValueError(f"{field} is invalid")
    return item


def _file_digest(path: Path) -> str:
    return hashlib.sha256(read_private_bytes(path, max_bytes=512 * 1024 * 1024)).hexdigest()


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    details = path.lstat()
    if (
        not path.is_absolute()
        or not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
        or details.st_uid != os.geteuid()
    ):
        raise PermissionError("standalone host work directory must be current-UID mode 0700")


def _acquire_checkpoint_lock(work_dir: Path) -> int:
    """Acquire one nonblocking lock for all stateful managed-host checkpoints."""

    directory = os.open(work_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        descriptor = os.open(
            ".checkpoint.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
    finally:
        os.close(directory)
    details = os.fstat(descriptor)
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_uid != os.geteuid()
        or details.st_nlink != 1
    ):
        os.close(descriptor)
        raise PermissionError("standalone checkpoint lock is not a private regular file")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise ValueError("another standalone checkpoint is already running") from exc
    return descriptor


def _absolute(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def _moment(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_moment(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("approval expiry is invalid") from exc
    if result.tzinfo is None:
        raise ValueError("approval expiry is invalid")
    return result.astimezone(UTC)


if __name__ == "__main__":
    raise SystemExit(main())

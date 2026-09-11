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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.deployment_kit import acquire_deployment_kit
from fdai_deployment_cli.license import inspect_license
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.target import compute_target_binding
from fdai_deployment_cli.trust_roots import license_public_key_pem

_DIGEST = re.compile(r"[0-9a-f]{64}")
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_STAGES: Final = ("substrate", "application")
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
    "module.key_vault",
    "module.kv_private_endpoint",
    "module.state_store",
    "module.postgres_public_mode_private_endpoint",
    "module.event_bus",
    "module.event_bus_auxiliary",
    "module.event_bus_private_endpoint",
    "azurerm_key_vault_secret.state_store_dsn",
)


def main(argv: list[str] | None = None) -> int:
    """Run one remote checkpoint and emit only sanitized JSON."""

    parser = argparse.ArgumentParser(prog="python -m fdai_deployment_cli.standalone_host")
    parser.add_argument("--work-dir", type=Path, required=True)
    subcommands = parser.add_subparsers(required=True)

    prepare = subcommands.add_parser("prepare")
    prepare.add_argument("--kit", type=Path, required=True)
    prepare.add_argument("--handoff", type=Path, required=True)
    prepare.add_argument("--entra", type=Path, required=True)
    prepare.set_defaults(handler=_prepare)

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

    migrate = subcommands.add_parser("migrate")
    migrate.set_defaults(handler=_migrate)

    license_command = subcommands.add_parser("install-license")
    license_command.add_argument("--image-digest", required=True)
    license_command.add_argument("--deployment-binding", required=True)
    license_command.set_defaults(handler=_install_license)

    verify = subcommands.add_parser("verify")
    verify.set_defaults(handler=_verify)

    args = parser.parse_args(argv)
    try:
        work_dir = _absolute(args.work_dir)
        result = args.handler(args, work_dir)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"standalone-host: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


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
    foundation_binding_digest = _foundation_binding_digest(
        handoff,
        runner=runner,
        state=state,
        ops=ops,
        app=app,
    )
    entra_binding_digest = canonical_digest(entra)
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
        ):
            raise ValueError("standalone host retained context differs")
        _terraform_init(work_dir, retained)
        return {
            "schema_version": "fdai.standalone-host-prepare.v1",
            "state": "prepared",
            "source_commit": retained["source_commit"],
            "kit_manifest_digest": retained["kit_manifest_digest"],
            "runtime_release_digest": retained["runtime_release_digest"],
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
    _install_runtime_support(work_dir)
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
    suffix = hashlib.sha256(str(handoff["run_digest"]).encode()).hexdigest()[:6]
    region = str(handoff["region"])
    region_short = region[:3]
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
        "env": "dev",
        "region": region,
        "region_short": region_short,
        "tenant_id": tenant,
        "deploy_runner_principal_id": principal_id,
        "postgres_admin_login": "fdaiadmin",
        "generate_initial_postgres_password": True,
        "resource_name_suffix": suffix,
        "foundation_resource_group_context_digest": str(app["foundation_context_digest"]),
        "enable_private_networking": True,
        "enable_private_postgres": False,
        "runner_vnet_id": str(ops["vnet_id"]),
        "runner_vnet_name": str(ops["vnet_name"]),
        "ops_resource_group_name": str(ops["resource_group_name"]),
        "acr_sku": "Premium",
        "core_image": refs["core-control-plane"],
        "operator_api_image": refs["operator-service"],
        "operator_api_migration_image": refs["operator-service"],
        "ingestion_image": refs["document-ingestion-api"],
        "ingestion_migration_image": refs["document-ingestion-api"],
        "clamav_image": refs["clamav"],
        "enable_console": True,
        "enable_operator_api": True,
        "enable_isolated_executor": True,
        "enable_document_ingestion": False,
        "enable_llm": False,
        "operator_api_audience": str(entra["OPERATOR_API_AUDIENCE"]),
        "rbac_readers_group_id": str(entra["RBAC_READERS_GROUP_ID"]),
        "rbac_contributors_group_id": str(entra["RBAC_CONTRIBUTORS_GROUP_ID"]),
        "rbac_approvers_group_id": str(entra["RBAC_APPROVERS_GROUP_ID"]),
        "rbac_owners_group_id": str(entra["RBAC_OWNERS_GROUP_ID"]),
        "rbac_break_glass_group_id": str(entra["RBAC_BREAK_GLASS_GROUP_ID"]),
        "stewardship_maintainers": operator_id,
        "stewardship_agent_bindings": {name: f"user:{operator_id}" for name in steward_names},
    }
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
        "state_resource_group": str(ops["resource_group_name"]),
        "state_account": str(state["account_name"]),
        "state_container": str(state["container_name"]),
        "state_key": "fdai-dev.tfstate",
        "kit_manifest_digest": kit.verification.manifest_digest,
        "runtime_release_digest": kit.runtime.digest,
        "registry_name": registry,
        "registry_login_server": login_server,
        "image_refs": refs,
        "infra": str(infra),
        "terraform": str(terraform),
        "provider_mirror": str(provider_mirror),
        "terraform_config": str(terraform_config),
        "terraform_data": str(work_dir / "terraform-data"),
    }
    _replace_private_json(work_dir / "application.auto.tfvars.json", values)
    _replace_private_json(work_dir / "context.json", context)
    _terraform_init(work_dir, context)
    return {
        "schema_version": "fdai.standalone-host-prepare.v1",
        "state": "prepared",
        "source_commit": kit.source_commit,
        "kit_manifest_digest": kit.verification.manifest_digest,
        "runtime_release_digest": kit.runtime.digest,
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _plan(args: argparse.Namespace, work_dir: Path) -> dict[str, object]:
    stage = str(args.stage)
    if stage == "application":
        for prerequisite in (
            "substrate-receipt.json",
            "image-import-receipt.json",
            "migration-receipt.json",
        ):
            if not (work_dir / prerequisite).is_file():
                raise ValueError("application plan prerequisites are incomplete")
    context = _private_json(work_dir / "context.json", "standalone host context")
    _managed_identity_login_from_context(context, work_dir)
    infra = Path(str(context["infra"]))
    plan_path = work_dir / f"{stage}.tfplan"
    plan_path.unlink(missing_ok=True)
    command = [
        "terraform",
        "plan",
        "-input=false",
        "-no-color",
        f"-var-file={work_dir / 'application.auto.tfvars.json'}",
        f"-out={plan_path}",
    ]
    if stage == "substrate":
        command.extend(f"-target={target}" for target in _SUBSTRATE_TARGETS)
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
    plan_path = work_dir / f"{stage}.tfplan"
    if _file_digest(plan_path) != review["plan_digest"]:
        raise ValueError("standalone application plan changed before apply")
    claim_path = work_dir / f"{stage}-claim.json"
    receipt_path = work_dir / f"{stage}-receipt.json"
    if receipt_path.exists():
        return _private_json(receipt_path, "standalone apply receipt")
    if claim_path.exists():
        raise ValueError("standalone apply claim already exists; automatic retry is blocked")
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
    _replace_private_json(claim_path, claim)
    _run(
        ("terraform", "apply", "-input=false", "-no-color", str(plan_path)),
        cwd=Path(str(context["infra"])),
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
    infra = Path(str(context["infra"]))
    command = [
        "terraform",
        "plan",
        "-detailed-exitcode",
        "-input=false",
        "-no-color",
        f"-var-file={work_dir / 'application.auto.tfvars.json'}",
    ]
    if stage == "substrate":
        command.extend(f"-target={target}" for target in _SUBSTRATE_TARGETS)
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
    infra = Path(str(context["infra"]))
    command = (
        "terraform",
        "plan",
        "-detailed-exitcode",
        "-input=false",
        "-no-color",
        f"-var-file={work_dir / 'application.auto.tfvars.json'}",
    )
    completed = subprocess.run(command, cwd=infra, check=False, capture_output=True, timeout=1800)
    if completed.returncode != 0:
        raise ValueError("standalone application second plan is not zero-change")
    health = _container_app_health(context, infra)
    if not health:
        raise ValueError("standalone application runtime health is incomplete")
    receipt: dict[str, object] = {
        "schema_version": "fdai.standalone-application-verification.v1",
        "state": "verified",
        "terraform_zero_change_verified": True,
        "runtime_health_verified": True,
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


def _install_runtime_support(work_dir: Path) -> None:
    environment = work_dir / "runtime-venv"
    if (environment / "bin/python").exists():
        return
    wheels = sorted((work_dir / "kit-work/verified/support/python").rglob("*.whl"))
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
    os.environ["PATH"] = os.pathsep.join(
        (str(terraform.parent), "/usr/local/bin", "/usr/bin", "/bin")
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
    return _container_app_health(context, Path(str(context["infra"])))


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
            "runner": runner,
            "state": state,
            "ops": ops,
            "app_resource_group": app,
        }
    )


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
        raise ValueError(f"{label} is invalid")
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


def _absolute(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def _moment(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_moment(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("approval expiry is invalid") from exc
    if result.tzinfo is None:
        raise ValueError("approval expiry is invalid")
    return result.astimezone(UTC)


if __name__ == "__main__":
    raise SystemExit(main())

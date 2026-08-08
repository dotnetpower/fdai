#!/usr/bin/env python3
"""Create and verify immutable service deployment plan bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from service_contract import ServiceContractError, resolve_service, validate_image_reference

_SCHEMA_VERSION = "fdai.service-deployment-plan.v2"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


class PlanBundleError(ValueError):
    """Raised when protected plan evidence is incomplete, stale, or mismatched."""


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PlanBundleError(f"{path.name} must contain a JSON object")
    return payload


def _required(value: str, *, field: str) -> str:
    if not value or "\n" in value or "\r" in value:
        raise PlanBundleError(f"{field} must be non-empty and single-line")
    return value


def _resource_ids(value: Any) -> list[str]:
    found: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)
        elif isinstance(item, str) and item.lower().startswith("/subscriptions/"):
            found.add(item.lower())

    visit(value)
    return sorted(found)


def _target_context(
    payload: dict[str, Any],
    *,
    allowed_address: str,
    subscription_id: str,
    image_ref: str,
) -> dict[str, Any]:
    changes = payload.get("resource_changes")
    if not isinstance(changes, list):
        raise PlanBundleError("plan JSON resource_changes must be an array")
    matches = [
        entry
        for entry in changes
        if isinstance(entry, dict) and entry.get("address") == allowed_address
    ]
    if len(matches) != 1:
        raise PlanBundleError("plan JSON must contain exactly one selected service resource")
    change = matches[0].get("change")
    after = change.get("after") if isinstance(change, dict) else None
    if not isinstance(after, dict):
        raise PlanBundleError("selected service plan has no planned resource")

    service_name = _required(str(after.get("name", "")), field="service name")
    resource_group = _required(
        str(after.get("resource_group_name", "")), field="service resource group"
    )
    environment_id = _required(
        str(after.get("container_app_environment_id", "")),
        field="Container Apps environment id",
    )
    expected_resource_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/"
        f"Microsoft.App/containerApps/{service_name}"
    ).lower()
    planned_resource_id = str(after.get("id") or expected_resource_id).lower()
    if planned_resource_id != expected_resource_id:
        raise PlanBundleError(
            "planned service resource id does not match subscription/name context"
        )

    identities = after.get("identity")
    identity = identities[0] if isinstance(identities, list) and len(identities) == 1 else None
    raw_identity_ids = identity.get("identity_ids") if isinstance(identity, dict) else None
    if (
        not isinstance(raw_identity_ids, list)
        or not raw_identity_ids
        or not all(isinstance(identity_id, str) and identity_id for identity_id in raw_identity_ids)
    ):
        raise PlanBundleError("planned service workload identity set is invalid")

    templates = after.get("template")
    template = templates[0] if isinstance(templates, list) and len(templates) == 1 else None
    containers = template.get("container") if isinstance(template, dict) else None
    container = containers[0] if isinstance(containers, list) and len(containers) == 1 else None
    if not isinstance(container, dict) or container.get("image") != image_ref:
        raise PlanBundleError("planned service image does not match protected image context")
    runtime_contract = {key: container.get(key) for key in ("name", "command", "args", "env")}
    tags = after.get("tags")
    component_tag = tags.get("fdai:component") if isinstance(tags, dict) else None
    if not isinstance(component_tag, str) or not component_tag:
        raise PlanBundleError("planned service is missing the fdai:component tag")
    return {
        "service_resource_id": expected_resource_id,
        "service_name": service_name,
        "resource_group": resource_group,
        "component_tag": component_tag,
        "container_app_environment_id": environment_id.lower(),
        "identity_resource_ids": sorted(identity_id.lower() for identity_id in raw_identity_ids),
        "referenced_resource_ids": _resource_ids(after),
        "image_ref": image_ref,
        "runtime_contract_digest": hashlib.sha256(_canonical(runtime_contract)).hexdigest(),
    }


def _deployment_context(
    *,
    plan_json: Path,
    service: str,
    environment: str,
    repository: str,
    commit_sha: str,
    image_ref: str,
    image_digest: str,
    tenant_id: str,
    subscription_id: str,
    backend_resource_group: str,
    backend_storage_account: str,
    backend_container: str,
    controls_commit_sha: str,
    attestation_signer_workflow: str,
) -> dict[str, Any]:
    contract = resolve_service(service, environment)
    return {
        "service": service,
        "environment": environment,
        "repository": repository,
        "commit_sha": commit_sha,
        "terraform_root": contract.terraform_root,
        "tenant_id": _required(tenant_id, field="tenant id"),
        "subscription_id": _required(subscription_id, field="subscription id"),
        "backend": {
            "resource_group": _required(backend_resource_group, field="backend resource group"),
            "storage_account": _required(backend_storage_account, field="backend storage account"),
            "container": _required(backend_container, field="backend container"),
            "key": contract.backend_key,
        },
        "target": _target_context(
            _read_object(plan_json),
            allowed_address=contract.allowed_resource_address,
            subscription_id=subscription_id,
            image_ref=image_ref,
        ),
        "attestation": {
            "source_digest": commit_sha,
            "subject_digest": image_digest,
            "signer_workflow": _required(
                attestation_signer_workflow, field="attestation signer workflow"
            ),
        },
        "trusted_controls": {"commit_sha": controls_commit_sha},
    }


def create_bundle(
    *,
    plan: Path,
    plan_json: Path,
    context_path: Path,
    metadata_path: Path,
    service: str,
    environment: str,
    repository: str,
    commit_sha: str,
    image_ref: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
    tenant_id: str,
    subscription_id: str,
    backend_resource_group: str,
    backend_storage_account: str,
    backend_container: str,
    controls_commit_sha: str,
    attestation_signer_workflow: str,
    now: datetime,
) -> dict[str, Any]:
    """Seal a guarded binary plan and its deployment context for exact later apply."""
    if _COMMIT_PATTERN.fullmatch(commit_sha) is None:
        raise PlanBundleError("commit_sha must be a lowercase 40-character git SHA")
    if not workflow_run_id.isdigit():
        raise PlanBundleError("workflow_run_id must be numeric")
    if not workflow_run_attempt.isdigit() or int(workflow_run_attempt) < 1:
        raise PlanBundleError("workflow_run_attempt must be a positive integer")
    if _COMMIT_PATTERN.fullmatch(controls_commit_sha) is None:
        raise PlanBundleError("controls_commit_sha must be a lowercase 40-character git SHA")
    contract = resolve_service(service, environment)
    image_digest = validate_image_reference(contract, repository, image_ref)
    context = _deployment_context(
        plan_json=plan_json,
        service=service,
        environment=environment,
        repository=repository,
        commit_sha=commit_sha,
        image_ref=image_ref,
        image_digest=image_digest,
        tenant_id=tenant_id,
        subscription_id=subscription_id,
        backend_resource_group=backend_resource_group,
        backend_storage_account=backend_storage_account,
        backend_container=backend_container,
        controls_commit_sha=controls_commit_sha,
        attestation_signer_workflow=attestation_signer_workflow,
    )
    context_path.write_bytes(_canonical(context))
    context_digest = _digest(context_path)
    metadata: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "ready",
        "plan_id": f"{service}-{environment}-{workflow_run_id}-{workflow_run_attempt}",
        "service": service,
        "environment": environment,
        "commit_sha": commit_sha,
        "backend_key": contract.backend_key,
        "terraform_root": contract.terraform_root,
        "allowed_resource_address": contract.allowed_resource_address,
        "image_ref": image_ref,
        "image_digest": image_digest,
        "plan_digest": _digest(plan),
        "plan_json_digest": _digest(plan_json),
        "context_digest": context_digest,
        "workflow_run_id": workflow_run_id,
        "workflow_run_attempt": workflow_run_attempt,
        "tenant_id": tenant_id,
        "subscription_id": subscription_id,
        "backend_resource_group": backend_resource_group,
        "backend_storage_account": backend_storage_account,
        "backend_container": backend_container,
        "controls_commit_sha": controls_commit_sha,
        "attestation_signer_workflow": attestation_signer_workflow,
        "created_at": now.astimezone(UTC).isoformat(),
        "expires_at": (now.astimezone(UTC) + timedelta(hours=24)).isoformat(),
    }
    metadata_path.write_bytes(_canonical(metadata))
    return metadata


def verify_bundle(
    *,
    plan: Path,
    plan_json: Path,
    context_path: Path,
    metadata_path: Path,
    service: str,
    environment: str,
    repository: str,
    commit_sha: str,
    image_ref: str,
    plan_digest: str,
    context_digest: str,
    plan_run_id: str,
    workflow_run_attempt: str,
    tenant_id: str,
    subscription_id: str,
    backend_resource_group: str,
    backend_storage_account: str,
    backend_container: str,
    controls_commit_sha: str,
    attestation_signer_workflow: str,
    now: datetime,
) -> dict[str, Any]:
    """Verify exact apply inputs against every sealed plan artifact and mapping."""
    invalid_plan_digest = _SHA256_PATTERN.fullmatch(plan_digest) is None
    invalid_context_digest = _SHA256_PATTERN.fullmatch(context_digest) is None
    if invalid_plan_digest or invalid_context_digest:
        raise PlanBundleError("plan and context digests must be lowercase SHA-256 values")
    if _COMMIT_PATTERN.fullmatch(commit_sha) is None:
        raise PlanBundleError("commit_sha must be a lowercase 40-character git SHA")
    if not plan_run_id.isdigit():
        raise PlanBundleError("plan_run_id must be numeric")
    contract = resolve_service(service, environment)
    image_digest = validate_image_reference(contract, repository, image_ref)
    metadata = _read_object(metadata_path)
    expected = {
        "schema_version": _SCHEMA_VERSION,
        "status": "ready",
        "plan_id": f"{service}-{environment}-{plan_run_id}-{workflow_run_attempt}",
        "service": service,
        "environment": environment,
        "commit_sha": commit_sha,
        "backend_key": contract.backend_key,
        "terraform_root": contract.terraform_root,
        "allowed_resource_address": contract.allowed_resource_address,
        "image_ref": image_ref,
        "image_digest": image_digest,
        "plan_digest": plan_digest,
        "context_digest": context_digest,
        "workflow_run_id": plan_run_id,
        "workflow_run_attempt": workflow_run_attempt,
        "tenant_id": tenant_id,
        "subscription_id": subscription_id,
        "backend_resource_group": backend_resource_group,
        "backend_storage_account": backend_storage_account,
        "backend_container": backend_container,
        "controls_commit_sha": controls_commit_sha,
        "attestation_signer_workflow": attestation_signer_workflow,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise PlanBundleError(f"plan metadata {key} does not match exact apply input")
    if _digest(plan) != plan_digest:
        raise PlanBundleError("binary plan digest does not match exact apply input")
    if _digest(plan_json) != metadata.get("plan_json_digest"):
        raise PlanBundleError("plan JSON digest does not match metadata")
    if _digest(context_path) != context_digest:
        raise PlanBundleError("context digest does not match exact apply input")
    context = _read_object(context_path)
    expected_context = _deployment_context(
        plan_json=plan_json,
        service=service,
        environment=environment,
        repository=repository,
        commit_sha=commit_sha,
        image_ref=image_ref,
        image_digest=image_digest,
        tenant_id=tenant_id,
        subscription_id=subscription_id,
        backend_resource_group=backend_resource_group,
        backend_storage_account=backend_storage_account,
        backend_container=backend_container,
        controls_commit_sha=controls_commit_sha,
        attestation_signer_workflow=attestation_signer_workflow,
    )
    if context != expected_context:
        raise PlanBundleError("sealed deployment context does not match exact apply input")
    try:
        expires_at = datetime.fromisoformat(str(metadata["expires_at"]))
    except (KeyError, ValueError) as exc:
        raise PlanBundleError("plan metadata has an invalid expiry") from exc
    if expires_at.tzinfo is None or expires_at <= now.astimezone(UTC):
        raise PlanBundleError("protected service plan has expired")
    return metadata


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-json", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--workflow-run-attempt", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--backend-resource-group", required=True)
    parser.add_argument("--backend-storage-account", required=True)
    parser.add_argument("--backend-container", required=True)
    parser.add_argument("--controls-commit-sha", required=True)
    parser.add_argument("--attestation-signer-workflow", required=True)


def main() -> int:
    """Create or verify a protected plan bundle from workflow inputs."""
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    _common(create)
    create.add_argument("--workflow-run-id", required=True)
    verify = commands.add_parser("verify")
    _common(verify)
    verify.add_argument("--plan-digest", required=True)
    verify.add_argument("--context-digest", required=True)
    verify.add_argument("--plan-run-id", required=True)
    args = parser.parse_args()
    common = {
        "plan": args.plan,
        "plan_json": args.plan_json,
        "context_path": args.context,
        "metadata_path": args.metadata,
        "service": args.service,
        "environment": args.environment,
        "repository": args.repository,
        "commit_sha": args.commit_sha,
        "image_ref": args.image_ref,
        "workflow_run_attempt": args.workflow_run_attempt,
        "tenant_id": args.tenant_id,
        "subscription_id": args.subscription_id,
        "backend_resource_group": args.backend_resource_group,
        "backend_storage_account": args.backend_storage_account,
        "backend_container": args.backend_container,
        "controls_commit_sha": args.controls_commit_sha,
        "attestation_signer_workflow": args.attestation_signer_workflow,
    }
    try:
        if args.command == "create":
            metadata = create_bundle(
                **common,
                workflow_run_id=args.workflow_run_id,
                now=datetime.now(UTC),
            )
        else:
            metadata = verify_bundle(
                **common,
                plan_digest=args.plan_digest,
                context_digest=args.context_digest,
                plan_run_id=args.plan_run_id,
                now=datetime.now(UTC),
            )
        print(json.dumps(metadata, sort_keys=True))
    except (OSError, json.JSONDecodeError, ServiceContractError, PlanBundleError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

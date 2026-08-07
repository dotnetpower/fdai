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

_SCHEMA_VERSION = "fdai.service-deployment-plan.v1"
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
    now: datetime,
) -> dict[str, Any]:
    """Seal a guarded binary plan and its deployment context for exact later apply."""
    if _COMMIT_PATTERN.fullmatch(commit_sha) is None:
        raise PlanBundleError("commit_sha must be a lowercase 40-character git SHA")
    if not workflow_run_id.isdigit():
        raise PlanBundleError("workflow_run_id must be numeric")
    contract = resolve_service(service, environment)
    image_digest = validate_image_reference(contract, repository, image_ref)
    context = {
        "allowed_resource_address": contract.allowed_resource_address,
        "backend_key": contract.backend_key,
        "commit_sha": commit_sha,
        "environment": environment,
        "image_digest": image_digest,
        "image_ref": image_ref,
        "repository": repository,
        "service": service,
        "terraform_root": contract.terraform_root,
    }
    context_path.write_bytes(_canonical(context))
    context_digest = _digest(context_path)
    metadata: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "ready",
        "plan_id": f"{service}-{environment}-{workflow_run_id}",
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
        "plan_id": f"{service}-{environment}-{plan_run_id}",
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
    expected_context = {
        key: expected[key]
        for key in (
            "allowed_resource_address",
            "backend_key",
            "commit_sha",
            "environment",
            "image_digest",
            "image_ref",
            "service",
            "terraform_root",
        )
    }
    expected_context["repository"] = repository
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

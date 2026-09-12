#!/usr/bin/env python3
"""Build the sanitized receipt for one exact protected deployment apply."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_MAX_READBACK_BYTES = 64 * 1024


def build_apply_receipt(
    *,
    environ: Mapping[str, str],
    inventory_path: Path,
    plan_metadata_path: Path,
    cost_governance_readback_path: Path = Path("cost-governance-job-image-readback.json"),
    provider_schema_evidence_path: Path = Path("provider-schema-deployment-evidence.json"),
    provider_schema_core_baseline_path: Path = Path("provider-schema-core-baseline.json"),
) -> dict[str, object]:
    """Return an apply receipt closed over every available required observation."""
    receipt: dict[str, object] = {
        "schema_version": "fdai.deployment-apply-receipt.v1",
        "plan_id": environ["APPLY_PLAN_ID"],
        "plan_digest": environ["APPLY_PLAN_DIGEST"],
        "request_id": environ["APPLY_REQUEST_ID"],
        "context_digest": environ["APPLY_CONTEXT_DIGEST"],
        "source_commit": environ["APPLY_SOURCE_COMMIT"],
        "workflow_run_id": environ["GITHUB_RUN_ID"],
        "workflow_run_attempt": environ["GITHUB_RUN_ATTEMPT"],
        "applied_at": environ["APPLIED_AT"],
        "status": "applied",
        "subscription_ready": False,
    }
    if inventory_path.is_file():
        inventory_bytes = inventory_path.read_bytes()
        inventory = _json_object(inventory_bytes, "initial inventory receipt")
        if (
            inventory.get("schema_version") != "fdai.genesis-initial-inventory-execution-receipt.v1"
            or inventory.get("source_commit") != environ["APPLY_SOURCE_COMMIT"]
            or inventory.get("status") != "succeeded"
            or inventory.get("active_generation_verified") is not False
            or inventory.get("subscription_ready") is not False
        ):
            raise ValueError("initial inventory receipt is invalid")
        receipt.update(
            {
                "terraform_zero_change_verified": True,
                "migration_stage_verified": True,
                "runtime_health_verified": True,
                "canary_verified": True,
                "initial_inventory_execution_receipt_digest": hashlib.sha256(
                    inventory_bytes
                ).hexdigest(),
            }
        )
    request_id = environ["APPLY_REQUEST_ID"]
    is_provider_schema = request_id.startswith("apply-provider-")
    is_cost_governance = request_id.startswith("apply-cost-")
    if is_provider_schema:
        if inventory_path.is_file() or cost_governance_readback_path.is_file():
            raise ValueError("provider-schema apply receipt has unrelated runtime evidence")
        plan_metadata = _load_json_object(plan_metadata_path, "plan metadata")
        expected_profile = (
            "cost-governance"
            if request_id.startswith("apply-provider-cost-")
            else "core-control-plane"
        )
        runtime_revision, runtime_digest = _runtime_image_evidence(
            plan_metadata,
            expected_profile=expected_profile,
        )
        baseline_bytes = _read_bounded(
            provider_schema_core_baseline_path,
            "provider-schema Core baseline",
        )
        baseline = _json_object(baseline_bytes, "provider-schema Core baseline")
        _validate_provider_schema_core_baseline(
            baseline,
            expected_source_revision=runtime_revision,
            expected_image_digest=runtime_digest,
        )
        evidence_bytes = _read_bounded(
            provider_schema_evidence_path,
            "provider-schema deployment evidence",
        )
        evidence = _json_object(evidence_bytes, "provider-schema deployment evidence")
        _validate_provider_schema_evidence(
            evidence,
            expected_application_source=environ["APPLY_SOURCE_COMMIT"],
            expected_runtime_revision=runtime_revision,
            expected_plan_id=environ["APPLY_PLAN_ID"],
        )
        receipt.update(
            {
                "terraform_zero_change_verified": True,
                "provider_schema_runtime_image_revision": runtime_revision,
                "provider_schema_runtime_image_digest": runtime_digest,
                "provider_schema_runtime_image_profile": expected_profile,
                "provider_schema_core_baseline_digest": hashlib.sha256(baseline_bytes).hexdigest(),
                "provider_schema_deployment_evidence_digest": hashlib.sha256(
                    evidence_bytes
                ).hexdigest(),
            }
        )
    elif is_cost_governance:
        if inventory_path.is_file():
            raise ValueError("Cost Governance apply receipt has unrelated inventory evidence")
        readback_bytes = _read_bounded(
            cost_governance_readback_path,
            "Cost Governance Job image readback",
        )
        readback = _json_object(readback_bytes, "Cost Governance Job image readback")
        _validate_cost_governance_readback(readback)
        plan_metadata = _load_json_object(plan_metadata_path, "plan metadata")
        runtime_image = plan_metadata.get("runtime_image")
        if (
            not isinstance(runtime_image, dict)
            or runtime_image.get("profile") != "cost-governance"
            or runtime_image.get("digest") != readback["image_digest"]
        ):
            raise ValueError("Cost Governance readback does not match plan image evidence")
        receipt.update(
            {
                "terraform_zero_change_verified": True,
                "cost_governance_job_images_verified": True,
                "cost_governance_image_digest": readback["image_digest"],
                "cost_governance_job_image_readback_digest": hashlib.sha256(
                    readback_bytes
                ).hexdigest(),
            }
        )
    elif cost_governance_readback_path.is_file():
        raise ValueError("Cost Governance Job image readback is unexpected")
    if not is_provider_schema and (
        provider_schema_evidence_path.is_file() or provider_schema_core_baseline_path.is_file()
    ):
        raise ValueError("provider-schema deployment evidence is unexpected")
    readback_digest = environ.get("MODEL_BINDING_READBACK_DIGEST", "")
    if readback_digest:
        if not _is_digest(readback_digest):
            raise ValueError("model binding readback digest is invalid")
        model_resolution = _load_json_object(plan_metadata_path, "plan metadata").get(
            "model_resolution"
        )
        if not isinstance(model_resolution, dict):
            raise ValueError("model binding apply receipt has no model resolution")
        receipt["model_binding"] = {
            "model_resolution": model_resolution,
            "readback_receipt_digest": readback_digest,
        }
    identity_effect_digest = environ.get("DEPLOY_IDENTITY_EFFECT_DIGEST", "")
    if identity_effect_digest:
        receipt["deploy_identity_effect_digest"] = identity_effect_digest
    receipt["receipt_digest"] = _canonical_digest(receipt)
    return receipt


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _canonical_digest(value: Mapping[str, object]) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(body).hexdigest()


def _read_bounded(path: Path, label: str) -> bytes:
    try:
        details = path.lstat()
        if not stat.S_ISREG(details.st_mode) or details.st_size > _MAX_READBACK_BYTES:
            raise ValueError(f"{label} must be a bounded regular file")
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{label} is unavailable") from exc


def _validate_cost_governance_readback(readback: Mapping[str, object]) -> None:
    if set(readback) != {"schema_version", "image_digest", "jobs"}:
        raise ValueError("Cost Governance Job image readback schema is invalid")
    image_digest = readback.get("image_digest")
    if (
        readback.get("schema_version") != "fdai.cost-governance-job-image-readback.v1"
        or not isinstance(image_digest, str)
        or not image_digest.startswith("sha256:")
        or not _is_digest(image_digest.removeprefix("sha256:"))
    ):
        raise ValueError("Cost Governance Job image readback is invalid")
    jobs = readback.get("jobs")
    expected_containers = {
        "analyzer": "cost-governance-analyzer",
        "collector": "cost-governance-collector",
    }
    if not isinstance(jobs, dict) or set(jobs) != set(expected_containers):
        raise ValueError("Cost Governance Job image readback is incomplete")
    for role, expected_container in expected_containers.items():
        job = jobs[role]
        if (
            not isinstance(job, dict)
            or set(job) != {"container", "image_digest"}
            or job.get("container") != expected_container
            or job.get("image_digest") != image_digest
        ):
            raise ValueError(f"Cost Governance {role} readback is invalid")


def _runtime_image_evidence(
    plan_metadata: Mapping[str, object],
    *,
    expected_profile: str,
) -> tuple[str, str]:
    runtime_image = plan_metadata.get("runtime_image")
    if not isinstance(runtime_image, dict) or set(runtime_image) != {
        "source_revision",
        "digest",
        "profile",
    }:
        raise ValueError("provider-schema plan image evidence is invalid")
    source_revision = runtime_image.get("source_revision")
    image_digest = runtime_image.get("digest")
    if (
        not isinstance(source_revision, str)
        or len(source_revision) != 40
        or any(character not in "0123456789abcdef" for character in source_revision)
        or not isinstance(image_digest, str)
        or not image_digest.startswith("sha256:")
        or not _is_digest(image_digest.removeprefix("sha256:"))
        or runtime_image.get("profile") != expected_profile
    ):
        raise ValueError("provider-schema plan image evidence is invalid")
    return source_revision, image_digest


def _validate_provider_schema_core_baseline(
    baseline: Mapping[str, object],
    *,
    expected_source_revision: str,
    expected_image_digest: str,
) -> None:
    expected_fields = {
        "schema_version",
        "source_revision",
        "image_digest",
        "core_app_ref_digest",
        "active_revision_ref_digest",
        "max_inactive_revisions",
        "health_state",
        "provisioning_state",
        "observed_at",
        "grants_authority",
    }
    max_inactive_revisions = baseline.get("max_inactive_revisions")
    if (
        set(baseline) != expected_fields
        or baseline.get("schema_version") != "fdai.provider-schema-core-baseline.v1"
        or baseline.get("source_revision") != expected_source_revision
        or baseline.get("image_digest") != expected_image_digest
        or baseline.get("health_state") != "Healthy"
        or baseline.get("provisioning_state") != "Provisioned"
        or baseline.get("grants_authority") is not False
        or not isinstance(max_inactive_revisions, int)
        or isinstance(max_inactive_revisions, bool)
        or max_inactive_revisions < 1
        or not isinstance(baseline.get("observed_at"), str)
    ):
        raise ValueError("provider-schema Core baseline is invalid")
    for field in ("core_app_ref_digest", "active_revision_ref_digest"):
        value = baseline.get(field)
        if not isinstance(value, str) or not _is_digest(value):
            raise ValueError("provider-schema Core baseline is invalid")


def _validate_provider_schema_evidence(
    evidence: Mapping[str, object],
    *,
    expected_application_source: str,
    expected_runtime_revision: str,
    expected_plan_id: str,
) -> None:
    expected_fields = {
        "schema_version",
        "application_source_commit",
        "runtime_image_revision",
        "plan_id",
        "job_execution_ref_digest",
        "job_execution_status",
        "checked_at",
        "provider_source_revision",
        "baseline_digest",
        "observed_digest",
        "drift_digest",
        "disposition",
        "durable_generation_digest",
        "durable_generation_revision",
        "run_receipt_digest",
        "review_package_digest",
        "heimdall_review_dispatched",
        "review_evidence_status",
        "correlation_id",
        "forseti_risk_verdict",
        "forseti_reason",
        "saga_audit_entry_hash",
        "grants_authority",
    }
    generation_revision = evidence.get("durable_generation_revision")
    if (
        set(evidence) != expected_fields
        or evidence.get("schema_version") != "fdai.provider-schema-deployment-evidence.v1"
        or evidence.get("application_source_commit") != expected_application_source
        or evidence.get("runtime_image_revision") != expected_runtime_revision
        or evidence.get("plan_id") != expected_plan_id
        or evidence.get("job_execution_status") != "Succeeded"
        or evidence.get("grants_authority") is not False
        or not isinstance(evidence.get("checked_at"), str)
        or evidence.get("disposition") not in {"unchanged", "compatible", "breaking"}
        or not isinstance(generation_revision, int)
        or isinstance(generation_revision, bool)
        or generation_revision < 1
    ):
        raise ValueError("provider-schema deployment evidence is invalid")
    job_execution_digest = evidence.get("job_execution_ref_digest")
    provider_revision = evidence.get("provider_source_revision")
    drift_digest = evidence.get("drift_digest")
    if (
        not isinstance(job_execution_digest, str)
        or not _is_digest(job_execution_digest)
        or not isinstance(provider_revision, str)
        or not 40 <= len(provider_revision) <= 64
        or any(character not in "0123456789abcdef" for character in provider_revision)
        or (
            drift_digest is not None
            and (not isinstance(drift_digest, str) or not _is_digest(drift_digest))
        )
    ):
        raise ValueError("provider-schema deployment evidence is invalid")
    for field in (
        "baseline_digest",
        "observed_digest",
        "durable_generation_digest",
        "run_receipt_digest",
    ):
        digest = evidence.get(field)
        if (
            not isinstance(digest, str)
            or not digest.startswith("sha256:")
            or not _is_digest(digest.removeprefix("sha256:"))
        ):
            raise ValueError("provider-schema deployment evidence is invalid")
    review_status = evidence.get("review_evidence_status")
    if review_status == "verified":
        review_digest = evidence.get("review_package_digest")
        saga_digest = evidence.get("saga_audit_entry_hash")
        if (
            evidence.get("disposition") != "breaking"
            or evidence.get("heimdall_review_dispatched") is not True
            or not isinstance(drift_digest, str)
            or evidence.get("correlation_id") != f"provider-schema:azure:{drift_digest}"
            or evidence.get("forseti_risk_verdict") != "hil"
            or evidence.get("forseti_reason") != "no_rule_match"
            or not isinstance(review_digest, str)
            or not review_digest.startswith("sha256:")
            or not _is_digest(review_digest.removeprefix("sha256:"))
            or not isinstance(saga_digest, str)
            or not _is_digest(saga_digest)
        ):
            raise ValueError("provider-schema deployment evidence is invalid")
    elif review_status == "not_applicable":
        if (
            evidence.get("disposition") == "breaking"
            or evidence.get("heimdall_review_dispatched") is not False
            or any(
                evidence.get(field) is not None
                for field in (
                    "review_package_digest",
                    "correlation_id",
                    "forseti_risk_verdict",
                    "forseti_reason",
                    "saga_audit_entry_hash",
                )
            )
        ):
            raise ValueError("provider-schema deployment evidence is invalid")
    else:
        raise ValueError("provider-schema deployment evidence is invalid")


def _json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain an object")
    return payload


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        return _json_object(path.read_bytes(), label)
    except OSError as exc:
        raise ValueError(f"{label} is invalid") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inventory-receipt",
        type=Path,
        default=Path("initial-inventory-receipt.json"),
    )
    parser.add_argument("--plan-metadata", type=Path, default=Path("plan-metadata.json"))
    parser.add_argument(
        "--cost-governance-readback",
        type=Path,
        default=Path("cost-governance-job-image-readback.json"),
    )
    parser.add_argument(
        "--provider-schema-evidence",
        type=Path,
        default=Path("provider-schema-deployment-evidence.json"),
    )
    parser.add_argument(
        "--provider-schema-core-baseline",
        type=Path,
        default=Path("provider-schema-core-baseline.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = build_apply_receipt(
            environ=os.environ,
            inventory_path=args.inventory_receipt,
            plan_metadata_path=args.plan_metadata,
            cost_governance_readback_path=args.cost_governance_readback,
            provider_schema_evidence_path=args.provider_schema_evidence,
            provider_schema_core_baseline_path=args.provider_schema_core_baseline,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    args.output.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

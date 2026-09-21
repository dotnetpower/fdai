"""Protected apply receipt download and observation validation."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Mapping
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.github_artifact_io import (
    _json_object,
    _private_artifact_bytes,
    _private_artifact_json,
)
from fdai_deployment_cli.github_provider_artifact import (
    _validate_provider_schema_core_baseline,
    _validate_provider_schema_evidence,
)
from fdai_deployment_cli.github_workflow_values import (
    _COMMIT,
    _DIGEST,
    _OCI_DIGEST,
    _PLAN_ID,
    CommandRunner,
)


def _download_apply_receipt(
    *,
    repository: str,
    workflow_run_id: int,
    request_id_value: str,
    expected_commit: str,
    expected_context_digest: str,
    expected_plan_id: str,
    expected_plan_digest: str,
    run: CommandRunner,
) -> dict[str, object]:
    """Download and validate one application receipt and its profile observation."""

    if (
        _PLAN_ID.fullmatch(expected_plan_id) is None
        or _DIGEST.fullmatch(expected_plan_digest) is None
    ):
        raise ValueError("expected apply plan identity is invalid")
    with tempfile.TemporaryDirectory(prefix="fdai-apply-status-") as raw_directory:
        directory = Path(raw_directory)
        result = run(
            (
                "run",
                "download",
                str(workflow_run_id),
                "--repo",
                repository,
                "--name",
                f"deployment-apply-receipt-{expected_plan_id}",
                "--dir",
                str(directory),
            )
        )
        if result.returncode != 0:
            raise ValueError("github_apply_receipt_unavailable")
        receipt = _private_artifact_json(directory / "apply-receipt.json", "apply receipt")
        provider_schema = request_id_value.startswith("apply-provider-")
        cost_governance = request_id_value.startswith("apply-cost-")
        if provider_schema:
            provider_evidence_bytes = _private_artifact_bytes(
                directory / "provider-schema-deployment-evidence.json",
                "provider-schema deployment evidence",
            )
            provider_evidence = dict(
                _json_object(
                    provider_evidence_bytes.decode("utf-8"),
                    "provider-schema deployment evidence",
                )
            )
            provider_baseline_bytes = _private_artifact_bytes(
                directory / "provider-schema-core-baseline.json",
                "provider-schema Core baseline",
            )
            provider_baseline = dict(
                _json_object(
                    provider_baseline_bytes.decode("utf-8"),
                    "provider-schema Core baseline",
                )
            )
            observation_bytes = b""
            observation: dict[str, object] = {}
        else:
            observation_path = directory / (
                "cost-governance-job-image-readback.json"
                if cost_governance
                else "initial-inventory-receipt.json"
            )
            observation_label = (
                "Cost Governance Job image readback"
                if cost_governance
                else "initial inventory execution receipt"
            )
            observation_bytes = _private_artifact_bytes(observation_path, observation_label)
            observation = dict(_json_object(observation_bytes.decode("utf-8"), observation_label))
    expected = {
        "schema_version": "fdai.deployment-apply-receipt.v1",
        "plan_id": expected_plan_id,
        "plan_digest": expected_plan_digest,
        "request_id": request_id_value,
        "context_digest": expected_context_digest,
        "source_commit": expected_commit,
        "status": "applied",
        "terraform_zero_change_verified": True,
        "subscription_ready": False,
    }
    if provider_schema:
        expected.update(
            {
                "terraform_zero_change_verified": True,
                "provider_schema_runtime_image_profile": (
                    "cost-governance"
                    if request_id_value.startswith("apply-provider-cost-")
                    else "core-control-plane"
                ),
            }
        )
    elif cost_governance:
        expected["cost_governance_job_images_verified"] = True
    else:
        expected.update(
            {
                "migration_stage_verified": True,
                "runtime_health_verified": True,
                "canary_verified": True,
            }
        )
    receipt_digest = receipt.get("receipt_digest")
    receipt_body = {key: item for key, item in receipt.items() if key != "receipt_digest"}
    if any(receipt.get(key) != item for key, item in expected.items()):
        raise ValueError("github_apply_receipt_context_mismatch")
    if (
        not isinstance(receipt_digest, str)
        or _DIGEST.fullmatch(receipt_digest) is None
        or canonical_digest(receipt_body) != receipt_digest
    ):
        raise ValueError("github_apply_receipt_digest_invalid")
    if provider_schema:
        runtime_revision = receipt.get("provider_schema_runtime_image_revision")
        runtime_digest = receipt.get("provider_schema_runtime_image_digest")
        if (
            not isinstance(runtime_revision, str)
            or _COMMIT.fullmatch(runtime_revision) is None
            or not isinstance(runtime_digest, str)
            or _OCI_DIGEST.fullmatch(runtime_digest) is None
            or receipt.get("provider_schema_core_baseline_digest")
            != hashlib.sha256(provider_baseline_bytes).hexdigest()
            or receipt.get("provider_schema_deployment_evidence_digest")
            != hashlib.sha256(provider_evidence_bytes).hexdigest()
        ):
            raise ValueError("github_provider_schema_receipt_invalid")
        _validate_provider_schema_core_baseline(
            provider_baseline,
            expected_source_revision=runtime_revision,
            expected_image_digest=runtime_digest,
        )
        provider_summary = _validate_provider_schema_evidence(
            provider_evidence,
            expected_application_source=expected_commit,
            expected_runtime_revision=runtime_revision,
            expected_plan_id=expected_plan_id,
        )
        return {
            **expected,
            "provider_schema_runtime_image_revision": runtime_revision,
            "provider_schema_runtime_image_digest": runtime_digest,
            "provider_schema_core_baseline_digest": hashlib.sha256(
                provider_baseline_bytes
            ).hexdigest(),
            "provider_schema_deployment_evidence_digest": hashlib.sha256(
                provider_evidence_bytes
            ).hexdigest(),
            "provider_schema": provider_summary,
        }
    observation_digest = hashlib.sha256(observation_bytes).hexdigest()
    if cost_governance:
        image_digest = receipt.get("cost_governance_image_digest")
        if (
            receipt.get("cost_governance_job_image_readback_digest") != observation_digest
            or not isinstance(image_digest, str)
            or _OCI_DIGEST.fullmatch(image_digest) is None
        ):
            raise ValueError("github_cost_governance_readback_invalid")
        _validate_cost_governance_readback(observation, expected_digest=image_digest)
        return {
            **expected,
            "cost_governance_image_digest": image_digest,
            "cost_governance_job_image_readback_digest": observation_digest,
        }
    inventory_receipt_digest = observation.get("receipt_digest")
    inventory_body = {key: item for key, item in observation.items() if key != "receipt_digest"}
    if (
        receipt.get("initial_inventory_execution_receipt_digest") != observation_digest
        or observation.get("schema_version")
        != "fdai.genesis-initial-inventory-execution-receipt.v1"
        or observation.get("source_commit") != expected_commit
        or observation.get("status") != "succeeded"
        or observation.get("active_generation_verified") is not False
        or observation.get("subscription_ready") is not False
        or not isinstance(inventory_receipt_digest, str)
        or _DIGEST.fullmatch(inventory_receipt_digest) is None
        or hashlib.sha256(
            json.dumps(inventory_body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        != inventory_receipt_digest
    ):
        raise ValueError("github_initial_inventory_receipt_invalid")
    return {
        "plan_id": expected_plan_id,
        "plan_digest": expected_plan_digest,
        "request_id": request_id_value,
        "context_digest": expected_context_digest,
        "source_commit": expected_commit,
        "status": "applied",
        "terraform_zero_change_verified": True,
        "migration_stage_verified": True,
        "runtime_health_verified": True,
        "canary_verified": True,
        "initial_inventory_execution_receipt_digest": observation_digest,
        "subscription_ready": False,
    }


def _validate_cost_governance_readback(
    value: Mapping[str, object],
    *,
    expected_digest: str,
) -> None:
    """Reject incomplete or mismatched Cost Governance Job observations."""
    if (
        set(value) != {"schema_version", "image_digest", "jobs"}
        or value.get("schema_version") != "fdai.cost-governance-job-image-readback.v1"
        or value.get("image_digest") != expected_digest
    ):
        raise ValueError("github_cost_governance_readback_invalid")
    jobs = value.get("jobs")
    expected_containers = {
        "analyzer": "cost-governance-analyzer",
        "collector": "cost-governance-collector",
    }
    if not isinstance(jobs, dict) or set(jobs) != set(expected_containers):
        raise ValueError("github_cost_governance_readback_invalid")
    for role, container in expected_containers.items():
        job = jobs[role]
        if (
            not isinstance(job, dict)
            or set(job) != {"container", "image_digest"}
            or job.get("container") != container
            or job.get("image_digest") != expected_digest
        ):
            raise ValueError("github_cost_governance_readback_invalid")

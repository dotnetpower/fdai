"""Protected plan artifact download and validation."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.github_artifact_io import _private_artifact_json
from fdai_deployment_cli.github_workflow_values import (
    _COMMIT,
    _DIGEST,
    _OCI_DIGEST,
    _PLAN_ID,
    CommandRunner,
)

_CORE_POST_APPLY_OBSERVATIONS = [
    "database-migrations",
    "runtime-health",
    "initial-inventory-execution",
    "canary-publisher",
    "terraform-zero-change",
]

_COST_GOVERNANCE_POST_APPLY_OBSERVATIONS = [
    "terraform-zero-change",
    "cost-governance-job-image-readback",
]

_PROVIDER_SCHEMA_POST_APPLY_OBSERVATIONS = [
    "terraform-zero-change",
    "provider-schema-core-baseline",
    "provider-schema-job-execution",
    "provider-schema-durable-generation",
    "provider-schema-agent-review",
]


def _download_plan_metadata(
    *,
    repository: str,
    workflow_run_id: int,
    request_id_value: str,
    expected_commit: str,
    expected_context_digest: str,
    run: CommandRunner,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="fdai-plan-status-") as raw_directory:
        directory = Path(raw_directory)
        result = run(
            (
                "run",
                "download",
                str(workflow_run_id),
                "--repo",
                repository,
                "--name",
                f"deployment-plan-metadata-{request_id_value}",
                "--dir",
                str(directory),
            )
        )
        if result.returncode != 0:
            raise ValueError("github_plan_metadata_unavailable")
        payload = _private_artifact_json(directory / "plan-metadata.json", "plan metadata")
    required = {
        "schema_version": "fdai.deployment-plan.v1",
        "request_id": request_id_value,
        "commit_sha": expected_commit,
        "context_digest": expected_context_digest,
        "status": "ready",
    }
    if any(payload.get(key) != value for key, value in required.items()):
        raise ValueError("github_plan_metadata_context_mismatch")
    plan_id = payload.get("plan_id")
    plan_digest = payload.get("plan_digest")
    context_digest = payload.get("context_digest")
    expires_at = payload.get("expires_at")
    if (
        not isinstance(plan_id, str)
        or _PLAN_ID.fullmatch(plan_id) is None
        or not isinstance(plan_digest, str)
        or _DIGEST.fullmatch(plan_digest) is None
        or not isinstance(context_digest, str)
        or _DIGEST.fullmatch(context_digest) is None
        or not isinstance(expires_at, str)
    ):
        raise ValueError("github_plan_metadata_invalid")
    summary = _plan_summary(payload.get("plan_summary"))
    observations = payload.get("post_apply_observations")
    provider_schema = request_id_value.startswith("plan-provider-")
    cost_governance = request_id_value.startswith("plan-cost-")
    expected_observations = (
        _PROVIDER_SCHEMA_POST_APPLY_OBSERVATIONS
        if provider_schema
        else (
            _COST_GOVERNANCE_POST_APPLY_OBSERVATIONS
            if cost_governance
            else _CORE_POST_APPLY_OBSERVATIONS
        )
    )
    if observations != expected_observations:
        raise ValueError("github_plan_metadata_observations_invalid")
    runtime_image = payload.get("runtime_image")
    expected_profile = (
        "cost-governance"
        if cost_governance or request_id_value.startswith("plan-provider-cost-")
        else "core-control-plane"
    )
    if (cost_governance or provider_schema) and (
        not isinstance(runtime_image, dict)
        or set(runtime_image) != {"source_revision", "digest", "profile"}
        or not isinstance(runtime_image.get("source_revision"), str)
        or _COMMIT.fullmatch(runtime_image["source_revision"]) is None
        or not isinstance(runtime_image.get("digest"), str)
        or _OCI_DIGEST.fullmatch(runtime_image["digest"]) is None
        or runtime_image.get("profile") != expected_profile
    ):
        raise ValueError("github_plan_metadata_runtime_image_invalid")
    projected: dict[str, object] = {
        "plan_id": plan_id,
        "plan_digest": plan_digest,
        "context_digest": context_digest,
        "expires_at": expires_at,
        "status": "ready",
        "plan_summary": summary,
        "post_apply_observations": observations,
    }
    if provider_schema and isinstance(runtime_image, dict):
        projected["runtime_image"] = dict(runtime_image)
    return projected


def _plan_summary(value: object) -> dict[str, object]:
    """Validate one address-free protected-plan action summary."""

    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "action_counts",
        "resource_type_counts",
        "managed_resources",
        "destructive",
        "summary_digest",
    }:
        raise ValueError("github_plan_summary_invalid")
    digest = value.get("summary_digest")
    body = {key: item for key, item in value.items() if key != "summary_digest"}
    if (
        value.get("schema_version") != "fdai.deployment-plan-summary.v1"
        or not isinstance(digest, str)
        or _DIGEST.fullmatch(digest) is None
        or canonical_digest(body) != digest
        or type(value.get("managed_resources")) is not int
        or int(value["managed_resources"]) < 0
        or type(value.get("destructive")) is not bool
    ):
        raise ValueError("github_plan_summary_invalid")
    actions = value.get("action_counts")
    expected_actions = {"create", "update", "delete", "replace", "no_op", "read"}
    if (
        not isinstance(actions, dict)
        or set(actions) != expected_actions
        or any(type(count) is not int or count < 0 for count in actions.values())
        or sum(actions.values()) != value["managed_resources"]
    ):
        raise ValueError("github_plan_summary_invalid")
    resource_types = value.get("resource_type_counts")
    if not isinstance(resource_types, dict) or len(resource_types) > 256:
        raise ValueError("github_plan_summary_invalid")
    for resource_type, counts in resource_types.items():
        if (
            not isinstance(resource_type, str)
            or not resource_type
            or len(resource_type) > 128
            or not isinstance(counts, dict)
            or not set(counts).issubset(expected_actions)
            or any(type(count) is not int or count <= 0 for count in counts.values())
        ):
            raise ValueError("github_plan_summary_invalid")
    return {str(key): item for key, item in value.items()}

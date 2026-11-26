#!/usr/bin/env python3
"""Build protected deployment-plan metadata from sealed workflow evidence."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

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


def build_plan_metadata(
    *,
    environ: Mapping[str, str],
    plan_summary: Mapping[str, object],
) -> dict[str, object]:
    """Return metadata bound to the exact plan, source, and post-apply evidence."""
    runtime_image_revision = environ.get("FDAI_RUNTIME_IMAGE_REVISION", "")
    runtime_image_digest = environ.get("FDAI_RUNTIME_IMAGE_DIGEST", "")
    runtime_image_profile = environ.get("FDAI_RUNTIME_IMAGE_PROFILE", "core-control-plane")
    if runtime_image_profile not in {"core-control-plane", "cost-governance"}:
        raise ValueError("runtime image profile is unsupported")
    if bool(runtime_image_revision) != bool(runtime_image_digest):
        raise ValueError("runtime image plan evidence is incomplete")
    if runtime_image_profile != "core-control-plane" and not runtime_image_revision:
        raise ValueError("non-default runtime image profile requires exact image evidence")
    plan_request_id = environ["PLAN_REQUEST_ID"]
    provider_schema = plan_request_id.startswith("plan-provider-")
    if provider_schema:
        expected_profile = (
            "cost-governance"
            if plan_request_id.startswith("plan-provider-cost-")
            else "core-control-plane"
        )
        if runtime_image_profile != expected_profile:
            raise ValueError("provider-schema request and runtime image profile do not match")
    metadata: dict[str, object] = {
        "schema_version": "fdai.deployment-plan.v1",
        "plan_id": environ["PLAN_ID"],
        "plan_digest": environ["PLAN_DIGEST"],
        "source_artifact_digest": environ["SOURCE_ARTIFACT_DIGEST"],
        "context_digest": environ["PLAN_CONTEXT_DIGEST"],
        "preflight_evidence_digest": environ["PREFLIGHT_EVIDENCE_DIGEST"],
        "azure_preflight_evidence_digest": environ["AZURE_PREFLIGHT_EVIDENCE_DIGEST"],
        "preflight_blocks": False,
        "commit_sha": environ["PLAN_COMMIT_SHA"],
        "request_id": plan_request_id,
        "request_kind": ("model" if plan_request_id.startswith("plan-model-") else "standard"),
        "created_at": environ["CREATED_AT"],
        "expires_at": environ["EXPIRES_AT"],
        "status": "ready",
        "workflow_run_id": environ["GITHUB_RUN_ID"],
        "plan_summary": dict(plan_summary),
        "post_apply_observations": list(
            _PROVIDER_SCHEMA_POST_APPLY_OBSERVATIONS
            if provider_schema
            else (
                _COST_GOVERNANCE_POST_APPLY_OBSERVATIONS
                if runtime_image_profile == "cost-governance"
                else _CORE_POST_APPLY_OBSERVATIONS
            )
        ),
    }
    if runtime_image_revision:
        metadata["runtime_image"] = {
            "source_revision": runtime_image_revision,
            "digest": runtime_image_digest,
            "profile": runtime_image_profile,
        }
    resolved_models_path = environ.get("FDAI_RESOLVED_MODELS_PATH", "")
    deployment_models_path = environ.get("FDAI_DEPLOYMENT_MODELS_PATH", "")
    if bool(resolved_models_path) != bool(deployment_models_path):
        raise ValueError("protected plan model-resolution evidence is incomplete")
    if not resolved_models_path:
        return metadata
    resolved_digest = environ.get("FDAI_RESOLVED_MODELS_SHA256", "")
    deployment_digest = environ.get("FDAI_DEPLOYMENT_MODELS_SHA256", "")
    if not all(_is_digest(value) for value in (resolved_digest, deployment_digest)):
        raise ValueError("protected plan model-resolution evidence is incomplete")
    resolved_path = Path(resolved_models_path)
    if not resolved_path.is_file() or not Path(deployment_models_path).is_file():
        raise ValueError("protected plan model-resolution evidence is incomplete")
    resolved_payload = _load_json_object(resolved_path, "resolved model manifest")
    model_resolution: dict[str, object] = {
        "resolved_models_digest": resolved_digest,
        "deployment_models_digest": deployment_digest,
        "chatops_channel_validation": environ.get("VALIDATE_CHATOPS_CHANNELS") == "true",
    }
    binding_policy = resolved_payload.get("binding_policy")
    if binding_policy is not None:
        if not isinstance(binding_policy, dict):
            raise ValueError("protected plan binding-policy evidence is invalid")
        model_resolution.update(
            {
                "binding_policy_environment": binding_policy.get("environment"),
                "binding_policy_revision": binding_policy.get("revision"),
                "binding_policy_digest": binding_policy.get("digest"),
                "binding_policy_expected_active_digest": binding_policy.get(
                    "expected_active_digest"
                ),
                "active_core_revision": environ.get("ACTIVE_CORE_REVISION"),
                "active_core_image_digest": environ.get("ACTIVE_CORE_IMAGE_DIGEST"),
                "active_core_model_digest": environ.get("ACTIVE_CORE_MODEL_DIGEST"),
            }
        )
    if metadata["request_kind"] == "model" and binding_policy is None:
        raise ValueError("model plan has no binding-policy evidence")
    metadata["model_resolution"] = model_resolution
    return metadata


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain an object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = _load_json_object(args.plan_summary, "deployment plan summary")
        metadata = build_plan_metadata(environ=os.environ, plan_summary=summary)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    args.output.write_text(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

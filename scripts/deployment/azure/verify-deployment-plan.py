#!/usr/bin/env python3
"""Verify a protected Terraform plan against sanitized immutable metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_OCI_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_COMMIT = re.compile(r"^[a-f0-9]{40}$")
_PLAN_ID = re.compile(r"^plan-[1-9][0-9]*-[1-9][0-9]*$")
_ENVIRONMENT = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_SHA256_REF = re.compile(r"^sha256:[a-f0-9]{64}$")
_REQUEST_KINDS = frozenset({"standard", "model", "event-bus", "event-bus-jobs"})
_MAX_PLAN_BYTES: Final[int] = 512 * 1024 * 1024
_MAX_METADATA_BYTES: Final[int] = 64 * 1024
_BASE_METADATA_FIELDS = frozenset(
    {
        "schema_version",
        "plan_id",
        "plan_digest",
        "source_artifact_digest",
        "context_digest",
        "preflight_evidence_digest",
        "azure_preflight_evidence_digest",
        "preflight_blocks",
        "commit_sha",
        "request_id",
        "request_kind",
        "created_at",
        "expires_at",
        "status",
        "workflow_run_id",
    }
)
_RUNTIME_IMAGE_FIELDS = frozenset({"source_revision", "digest"})
_MODEL_RESOLUTION_FIELDS = frozenset({"resolved_models_digest", "deployment_models_digest"})
_MODEL_VALIDATION_FIELDS = frozenset({"chatops_channel_validation"})
_MODEL_BINDING_FIELDS = frozenset(
    {
        "binding_policy_environment",
        "binding_policy_revision",
        "binding_policy_digest",
        "binding_policy_expected_active_digest",
        "active_core_revision",
        "active_core_image_digest",
        "active_core_model_digest",
    }
)


class PlanVerificationError(RuntimeError):
    """The stored plan cannot be safely applied."""


def verify_plan(
    plan_path: Path,
    source_artifact_path: Path,
    metadata_path: Path,
    preflight_evidence_path: Path,
    azure_preflight_evidence_path: Path,
    *,
    expected_plan_id: str,
    expected_plan_digest: str,
    expected_context_digest: str,
    expected_commit_sha: str,
    expected_request_kind: str,
    expected_environment: str,
    now: datetime,
) -> None:
    """Raise unless the exact binary plan and metadata remain apply-eligible."""
    for path, label, maximum in (
        (plan_path, "plan", _MAX_PLAN_BYTES),
        (source_artifact_path, "source artifact", _MAX_PLAN_BYTES),
        (metadata_path, "metadata", _MAX_METADATA_BYTES),
        (preflight_evidence_path, "preflight evidence", _MAX_METADATA_BYTES),
        (azure_preflight_evidence_path, "Azure preflight evidence", _MAX_METADATA_BYTES),
    ):
        if path.is_symlink() or not path.is_file():
            raise PlanVerificationError(f"{label} MUST be a regular file")
        if path.stat().st_size > maximum:
            raise PlanVerificationError(f"{label} exceeds the size limit")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlanVerificationError("plan metadata is invalid JSON") from exc
    if not isinstance(metadata, dict):
        raise PlanVerificationError("plan metadata has an unexpected schema")
    optional_fields = set(metadata) - _BASE_METADATA_FIELDS
    if not _BASE_METADATA_FIELDS.issubset(metadata) or not optional_fields.issubset(
        {"runtime_image", "model_resolution"}
    ):
        raise PlanVerificationError("plan metadata has an unexpected schema")
    if metadata.get("schema_version") != "fdai.deployment-plan.v1":
        raise PlanVerificationError("plan metadata schema version is unsupported")
    _expect(metadata, "plan_id", expected_plan_id, _PLAN_ID)
    _expect(metadata, "plan_digest", expected_plan_digest, _DIGEST)
    source_artifact_digest = metadata.get("source_artifact_digest")
    if (
        not isinstance(source_artifact_digest, str)
        or _DIGEST.fullmatch(source_artifact_digest) is None
    ):
        raise PlanVerificationError("plan metadata source artifact digest is invalid")
    if _sha256(source_artifact_path) != source_artifact_digest:
        raise PlanVerificationError("source artifact digest does not match metadata")
    _expect(metadata, "context_digest", expected_context_digest, _DIGEST)
    preflight_digest = metadata.get("preflight_evidence_digest")
    if not isinstance(preflight_digest, str) or _DIGEST.fullmatch(preflight_digest) is None:
        raise PlanVerificationError("plan metadata preflight evidence digest is invalid")
    if _sha256(preflight_evidence_path) != preflight_digest:
        raise PlanVerificationError("preflight evidence digest does not match metadata")
    azure_preflight_digest = metadata.get("azure_preflight_evidence_digest")
    if (
        not isinstance(azure_preflight_digest, str)
        or _DIGEST.fullmatch(azure_preflight_digest) is None
    ):
        raise PlanVerificationError("plan metadata Azure preflight evidence digest is invalid")
    if _sha256(azure_preflight_evidence_path) != azure_preflight_digest:
        raise PlanVerificationError("Azure preflight evidence digest does not match metadata")
    if metadata.get("preflight_blocks") is not False:
        raise PlanVerificationError("plan is blocked by deployment preflight")
    _expect(metadata, "commit_sha", expected_commit_sha, _COMMIT)
    request_kind = metadata.get("request_kind")
    if request_kind not in _REQUEST_KINDS or request_kind != expected_request_kind:
        raise PlanVerificationError("plan metadata request kind does not match the request")
    runtime_image = metadata.get("runtime_image")
    if runtime_image is not None:
        if not isinstance(runtime_image, dict) or set(runtime_image) != _RUNTIME_IMAGE_FIELDS:
            raise PlanVerificationError("plan metadata runtime image has an unexpected schema")
        source_revision = runtime_image.get("source_revision")
        image_digest = runtime_image.get("digest")
        if not isinstance(source_revision, str) or _COMMIT.fullmatch(source_revision) is None:
            raise PlanVerificationError("plan metadata runtime image revision is invalid")
        if not isinstance(image_digest, str) or _OCI_DIGEST.fullmatch(image_digest) is None:
            raise PlanVerificationError("plan metadata runtime image digest is invalid")
    model_resolution = metadata.get("model_resolution")
    if model_resolution is not None:
        fields = set(model_resolution) if isinstance(model_resolution, dict) else set()
        allowed_fields = {
            _MODEL_RESOLUTION_FIELDS,
            _MODEL_RESOLUTION_FIELDS | _MODEL_VALIDATION_FIELDS,
            _MODEL_RESOLUTION_FIELDS | _MODEL_BINDING_FIELDS,
            _MODEL_RESOLUTION_FIELDS | _MODEL_BINDING_FIELDS | _MODEL_VALIDATION_FIELDS,
        }
        if not isinstance(model_resolution, dict) or fields not in allowed_fields:
            raise PlanVerificationError("plan metadata model resolution has an unexpected schema")
        for field in _MODEL_RESOLUTION_FIELDS:
            digest = model_resolution[field]
            if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
                raise PlanVerificationError("plan metadata model resolution digest is invalid")
        if "chatops_channel_validation" in fields and not isinstance(
            model_resolution["chatops_channel_validation"], bool
        ):
            raise PlanVerificationError("plan metadata ChatOps validation flag is invalid")
        if _MODEL_BINDING_FIELDS.issubset(fields):
            policy_environment = model_resolution["binding_policy_environment"]
            policy_revision = model_resolution["binding_policy_revision"]
            policy_digest = model_resolution["binding_policy_digest"]
            expected_active_digest = model_resolution["binding_policy_expected_active_digest"]
            active_revision = model_resolution["active_core_revision"]
            active_image_digest = model_resolution["active_core_image_digest"]
            active_model_digest = model_resolution["active_core_model_digest"]
            if (
                not isinstance(policy_environment, str)
                or _ENVIRONMENT.fullmatch(policy_environment) is None
                or policy_environment != expected_environment
                or not isinstance(policy_revision, int)
                or isinstance(policy_revision, bool)
                or policy_revision < 1
                or not isinstance(policy_digest, str)
                or _SHA256_REF.fullmatch(policy_digest) is None
                or not isinstance(expected_active_digest, str)
                or _SHA256_REF.fullmatch(expected_active_digest) is None
                or not isinstance(active_revision, str)
                or not active_revision.strip()
                or len(active_revision) > 128
                or not isinstance(active_image_digest, str)
                or _DIGEST.fullmatch(active_image_digest) is None
                or not isinstance(active_model_digest, str)
                or _DIGEST.fullmatch(active_model_digest) is None
                or expected_active_digest != f"sha256:{active_model_digest}"
            ):
                raise PlanVerificationError("plan metadata model binding provenance is invalid")
        elif request_kind == "model":
            raise PlanVerificationError("model plan metadata has no binding policy provenance")
    elif request_kind == "model":
        raise PlanVerificationError("model plan metadata has no model resolution evidence")
    if metadata.get("status") != "ready":
        raise PlanVerificationError("plan metadata status is not ready")
    expires_at = _timestamp(metadata.get("expires_at"))
    created_at = _timestamp(metadata.get("created_at"))
    if expires_at <= created_at:
        raise PlanVerificationError("plan metadata expiry is invalid")
    if now.astimezone(UTC) >= expires_at:
        raise PlanVerificationError("plan has expired")
    actual_digest = _sha256(plan_path)
    if actual_digest != expected_plan_digest:
        raise PlanVerificationError("binary plan digest does not match metadata")


def _expect(
    metadata: dict[str, object],
    field: str,
    expected: str,
    pattern: re.Pattern[str],
) -> None:
    actual = metadata.get(field)
    if not isinstance(actual, str) or pattern.fullmatch(actual) is None or actual != expected:
        raise PlanVerificationError(f"plan metadata {field} does not match the request")


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise PlanVerificationError("plan metadata timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlanVerificationError("plan metadata timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise PlanVerificationError("plan metadata timestamp is missing a timezone")
    return parsed.astimezone(UTC)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source-artifact", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--preflight-evidence", type=Path, required=True)
    parser.add_argument("--azure-preflight-evidence", type=Path, required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--plan-digest", required=True)
    parser.add_argument("--context-digest", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--request-kind", choices=sorted(_REQUEST_KINDS), required=True)
    parser.add_argument("--environment", required=True)
    args = parser.parse_args(argv)
    try:
        verify_plan(
            args.plan,
            args.source_artifact,
            args.metadata,
            args.preflight_evidence,
            args.azure_preflight_evidence,
            expected_plan_id=args.plan_id,
            expected_plan_digest=args.plan_digest,
            expected_context_digest=args.context_digest,
            expected_commit_sha=args.commit_sha,
            expected_request_kind=args.request_kind,
            expected_environment=args.environment,
            now=datetime.now(UTC),
        )
    except (OSError, PlanVerificationError) as exc:
        print(f"plan verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"verified protected plan {args.plan_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

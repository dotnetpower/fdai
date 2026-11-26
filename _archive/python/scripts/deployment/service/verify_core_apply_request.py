#!/usr/bin/env python3
"""Verify a bot-owned protected Core service apply request."""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
_POSITIVE_INTEGER_PATTERN = re.compile(r"[1-9][0-9]*")
_PLAN_SCHEMA_VERSION = "fdai.service-deployment-plan.v6"
_SERVICE = "core-control-plane"
_WORKFLOW_PATH = ".github/workflows/service-deploy.yml"


class CoreApplyRequestError(ValueError):
    """Raised when a protected Core apply request is incomplete or mismatched."""


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoreApplyRequestError(f"{path.name} must contain readable JSON") from exc
    if not isinstance(payload, dict):
        raise CoreApplyRequestError(f"{path.name} must contain a JSON object")
    return payload


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise CoreApplyRequestError(f"plan metadata {field} must be an ISO 8601 timestamp") from exc
    if timestamp.tzinfo is None:
        raise CoreApplyRequestError(f"plan metadata {field} must include a timezone")
    return timestamp.astimezone(UTC)


def verify_core_apply_request(
    *,
    run: dict[str, Any],
    metadata: dict[str, Any],
    repository: str,
    environment: str,
    commit_sha: str,
    image_ref: str,
    plan_run_id: str,
    plan_run_attempt: str,
    plan_digest: str,
    context_digest: str,
    now: datetime,
) -> None:
    """Fail unless the request matches one unexpired protected Core plan."""
    if environment not in {"dev", "staging"}:
        raise CoreApplyRequestError("Core service apply is available only for dev and staging")
    if _COMMIT_PATTERN.fullmatch(commit_sha) is None:
        raise CoreApplyRequestError("commit_sha must be a lowercase 40-character git SHA")
    if _POSITIVE_INTEGER_PATTERN.fullmatch(plan_run_id) is None:
        raise CoreApplyRequestError("plan_run_id must be a positive integer")
    if _POSITIVE_INTEGER_PATTERN.fullmatch(plan_run_attempt) is None:
        raise CoreApplyRequestError("plan_run_attempt must be a positive integer")
    if _DIGEST_PATTERN.fullmatch(plan_digest) is None:
        raise CoreApplyRequestError("plan_digest must be a lowercase SHA-256 digest")
    if _DIGEST_PATTERN.fullmatch(context_digest) is None:
        raise CoreApplyRequestError("context_digest must be a lowercase SHA-256 digest")

    expected_image_prefix = f"ghcr.io/{repository.lower()}/fdai-{_SERVICE}@sha256:"
    if not image_ref.startswith(expected_image_prefix):
        raise CoreApplyRequestError("image_ref must target the repository Core image")
    image_digest = image_ref.removeprefix(expected_image_prefix)
    if _DIGEST_PATTERN.fullmatch(image_digest) is None:
        raise CoreApplyRequestError("image_ref must be pinned by a lowercase SHA-256 digest")

    expected_run = {
        "id": int(plan_run_id),
        "run_attempt": int(plan_run_attempt),
        "conclusion": "success",
        "event": "workflow_dispatch",
        "path": _WORKFLOW_PATH,
    }
    for field, expected in expected_run.items():
        if run.get(field) != expected:
            raise CoreApplyRequestError(f"source plan run {field} does not match the request")
    if _COMMIT_PATTERN.fullmatch(str(run.get("head_sha", ""))) is None:
        raise CoreApplyRequestError("source plan run head_sha is invalid")
    run_repository = run.get("repository")
    if not isinstance(run_repository, dict) or run_repository.get("full_name") != repository:
        raise CoreApplyRequestError("source plan run repository does not match the request")

    expected_metadata = {
        "schema_version": _PLAN_SCHEMA_VERSION,
        "status": "ready",
        "plan_id": f"{_SERVICE}-{environment}-{plan_run_id}-{plan_run_attempt}",
        "service": _SERVICE,
        "environment": environment,
        "commit_sha": commit_sha,
        "image_ref": image_ref,
        "image_digest": f"sha256:{image_digest}",
        "plan_digest": plan_digest,
        "context_digest": context_digest,
        "workflow_run_id": plan_run_id,
        "workflow_run_attempt": plan_run_attempt,
        "degraded_recovery": False,
        "deployment_mode": "model-binding",
    }
    for field, expected in expected_metadata.items():
        if metadata.get(field) != expected:
            raise CoreApplyRequestError(f"plan metadata {field} does not match the request")

    created_at = _parse_timestamp(metadata.get("created_at"), field="created_at")
    expires_at = _parse_timestamp(metadata.get("expires_at"), field="expires_at")
    current_time = now.astimezone(UTC)
    if created_at > current_time:
        raise CoreApplyRequestError("plan metadata created_at is in the future")
    if expires_at <= current_time:
        raise CoreApplyRequestError("protected Core plan has expired")
    if expires_at <= created_at:
        raise CoreApplyRequestError("plan metadata expiration does not follow creation")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-json", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--plan-run-id", required=True)
    parser.add_argument("--plan-run-attempt", required=True)
    parser.add_argument("--plan-digest", required=True)
    parser.add_argument("--context-digest", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        verify_core_apply_request(
            run=_read_object(args.run_json),
            metadata=_read_object(args.metadata),
            repository=args.repository,
            environment=args.environment,
            commit_sha=args.commit_sha,
            image_ref=args.image_ref,
            plan_run_id=args.plan_run_id,
            plan_run_attempt=args.plan_run_attempt,
            plan_digest=args.plan_digest,
            context_digest=args.context_digest,
            now=datetime.now(UTC),
        )
    except CoreApplyRequestError as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

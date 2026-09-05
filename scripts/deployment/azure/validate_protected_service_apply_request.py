from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_POSITIVE_INTEGER = re.compile(r"^[1-9][0-9]*$")
_LOWER_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_LOWER_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_SERVICE_CONTRACTS = {
    "core-control-plane": (
        "fdai-core-control-plane",
        frozenset(
            {
                "standard",
                "database-host-binding",
                "model-binding",
                "database-host-binding+model-binding",
            }
        ),
    ),
    "document-ingestion-api": (
        "fdai-document-ingestion-api",
        frozenset(
            {
                "standard",
                "database-host-binding",
                "sharepoint-connector-enable",
                "sharepoint-connector-disable",
            }
        ),
    ),
}


class ProtectedServiceApplyRequestError(ValueError):
    """Raised when a bot-owned service apply request is not exactly plan-bound."""


def validate_protected_service_apply_request(
    *,
    repository: str,
    service: str,
    environment: str,
    commit_sha: str,
    plan_run_id: str,
    plan_run_attempt: str,
    plan_digest: str,
    context_digest: str,
    image_ref: str,
    run_metadata: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    plan_metadata: Mapping[str, Any],
    now: datetime | None = None,
) -> None:
    """Validate one bounded service apply request before the bot dispatches it."""

    if environment not in {"dev", "staging"}:
        raise ProtectedServiceApplyRequestError(
            "Service bot-owned apply is available only for dev and staging."
        )
    service_contract = _SERVICE_CONTRACTS.get(service)
    if service_contract is None:
        raise ProtectedServiceApplyRequestError("Service is not approved for bot-owned apply.")
    image_name, deployment_modes = service_contract
    if not _LOWER_HEX_40.fullmatch(commit_sha):
        raise ProtectedServiceApplyRequestError("Commit SHA must be lowercase 40-character hex.")
    if not _POSITIVE_INTEGER.fullmatch(plan_run_id):
        raise ProtectedServiceApplyRequestError("Plan run id must be a positive integer.")
    if not _POSITIVE_INTEGER.fullmatch(plan_run_attempt):
        raise ProtectedServiceApplyRequestError("Plan run attempt must be a positive integer.")
    if not _LOWER_HEX_64.fullmatch(plan_digest):
        raise ProtectedServiceApplyRequestError("Plan digest must be lowercase SHA-256.")
    if not _LOWER_HEX_64.fullmatch(context_digest):
        raise ProtectedServiceApplyRequestError("Context digest must be lowercase SHA-256.")

    image_pattern = re.compile(
        rf"^ghcr\.io/{re.escape(repository.lower())}/"
        rf"{re.escape(image_name)}@sha256:[0-9a-f]{{64}}$"
    )
    if not image_pattern.fullmatch(image_ref):
        raise ProtectedServiceApplyRequestError(
            "Image reference must be the approved repository service image pinned by SHA-256."
        )

    expected_run_id = int(plan_run_id)
    expected_attempt = int(plan_run_attempt)
    expected_run = {
        "id": expected_run_id,
        "run_attempt": expected_attempt,
        "name": "service-deploy",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
    }
    for field, expected in expected_run.items():
        if run_metadata.get(field) != expected:
            raise ProtectedServiceApplyRequestError(
                f"Plan workflow metadata field {field!r} is not the expected protected value."
            )
    run_repository = run_metadata.get("repository")
    if not isinstance(run_repository, Mapping) or run_repository.get("full_name") != repository:
        raise ProtectedServiceApplyRequestError(
            "Plan workflow metadata does not belong to the target repository."
        )

    artifact_values = artifacts.get("artifacts")
    if not isinstance(artifact_values, list):
        raise ProtectedServiceApplyRequestError("Plan artifact response must contain an array.")
    expected_name = f"service-plan-{service}-{environment}-{plan_run_id}-{plan_run_attempt}"
    matching = [
        artifact
        for artifact in artifact_values
        if isinstance(artifact, Mapping) and artifact.get("name") == expected_name
    ]
    if len(matching) != 1 or matching[0].get("expired") is not False:
        raise ProtectedServiceApplyRequestError(
            "Exactly one unexpired protected service plan artifact is required."
        )

    expected_plan = {
        "plan_id": (f"{service}-{environment}-{plan_run_id}-{plan_run_attempt}"),
        "workflow_run_id": plan_run_id,
        "workflow_run_attempt": plan_run_attempt,
        "service": service,
        "environment": environment,
        "status": "ready",
        "commit_sha": commit_sha,
        "plan_digest": plan_digest,
        "context_digest": context_digest,
        "image_ref": image_ref,
        "image_digest": image_ref.rsplit("@", maxsplit=1)[1],
    }
    for field, expected in expected_plan.items():
        if plan_metadata.get(field) != expected:
            raise ProtectedServiceApplyRequestError(
                f"Plan metadata field {field!r} is not bound to the requested service apply."
            )
    deployment_mode = plan_metadata.get("deployment_mode")
    if not isinstance(deployment_mode, str) or deployment_mode not in deployment_modes:
        raise ProtectedServiceApplyRequestError(
            "Plan deployment mode is not approved for the requested service apply."
        )

    expires_at = plan_metadata.get("expires_at")
    if not isinstance(expires_at, str):
        raise ProtectedServiceApplyRequestError("Plan expiry must be an RFC 3339 timestamp.")
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtectedServiceApplyRequestError(
            "Plan expiry must be an RFC 3339 timestamp."
        ) from exc
    if expiry.tzinfo is None:
        raise ProtectedServiceApplyRequestError("Plan expiry must include a time zone.")
    if expiry <= (now or datetime.now(UTC)):
        raise ProtectedServiceApplyRequestError("Protected service plan has expired.")


def _load_object(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProtectedServiceApplyRequestError(f"Unable to read {label}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProtectedServiceApplyRequestError(f"{label} must contain valid JSON.") from exc
    if not isinstance(payload, Mapping):
        raise ProtectedServiceApplyRequestError(f"{label} must contain a JSON object.")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--plan-run-id", required=True)
    parser.add_argument("--plan-run-attempt", required=True)
    parser.add_argument("--plan-digest", required=True)
    parser.add_argument("--context-digest", required=True)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--run-metadata", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--plan-metadata", type=Path, required=True)
    args = parser.parse_args()

    try:
        validate_protected_service_apply_request(
            repository=args.repository,
            service=args.service,
            environment=args.environment,
            commit_sha=args.commit_sha,
            plan_run_id=args.plan_run_id,
            plan_run_attempt=args.plan_run_attempt,
            plan_digest=args.plan_digest,
            context_digest=args.context_digest,
            image_ref=args.image_ref,
            run_metadata=_load_object(args.run_metadata, label="plan workflow metadata"),
            artifacts=_load_object(args.artifacts, label="plan artifact response"),
            plan_metadata=_load_object(args.plan_metadata, label="plan metadata"),
        )
    except ProtectedServiceApplyRequestError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

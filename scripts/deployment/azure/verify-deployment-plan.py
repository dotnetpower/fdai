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
_COMMIT = re.compile(r"^[a-f0-9]{40}$")
_PLAN_ID = re.compile(r"^plan-[1-9][0-9]*-[1-9][0-9]*$")
_MAX_PLAN_BYTES: Final[int] = 512 * 1024 * 1024
_MAX_METADATA_BYTES: Final[int] = 64 * 1024
_METADATA_FIELDS = frozenset(
    {
        "schema_version",
        "plan_id",
        "plan_digest",
        "context_digest",
        "preflight_evidence_digest",
        "azure_preflight_evidence_digest",
        "preflight_blocks",
        "commit_sha",
        "request_id",
        "created_at",
        "expires_at",
        "status",
        "workflow_run_id",
    }
)


class PlanVerificationError(RuntimeError):
    """The stored plan cannot be safely applied."""


def verify_plan(
    plan_path: Path,
    metadata_path: Path,
    preflight_evidence_path: Path,
    azure_preflight_evidence_path: Path,
    *,
    expected_plan_id: str,
    expected_plan_digest: str,
    expected_context_digest: str,
    expected_commit_sha: str,
    now: datetime,
) -> None:
    """Raise unless the exact binary plan and metadata remain apply-eligible."""
    for path, label, maximum in (
        (plan_path, "plan", _MAX_PLAN_BYTES),
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
    if not isinstance(metadata, dict) or set(metadata) != _METADATA_FIELDS:
        raise PlanVerificationError("plan metadata has an unexpected schema")
    if metadata.get("schema_version") != "fdai.deployment-plan.v1":
        raise PlanVerificationError("plan metadata schema version is unsupported")
    _expect(metadata, "plan_id", expected_plan_id, _PLAN_ID)
    _expect(metadata, "plan_digest", expected_plan_digest, _DIGEST)
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
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--preflight-evidence", type=Path, required=True)
    parser.add_argument("--azure-preflight-evidence", type=Path, required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--plan-digest", required=True)
    parser.add_argument("--context-digest", required=True)
    parser.add_argument("--commit-sha", required=True)
    args = parser.parse_args(argv)
    try:
        verify_plan(
            args.plan,
            args.metadata,
            args.preflight_evidence,
            args.azure_preflight_evidence,
            expected_plan_id=args.plan_id,
            expected_plan_digest=args.plan_digest,
            expected_context_digest=args.context_digest,
            expected_commit_sha=args.commit_sha,
            now=datetime.now(UTC),
        )
    except (OSError, PlanVerificationError) as exc:
        print(f"plan verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"verified protected plan {args.plan_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

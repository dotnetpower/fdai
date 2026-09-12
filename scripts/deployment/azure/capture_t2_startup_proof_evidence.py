#!/usr/bin/env python3
"""Capture bounded deployed T2 startup-proof reuse evidence from PostgreSQL."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from jsonschema import Draft202012Validator, FormatChecker
from psycopg.rows import dict_row
from scripts.deployment.azure.t2_startup_proof_evidence import (
    CORRELATION_PREFIX,
    T2StartupProofEvidenceError,
    T2StartupProofEvidencePendingError,
    build_t2_startup_proof_evidence,
    metering_query_window,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_SCHEMA = _REPO_ROOT / "config" / "t2-startup-proof-evidence.schema.json"
_REPORT_KEY = "runtime:startup-readiness:latest"


def _timestamp_argument(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise T2StartupProofEvidenceError(f"{field} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise T2StartupProofEvidenceError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _read_report(dsn: str) -> dict[str, Any] | None:
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=10) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        connection.execute("SET LOCAL statement_timeout = 15000")
        row = connection.execute(
            "SELECT value FROM state_kv WHERE key = %s",
            (_REPORT_KEY,),
        ).fetchone()
    if row is None:
        return None
    value = row["value"]
    if not isinstance(value, dict):
        raise T2StartupProofEvidenceError("startup readiness state is not a JSON object")
    return dict(value)


def _read_invocations(
    dsn: str,
    *,
    started_at: datetime,
    captured_at: datetime,
) -> tuple[Mapping[str, Any], ...]:
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=10) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        connection.execute("SET LOCAL statement_timeout = 15000")
        rows = connection.execute(
            """
            SELECT occurred_at, correlation_id, capability_id, model_key, mode,
                   usage_scope, prompt_tokens, completion_tokens, cost, currency
              FROM llm_invocation
             WHERE correlation_id LIKE %s
               AND occurred_at >= %s
               AND occurred_at <= %s
             ORDER BY occurred_at, invocation_id
            """,
            (f"{CORRELATION_PREFIX}model.cross-check.%", started_at, captured_at),
        ).fetchall()
    return tuple(dict(row) for row in rows)


def _capture(args: argparse.Namespace) -> dict[str, object]:
    dsn = os.environ.get(args.dsn_env, "").strip()
    if not dsn:
        raise T2StartupProofEvidenceError(f"{args.dsn_env} is required")
    dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    revision_created_at = _timestamp_argument(
        args.revision_created_at,
        "revision_created_at",
    )
    deadline = time.monotonic() + args.timeout_seconds
    pending_reason = "startup readiness report is unavailable"
    while True:
        captured_at = datetime.now(UTC)
        report = _read_report(dsn)
        if report is not None:
            try:
                started_at, _window_end = metering_query_window(
                    report,
                    captured_at=captured_at,
                    minimum_reuse_count=args.minimum_reuse_count,
                    maximum_proof_age_seconds=args.maximum_proof_age_seconds,
                )
                invocations = _read_invocations(
                    dsn,
                    started_at=started_at,
                    captured_at=captured_at,
                )
                return build_t2_startup_proof_evidence(
                    report,
                    invocations,
                    source_revision=args.source_revision,
                    image_digest=args.image_digest,
                    revision_ref_digest=args.revision_ref_digest,
                    replica_ref_digest=args.replica_ref_digest,
                    source_identity_digest=args.source_identity_digest,
                    environment=args.environment,
                    workflow_run_id=args.workflow_run_id,
                    workflow_run_attempt=args.workflow_run_attempt,
                    captured_at=captured_at,
                    revision_created_at=revision_created_at,
                    minimum_reuse_count=args.minimum_reuse_count,
                    maximum_proof_age_seconds=args.maximum_proof_age_seconds,
                )
            except T2StartupProofEvidencePendingError as exc:
                pending_reason = str(exc)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise T2StartupProofEvidenceError(
                f"timed out waiting for capture-ready startup evidence: {pending_reason}"
            )
        time.sleep(min(args.poll_seconds, remaining))


def _write_validated(receipt: Mapping[str, object], *, schema_path: Path, output: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn-env", default="FDAI_STARTUP_EVIDENCE_DSN")
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--revision-ref-digest", required=True)
    parser.add_argument("--replica-ref-digest", required=True)
    parser.add_argument("--source-identity-digest", required=True)
    parser.add_argument("--revision-created-at", required=True)
    parser.add_argument("--environment", choices=("dev", "staging", "prod"), required=True)
    parser.add_argument("--workflow-run-id", type=int, required=True)
    parser.add_argument("--workflow-run-attempt", type=int, required=True)
    parser.add_argument("--minimum-reuse-count", type=int, default=2)
    parser.add_argument("--maximum-proof-age-seconds", type=int, default=1_800)
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--schema", type=Path, default=_DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    """Capture and validate one sanitized receipt without logging live values."""

    args = _parser().parse_args()
    if not 1 <= args.timeout_seconds <= 1_800:
        print("capture-t2-startup-proof-evidence: timeout must be between 1 and 1800 seconds")
        return 2
    if not 0.1 <= args.poll_seconds <= 60:
        print("capture-t2-startup-proof-evidence: poll interval must be between 0.1 and 60 seconds")
        return 2
    try:
        receipt = _capture(args)
        _write_validated(receipt, schema_path=args.schema, output=args.output)
    except (OSError, T2StartupProofEvidenceError, psycopg.Error) as exc:
        detail = str(exc) if isinstance(exc, T2StartupProofEvidenceError) else type(exc).__name__
        print(f"capture-t2-startup-proof-evidence: ERROR: {detail}", file=sys.stderr)
        return 1
    print(
        "capture-t2-startup-proof-evidence: OK "
        f"(candidates={receipt['candidate_count']} reuse_floor={receipt['minimum_reuse_count']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

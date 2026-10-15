#!/usr/bin/env python3
"""Verify one deployed synthetic canary through its consumed Core audit row."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import psycopg
from psycopg.rows import dict_row

_CANARY_ACTOR = "fdai.canary-job"
_CANARY_ACTION_KIND = "control_loop.canary"


class CanaryAuditVerificationError(RuntimeError):
    """A canary audit is unavailable, ambiguous, malformed, or outside budget."""


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    host: str
    database: str
    user: str
    password: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> DatabaseConfig:
        values = {
            "host": environ.get("FDAI_CANARY_POSTGRES_HOST", "").strip(),
            "database": environ.get("FDAI_CANARY_POSTGRES_DATABASE", "").strip(),
            "user": environ.get("TF_VAR_postgres_admin_login", "").strip(),
            "password": environ.get("TF_VAR_postgres_admin_password", ""),
        }
        missing = sorted(name for name, value in values.items() if not value)
        if missing:
            raise CanaryAuditVerificationError(
                f"canary audit database configuration is incomplete: {', '.join(missing)}"
            )
        return cls(**values)


def _read_canary_audits(
    config: DatabaseConfig,
    *,
    correlation_id: str,
) -> tuple[dict[str, Any], ...]:
    with psycopg.connect(
        host=config.host,
        dbname=config.database,
        user=config.user,
        password=config.password,
        sslmode="require",
        connect_timeout=10,
        row_factory=dict_row,
    ) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        connection.execute("SET LOCAL statement_timeout = 15000")
        rows = connection.execute(
            """
            SELECT entry
              FROM audit_log
             WHERE entry->>'correlation_id' = %s
               AND entry->>'action_kind' = %s
             ORDER BY seq DESC
             LIMIT 2
            """,
            (correlation_id, _CANARY_ACTION_KIND),
        ).fetchall()
    audits: list[dict[str, Any]] = []
    for row in rows:
        entry = row.get("entry")
        if not isinstance(entry, dict):
            raise CanaryAuditVerificationError("canary audit entry is not a JSON object")
        audits.append(dict(entry))
    return tuple(audits)


def verify_canary_audit(
    entry: Mapping[str, object],
    *,
    slot: str,
    latency_budget_ms: int,
    verified_at: datetime,
) -> dict[str, object]:
    """Return one sanitized receipt only for the exact successful canary audit."""

    if verified_at.tzinfo is None or verified_at.utcoffset() is None:
        raise CanaryAuditVerificationError("canary verification time MUST include a timezone")
    if not slot or slot != slot.strip() or len(slot) > 100:
        raise CanaryAuditVerificationError("canary slot MUST be bounded exact text")
    if isinstance(latency_budget_ms, bool) or latency_budget_ms < 1:
        raise CanaryAuditVerificationError("canary latency budget MUST be positive")

    correlation_id = f"canary:{slot}"
    event_id = str(uuid5(NAMESPACE_URL, f"fdai.canary://{slot}"))
    expected = {
        "event_id": event_id,
        "correlation_id": correlation_id,
        "idempotency_key": correlation_id,
        "actor": _CANARY_ACTOR,
        "action_kind": _CANARY_ACTION_KIND,
        "mode": "shadow",
        "tier": "canary",
        "decision": "no-op",
        "outcome": "success",
    }
    for field, value in expected.items():
        if entry.get(field) != value:
            raise CanaryAuditVerificationError(f"canary audit {field} does not match")

    latency_ms = entry.get("latency_ms")
    if isinstance(latency_ms, bool) or not isinstance(latency_ms, int) or latency_ms < 0:
        raise CanaryAuditVerificationError("canary audit latency_ms MUST be a non-negative integer")
    if latency_ms > latency_budget_ms:
        raise CanaryAuditVerificationError("canary audit exceeded the latency budget")

    recorded_at_raw = entry.get("recorded_at")
    if not isinstance(recorded_at_raw, str):
        raise CanaryAuditVerificationError("canary audit recorded_at MUST be a timestamp")
    try:
        recorded_at = datetime.fromisoformat(recorded_at_raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CanaryAuditVerificationError("canary audit recorded_at is invalid") from exc
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise CanaryAuditVerificationError("canary audit recorded_at MUST include a timezone")
    if recorded_at > verified_at:
        raise CanaryAuditVerificationError("canary audit recorded_at is from the future")

    return {
        "schema_version": "1.0.0",
        "evidence_kind": "control_loop_canary_consumed_audit",
        "source_identity": "core-audit-log",
        "event_id": event_id,
        "correlation_id": correlation_id,
        "recorded_at": recorded_at.astimezone(UTC).isoformat(),
        "verified_at": verified_at.astimezone(UTC).isoformat(),
        "latency_ms": latency_ms,
        "latency_budget_ms": latency_budget_ms,
        "within_budget": True,
        "execution_authority": False,
    }


def capture_canary_audit(
    *,
    config: DatabaseConfig,
    slot: str,
    latency_budget_ms: int,
    timeout_seconds: float,
    poll_interval_seconds: float,
    reader: Callable[..., tuple[dict[str, Any], ...]] = _read_canary_audits,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    """Read until one exact audit appears or the bounded deadline expires."""

    if not 0 < timeout_seconds <= 300:
        raise CanaryAuditVerificationError("canary audit timeout MUST be in (0, 300]")
    if not 0 < poll_interval_seconds <= 10:
        raise CanaryAuditVerificationError("canary audit poll interval MUST be in (0, 10]")
    correlation_id = f"canary:{slot}"
    deadline = monotonic() + timeout_seconds
    while True:
        rows = reader(config, correlation_id=correlation_id)
        if len(rows) > 1:
            raise CanaryAuditVerificationError("canary audit identity is ambiguous")
        if rows:
            return verify_canary_audit(
                rows[0],
                slot=slot,
                latency_budget_ms=latency_budget_ms,
                verified_at=clock(),
            )
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise CanaryAuditVerificationError("canary consumed audit was not observed in time")
        sleeper(min(poll_interval_seconds, remaining))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", required=True)
    parser.add_argument("--latency-budget-ms", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = capture_canary_audit(
            config=DatabaseConfig.from_env(),
            slot=args.slot,
            latency_budget_ms=args.latency_budget_ms,
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
        )
        args.output.write_text(
            json.dumps(receipt, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (CanaryAuditVerificationError, OSError, psycopg.Error) as exc:
        print(f"verify-canary-audit: {exc}", file=sys.stderr)
        return 2
    print(f"verify-canary-audit: consumed audit verified within {receipt['latency_ms']} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CanaryAuditVerificationError",
    "DatabaseConfig",
    "capture_canary_audit",
    "main",
    "verify_canary_audit",
]

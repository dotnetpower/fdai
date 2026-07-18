#!/usr/bin/env python3
"""Select expired allowlisted deployment-plan blobs for runner-side deletion."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_PLAN_BLOB = re.compile(
    r"^(?:dev|staging|prod)/plan-[1-9][0-9]*-[1-9][0-9]*/"
    r"(?:terraform\.plan|metadata\.json|preflight-evidence\.json|"
    r"apply-claim\.json|apply-receipt\.json)$"
)


def select_expired_blobs(
    rows: object,
    *,
    now: datetime,
    retention: timedelta,
    max_scan: int,
    max_delete: int,
) -> tuple[str, ...]:
    """Return sorted expired plan blob names or fail on incomplete/broad input."""
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("blob listing MUST be a JSON array of objects")
    if len(rows) >= max_scan:
        raise ValueError("blob listing reached max_scan and may be incomplete")
    cutoff = now.astimezone(UTC) - retention
    selected: set[str] = set()
    for row in rows:
        name = row.get("name")
        properties = row.get("properties")
        modified = properties.get("lastModified") if isinstance(properties, dict) else None
        if not isinstance(name, str) or _PLAN_BLOB.fullmatch(name) is None:
            continue
        timestamp = _timestamp(modified)
        if timestamp < cutoff:
            selected.add(name)
    if len(selected) > max_delete:
        raise ValueError("expired blob count exceeds max_delete")
    return tuple(sorted(selected))


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("allowlisted plan blob is missing lastModified")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("lastModified MUST include a timezone")
    return parsed.astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--retention-hours", type=int, default=24)
    parser.add_argument("--max-scan", type=int, default=1001)
    parser.add_argument("--max-delete", type=int, default=1000)
    args = parser.parse_args(argv)
    if args.retention_hours < 1 or args.max_scan < 1 or args.max_delete < 1:
        parser.error("retention and bounds MUST be positive")
    try:
        rows = json.loads(args.manifest.read_text(encoding="utf-8"))
        selected = select_expired_blobs(
            rows,
            now=datetime.now(UTC),
            retention=timedelta(hours=args.retention_hours),
            max_scan=args.max_scan,
            max_delete=args.max_delete,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"cleanup selection failed: {exc}", file=sys.stderr)
        return 1
    for name in selected:
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

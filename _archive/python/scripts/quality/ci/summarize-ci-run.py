#!/usr/bin/env python3
"""Summarize exported Actions evidence without polling or treating a failed run as a speedup."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def seconds(start: str, end: str) -> float:
    elapsed = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    if elapsed < 0:
        raise ValueError("negative job or step duration")
    return elapsed


def summarize(
    run: dict[str, Any],
    jobs_payload: dict[str, Any],
    *,
    environment_id: str | None,
    test_count: int | None,
) -> dict[str, Any]:
    jobs = jobs_payload["jobs"]
    if len(jobs) != jobs_payload["total_count"]:
        raise ValueError("job export is incomplete; export all pages before summarizing")
    if test_count is not None and test_count <= 0:
        raise ValueError("test count must be positive")
    rows = []
    for job in jobs:
        if job["status"] != "completed":
            raise ValueError("run contains unfinished jobs")
        if job["conclusion"] == "skipped":
            continue
        rows.append(
            {
                "name": job["name"],
                "conclusion": job["conclusion"],
                "labels": sorted(job["labels"]),
                "runtime_seconds": seconds(job["started_at"], job["completed_at"]),
                "scheduling_seconds": seconds(job["created_at"], job["started_at"]),
            }
        )
    if not rows or len({row["name"] for row in rows}) != len(rows):
        raise ValueError("job export is empty or contains duplicate job names")
    return {
        "schema_version": 1,
        "run_id": run["id"],
        "attempt": run["run_attempt"],
        "revision": run["head_sha"],
        "workflow_id": run["workflow_id"],
        "conclusion": run["conclusion"],
        "complete": run["status"] == "completed",
        "environment_id": environment_id,
        "test_count": test_count,
        "job_slot_seconds": sum(row["runtime_seconds"] for row in rows),
        "jobs": rows,
    }


def compare(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, float]:
    for receipt in (baseline, candidate):
        if (
            receipt.get("schema_version") != 1
            or receipt.get("complete") is not True
            or receipt.get("conclusion") != "success"
            or any(row["conclusion"] != "success" for row in receipt["jobs"])
        ):
            raise ValueError("performance comparison requires two complete successful runs")
        if not receipt.get("environment_id") or not receipt.get("test_count"):
            raise ValueError("comparison requires an explicit environment identity and test count")
    for field in ("revision", "workflow_id", "environment_id", "test_count"):
        if baseline[field] != candidate[field]:
            raise ValueError(f"comparison input differs: {field}")

    def signature(receipt: dict[str, Any]) -> dict[str, list[str]]:
        return {row["name"]: row["labels"] for row in receipt["jobs"]}

    if signature(baseline) != signature(candidate):
        raise ValueError("comparison job scope or runner labels differ")
    before = baseline["job_slot_seconds"]
    if before <= 0:
        raise ValueError("baseline has no measured runtime")
    return {"job_slot_seconds_change_percent": (candidate["job_slot_seconds"] / before - 1) * 100}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--environment-id")
    parser.add_argument("--test-count", type=int)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = summarize(
            json.loads(args.run.read_text(encoding="utf-8")),
            json.loads(args.jobs.read_text(encoding="utf-8")),
            environment_id=args.environment_id,
            test_count=args.test_count,
        )
        if args.compare:
            receipt["comparison"] = compare(
                json.loads(args.compare.read_text(encoding="utf-8")), receipt
            )
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"ci-evidence: invalid or incomparable evidence: {error}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

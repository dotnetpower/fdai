#!/usr/bin/env python3
"""Check no-hosted-runner cutover evidence without changing routing or reading credentials."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


def assess(
    workflow: dict[str, Any],
    runners: dict[str, Any],
    elastic_receipt: dict[str, Any] | None,
) -> dict[str, Any]:
    if len(runners["runners"]) != runners["total_count"]:
        raise ValueError("runner inventory is paginated or incomplete")
    hosted = []
    unavailable = []
    for name, job in workflow["jobs"].items():
        selection = job["runs-on"]
        labels = [selection] if isinstance(selection, str) else selection
        if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
            unavailable.append(name)
            continue
        if "self-hosted" not in labels:
            hosted.append(name)
            continue
        matching = [
            runner
            for runner in runners["runners"]
            if runner["status"] == "online"
            and set(labels).issubset({label["name"] for label in runner["labels"]})
        ]
        if not matching:
            unavailable.append(name)
    elastic_verified = (
        elastic_receipt is not None
        and elastic_receipt.get("complete") is True
        and elastic_receipt.get("conclusion") == "success"
        and bool(elastic_receipt.get("test_count"))
        and bool(elastic_receipt.get("environment_id"))
        and any(
            "fdai-ci-aca" in row["labels"] and row["conclusion"] == "success"
            for row in elastic_receipt.get("jobs", [])
        )
        and all(row["conclusion"] == "success" for row in elastic_receipt.get("jobs", []))
    )
    return {
        "ready": not hosted and not unavailable and elastic_verified,
        "hosted_jobs": sorted(hosted),
        "unavailable_self_hosted_jobs": sorted(unavailable),
        "elastic_success_evidence": elastic_verified,
        "credential_values_inspected": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path, default=Path(".github/workflows/ci.yml"))
    parser.add_argument("--runners", type=Path, required=True)
    parser.add_argument("--elastic-receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        result = assess(
            yaml.safe_load(args.workflow.read_text(encoding="utf-8")),
            json.loads(args.runners.read_text(encoding="utf-8")),
            json.loads(args.elastic_receipt.read_text(encoding="utf-8"))
            if args.elastic_receipt
            else None,
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"runner-cutover: incomplete evidence: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

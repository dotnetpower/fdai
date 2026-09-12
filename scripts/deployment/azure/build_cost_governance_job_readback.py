#!/usr/bin/env python3
"""Build sanitized image readback evidence for the Cost Governance Jobs."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_DIGEST_IMAGE = re.compile(r"^[^\s@]+@sha256:([0-9a-f]{64})$")
_MAX_BYTES = 64 * 1024
_JOB_CONTAINERS = {
    "analyzer": "cost-governance-analyzer",
    "collector": "cost-governance-collector",
}


def build_job_readback(
    *,
    expected_image: str,
    job_receipts: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Return canonical evidence only when both Jobs use the expected image digest."""
    expected_match = _DIGEST_IMAGE.fullmatch(expected_image)
    if expected_match is None:
        raise ValueError("expected Cost Governance image is not digest pinned")
    if set(job_receipts) != set(_JOB_CONTAINERS):
        raise ValueError("Cost Governance Job image receipts are incomplete")

    expected_digest = expected_match.group(1)
    jobs: dict[str, object] = {}
    for role, expected_container in _JOB_CONTAINERS.items():
        receipt = job_receipts[role]
        if set(receipt) != {"container", "image_digest"}:
            raise ValueError(f"Cost Governance {role} image receipt schema is invalid")
        if receipt.get("container") != expected_container:
            raise ValueError(f"Cost Governance {role} container binding is invalid")
        if receipt.get("image_digest") != expected_digest:
            raise ValueError(f"Cost Governance {role} image digest does not match")
        jobs[role] = {
            "container": expected_container,
            "image_digest": f"sha256:{expected_digest}",
        }
    return {
        "schema_version": "fdai.cost-governance-job-image-readback.v1",
        "image_digest": f"sha256:{expected_digest}",
        "jobs": jobs,
    }


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_BYTES:
        raise ValueError(f"{label} is unavailable or too large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain an object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector", type=Path, required=True)
    parser.add_argument("--analyzer", type=Path, required=True)
    parser.add_argument("--expected-image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        readback = build_job_readback(
            expected_image=args.expected_image,
            job_receipts={
                "collector": _load_json_object(args.collector, "collector image receipt"),
                "analyzer": _load_json_object(args.analyzer, "analyzer image receipt"),
            },
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    args.output.write_text(
        json.dumps(readback, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.chmod(args.output, 0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

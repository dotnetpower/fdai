#!/usr/bin/env python3
"""Verify that one deployed Container Apps Job uses the expected image."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_DIGEST_IMAGE = re.compile(r"^[^\s@]+@sha256:([0-9a-f]{64})$")
_MAX_BYTES = 2 * 1024 * 1024


class JobImageVerificationError(RuntimeError):
    """The observed job is unavailable, ambiguous, or bound to another image."""


def verify_job_image(path: Path, *, container_name: str, expected_image: str) -> dict[str, str]:
    """Return sanitized image evidence after exact deployed-job validation."""
    expected_match = _DIGEST_IMAGE.fullmatch(expected_image)
    if expected_match is None:
        raise JobImageVerificationError("expected image is not digest pinned")
    if not container_name.strip():
        raise JobImageVerificationError("container name is empty")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_BYTES:
        raise JobImageVerificationError("job evidence is unavailable or too large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JobImageVerificationError("job evidence is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise JobImageVerificationError("job evidence MUST be an object")
    properties = payload.get("properties")
    if not isinstance(properties, dict) or properties.get("provisioningState") != "Succeeded":
        raise JobImageVerificationError("job is not successfully provisioned")
    template = properties.get("template")
    containers = template.get("containers") if isinstance(template, dict) else None
    if not isinstance(containers, list):
        raise JobImageVerificationError("job container template is invalid")
    selected = [
        item for item in containers if isinstance(item, dict) and item.get("name") == container_name
    ]
    if len(selected) != 1:
        raise JobImageVerificationError("job container binding is missing or ambiguous")
    image = selected[0].get("image")
    if not isinstance(image, str) or image != expected_image:
        raise JobImageVerificationError("deployed job image does not match the expected image")
    return {
        "container": container_name,
        "image_digest": expected_match.group(1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--expected-image", required=True)
    args = parser.parse_args()
    try:
        result = verify_job_image(
            args.job,
            container_name=args.container,
            expected_image=args.expected_image,
        )
    except JobImageVerificationError as exc:
        print(f"job image verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

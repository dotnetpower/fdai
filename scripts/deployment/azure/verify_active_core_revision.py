#!/usr/bin/env python3
"""Verify one active healthy Core revision and project sanitized model bindings."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_DIGEST_IMAGE = re.compile(r"^ghcr\.io/[^\s]+@sha256:([0-9a-f]{64})$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_BYTES = 2 * 1024 * 1024


class ActiveCoreRevisionError(RuntimeError):
    """The observed Core revision is ambiguous, unhealthy, or unbound."""


def active_core_binding(path: Path, *, require_model_binding: bool) -> dict[str, str]:
    """Return sanitized active revision coordinates after strict validation."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_BYTES:
        raise ActiveCoreRevisionError("active Core revision evidence is unavailable or too large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActiveCoreRevisionError("active Core revision evidence is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ActiveCoreRevisionError("active Core revision evidence MUST be an object")
    name = _string(payload, "name", "active Core revision")
    properties = payload.get("properties")
    if not isinstance(properties, dict):
        raise ActiveCoreRevisionError("active Core revision properties are invalid")
    if (
        properties.get("active") is not True
        or properties.get("healthState") != "Healthy"
        or properties.get("provisioningState") != "Provisioned"
    ):
        raise ActiveCoreRevisionError("Core revision is not active, healthy, and provisioned")
    template = properties.get("template")
    containers = template.get("containers") if isinstance(template, dict) else None
    if (
        not isinstance(containers, list)
        or len(containers) != 1
        or not isinstance(containers[0], dict)
    ):
        raise ActiveCoreRevisionError("active Core revision must contain one primary container")
    container: dict[str, Any] = containers[0]
    image = _string(container, "image", "active Core container")
    match = _DIGEST_IMAGE.fullmatch(image)
    if match is None:
        raise ActiveCoreRevisionError("active Core image is not a digest-pinned GHCR image")
    environment = container.get("env")
    if not isinstance(environment, list):
        raise ActiveCoreRevisionError("active Core environment is invalid")
    bindings: dict[str, str] = {}
    for item in environment:
        if not isinstance(item, dict):
            raise ActiveCoreRevisionError("active Core environment entry is invalid")
        key = item.get("name")
        value = item.get("value")
        if isinstance(key, str) and isinstance(value, str) and key not in bindings:
            bindings[key] = value
    runtime_digest = bindings.get("LLM_RESOLVED_MODELS_SHA256", "")
    if require_model_binding and (
        bindings.get("LLM_MODE") != "azure"
        or bindings.get("LLM_RESOLVED_MODELS_PATH") != "/app/resolved-models.json"
        or _DIGEST.fullmatch(runtime_digest) is None
    ):
        raise ActiveCoreRevisionError("active Core revision has no exact model binding")
    return {
        "revision": name,
        "image": image,
        "image_digest": match.group(1),
        "runtime_model_digest": runtime_digest,
    }


def _string(value: dict[str, Any], key: str, label: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ActiveCoreRevisionError(f"{label} {key} is invalid")
    return item


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", type=Path, required=True)
    parser.add_argument("--require-model-binding", action="store_true")
    args = parser.parse_args()
    try:
        result = active_core_binding(
            args.revision, require_model_binding=args.require_model_binding
        )
    except ActiveCoreRevisionError as exc:
        print(f"active Core revision verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

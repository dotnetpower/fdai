#!/usr/bin/env python3
"""Apply the tracked artifact-only service distribution version to a build checkout."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SERVICE_IDS = (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
)
DISTRIBUTIONS = {
    "core-control-plane": "fdai-core-control-plane",
    "operator-service": "fdai-operator-service",
    "document-ingestion-api": "fdai-document-ingestion-api",
    "document-processing-worker": "fdai-document-processing-worker",
    "isolated-executor": "fdai-isolated-executor-service",
}
_VERSION = re.compile(r"0\.1\.[0-9]+")


class ImageBuildOverrideError(ValueError):
    """Report an invalid or ambiguous tracked image-build override."""


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ImageBuildOverrideError("service image build override must be an object")
    return value


def _replace_project_version(path: Path, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'(?m)^version = "0\.1\.[0-9]+"$',
        f'version = "{version}"',
        text,
        count=1,
    )
    if count != 1:
        raise ImageBuildOverrideError(f"cannot replace one project version: {path}")
    path.write_text(updated, encoding="utf-8")


def _replace_lock_version(path: Path, distribution: str, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf'(?m)(^name = "{re.escape(distribution)}"\nversion = ")0\.1\.[0-9]+("$)')
    updated, count = pattern.subn(rf"\g<1>{version}\g<2>", text, count=1)
    if count != 1:
        raise ImageBuildOverrideError(f"cannot replace one lock version: {distribution}")
    path.write_text(updated, encoding="utf-8")


def apply_override(repository_root: Path) -> str | None:
    """Apply an active closed override and return its version; inactive is a no-op."""
    payload = _load(repository_root / "config/service-image-build-override.json")
    if set(payload) != {
        "schema_version",
        "state",
        "distribution_version",
        "services",
        "purpose",
    }:
        raise ImageBuildOverrideError("service image build override fields are invalid")
    if payload["schema_version"] != 1 or payload["state"] not in {"active", "inactive"}:
        raise ImageBuildOverrideError("service image build override state is invalid")
    if payload["services"] != list(SERVICE_IDS):
        raise ImageBuildOverrideError("service image build override service order is invalid")
    if payload["purpose"] != "corrected-n-minus-one-transition-artifacts":
        raise ImageBuildOverrideError("service image build override purpose is invalid")
    version = payload["distribution_version"]
    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
        raise ImageBuildOverrideError("service image build override version is invalid")
    if payload["state"] == "inactive":
        return None
    lock_path = repository_root / "uv.lock"
    for service_id in SERVICE_IDS:
        _replace_project_version(
            repository_root / "services" / service_id / "pyproject.toml",
            version,
        )
        _replace_lock_version(lock_path, DISTRIBUTIONS[service_id], version)
    return version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        version = apply_override(args.repository_root.resolve())
    except (OSError, json.JSONDecodeError, ImageBuildOverrideError) as exc:
        parser.error(str(exc))
    print(f"service-image-build-override: {version or 'inactive'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

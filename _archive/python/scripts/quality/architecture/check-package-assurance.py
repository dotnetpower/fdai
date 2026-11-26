#!/usr/bin/env python3
"""Validate FDAI's minimal signed-package inventory."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = REPO_ROOT / "config/package-assurance.json"
_ID = re.compile(r"[a-z0-9][a-z0-9.-]*")
_TOP_LEVEL = {"schema_version", "signature", "packages"}
_SIGNATURE = {
    "algorithm": "ed25519",
    "format": "detached-sha256sums",
}
_PACKAGE_FIELDS = {"id", "path", "manifest"}


def _load_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("package assurance policy must be a JSON object")
    return value


def _repo_path(root: Path, raw: object, field: str, errors: list[str]) -> Path | None:
    if not isinstance(raw, str) or not raw:
        errors.append(f"{field} must be a non-empty repository-relative path")
        return None
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        errors.append(f"{field} must be a repository-relative path")
        return None
    path = root / relative
    if not path.exists():
        errors.append(f"{field} does not exist: {raw}")
        return None
    return path


def _validate_signature(payload: Mapping[str, Any], errors: list[str]) -> None:
    signature = payload.get("signature")
    if not isinstance(signature, Mapping) or dict(signature) != _SIGNATURE:
        errors.append("signature must select ed25519 with the detached-sha256sums format")


def _validate_packages(
    root: Path,
    payload: Mapping[str, Any],
    errors: list[str],
) -> None:
    packages = payload.get("packages")
    if not isinstance(packages, list) or not packages:
        errors.append("packages must be a non-empty list")
        return
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, item in enumerate(packages):
        field = f"packages[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{field} must be an object")
            continue
        unknown = sorted(set(item) - _PACKAGE_FIELDS)
        if unknown:
            errors.append(f"{field} contains unsupported fields: {', '.join(unknown)}")
        package_id = item.get("id")
        if not isinstance(package_id, str) or _ID.fullmatch(package_id) is None:
            errors.append(f"{field}.id must be a stable lowercase id")
        elif package_id in seen_ids:
            errors.append(f"{field}.id is duplicated: {package_id}")
        else:
            seen_ids.add(package_id)
        package_path = item.get("path")
        if not isinstance(package_path, str) or not package_path:
            errors.append(f"{field}.path must be non-empty")
        elif package_path in seen_paths:
            errors.append(f"{field}.path is duplicated: {package_path}")
        else:
            seen_paths.add(package_path)
            _repo_path(root, package_path, f"{field}.path", errors)
        manifest = _repo_path(root, item.get("manifest"), f"{field}.manifest", errors)
        if manifest is None:
            continue
        if manifest.name != "pyproject.toml":
            errors.append(f"{field}.manifest must name pyproject.toml")
            continue
        try:
            document = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            errors.append(f"{field}.manifest cannot be parsed: {exc}")
            continue
        project = document.get("project")
        name = project.get("name") if isinstance(project, Mapping) else None
        if name != package_id:
            errors.append(f"{field}.manifest project.name must equal {package_id}")


def validate_policy(root: Path, payload: Mapping[str, Any]) -> list[str]:
    """Return every deterministic policy error."""

    errors: list[str] = []
    unknown = sorted(set(payload) - _TOP_LEVEL)
    missing = sorted(_TOP_LEVEL - set(payload))
    if unknown:
        errors.append("policy contains unsupported fields: " + ", ".join(unknown))
    if missing:
        errors.append("policy is missing fields: " + ", ".join(missing))
    if payload.get("schema_version") != 3:
        errors.append("schema_version must be 3")
    _validate_signature(payload, errors)
    _validate_packages(root, payload, errors)
    return errors


def main() -> int:
    try:
        payload = _load_json(POLICY_PATH)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"package-assurance: ERROR: {exc}", file=sys.stderr)
        return 1
    errors = validate_policy(REPO_ROOT, payload)
    if errors:
        for error in errors:
            print(f"package-assurance: ERROR: {error}", file=sys.stderr)
        return 1
    print(f"package-assurance: OK ({len(payload['packages'])} signed package(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate FDAI's minimum package-boundary assurance policy."""

from __future__ import annotations

import ast
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
_IMPORT = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_KNOWN_CONTROLS = frozenset(
    {
        "compatibility",
        "declared-dependency-closure",
        "digest-pinned-container",
        "exact-digest",
        "freshness",
        "independent-effect-verification",
        "no-public-fallback",
        "provenance",
        "sbom",
        "signed-root",
        "versioned-contract",
    }
)
_BOUNDARY_MINIMUMS = {
    "published-contract": {"versioned-contract"},
    "distributed-artifact": {"exact-digest", "provenance"},
    "distributed-evidence": {"exact-digest", "freshness", "provenance"},
}
_PROFILE_MINIMUMS = {
    "connected": {"declared-dependency-closure", "exact-digest", "provenance"},
    "offline": {
        "declared-dependency-closure",
        "exact-digest",
        "no-public-fallback",
        "provenance",
        "signed-root",
    },
    "appliance": {
        "declared-dependency-closure",
        "digest-pinned-container",
        "exact-digest",
        "no-public-fallback",
        "provenance",
        "signed-root",
    },
}
_RUNTIME_INVARIANTS = {
    "package_operation_grants_authority": False,
    "availability_or_enablement_grants_authority": False,
    "state_change_success_requires_independent_verification": True,
}
_TOP_LEVEL = {
    "schema_version",
    "boundary_minimums",
    "runtime_invariants",
    "packages",
    "artifact_profiles",
}
_PACKAGE_FIELDS = {
    "id",
    "path",
    "manifest",
    "public_facade",
    "import_name",
    "boundary",
    "required_controls",
    "compatibility_manifest",
    "compatibility_contract",
}


def _load_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("package assurance policy MUST be a JSON object")
    return value


def _repo_path(root: Path, raw: object, field: str, errors: list[str]) -> Path | None:
    if not isinstance(raw, str) or not raw:
        errors.append(f"{field} MUST be a non-empty repository-relative path")
        return None
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        errors.append(f"{field} MUST be a repository-relative path")
        return None
    path = root / relative
    if not path.exists():
        errors.append(f"{field} does not exist: {raw}")
        return None
    return path


def _controls(raw: object, field: str, errors: list[str]) -> set[str]:
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        errors.append(f"{field} MUST be a string array")
        return set()
    controls = set(raw)
    if len(controls) != len(raw):
        errors.append(f"{field} MUST contain unique controls")
    unknown = sorted(controls - _KNOWN_CONTROLS)
    if unknown:
        errors.append(f"{field} contains unsupported controls: {', '.join(unknown)}")
    return controls


def _validate_boundary_minimums(
    payload: Mapping[str, Any],
    errors: list[str],
) -> dict[str, set[str]]:
    raw = payload.get("boundary_minimums")
    if not isinstance(raw, Mapping):
        errors.append("boundary_minimums MUST be an object")
        return {}
    missing = sorted(set(_BOUNDARY_MINIMUMS) - set(raw))
    if missing:
        errors.append("boundary_minimums is missing: " + ", ".join(missing))
    result: dict[str, set[str]] = {}
    for boundary, controls_raw in raw.items():
        if not isinstance(boundary, str) or _ID.fullmatch(boundary) is None:
            errors.append("boundary_minimums keys MUST be stable lowercase ids")
            continue
        controls = _controls(controls_raw, f"boundary_minimums.{boundary}", errors)
        result[boundary] = controls
        required = _BOUNDARY_MINIMUMS.get(boundary, set())
        if not required <= controls:
            errors.append(
                f"boundary_minimums.{boundary} is missing constitutional minimums: "
                + ", ".join(sorted(required - controls))
            )
    return result


def _validate_facade(path: Path, field: str, errors: list[str]) -> None:
    if path.name != "__init__.py":
        errors.append(f"{field} MUST name __init__.py")
        return
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        errors.append(f"{field} cannot be parsed: {exc}")
        return
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            return
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__all__"
        ):
            return
    errors.append(f"{field} MUST declare __all__")


def _validate_packages(
    root: Path,
    payload: Mapping[str, Any],
    boundaries: Mapping[str, set[str]],
    errors: list[str],
) -> None:
    packages = payload.get("packages")
    if not isinstance(packages, list) or not packages:
        errors.append("packages MUST be a non-empty list")
        return
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, item in enumerate(packages):
        field = f"packages[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{field} MUST be an object")
            continue
        unknown_fields = sorted(set(item) - _PACKAGE_FIELDS)
        if unknown_fields:
            errors.append(f"{field} contains unsupported fields: {', '.join(unknown_fields)}")
        package_id = item.get("id")
        if not isinstance(package_id, str) or _ID.fullmatch(package_id) is None:
            errors.append(f"{field}.id MUST be a stable lowercase id")
        elif package_id in seen_ids:
            errors.append(f"{field}.id is duplicated: {package_id}")
        else:
            seen_ids.add(package_id)
        package_path = item.get("path")
        if not isinstance(package_path, str) or not package_path:
            errors.append(f"{field}.path MUST be non-empty")
        elif package_path in seen_paths:
            errors.append(f"{field}.path is duplicated: {package_path}")
        else:
            seen_paths.add(package_path)
            _repo_path(root, package_path, f"{field}.path", errors)
        boundary = item.get("boundary")
        if not isinstance(boundary, str) or boundary not in boundaries:
            errors.append(f"{field}.boundary is unsupported: {boundary}")
            continue
        controls = _controls(item.get("required_controls"), f"{field}.required_controls", errors)
        missing = boundaries[boundary] - controls
        if missing:
            errors.append(
                f"{field}.required_controls is missing boundary minimums: "
                + ", ".join(sorted(missing))
            )
        manifest = item.get("manifest")
        if manifest is not None:
            manifest_path = _repo_path(root, manifest, f"{field}.manifest", errors)
            if manifest_path is not None:
                if manifest_path.name != "pyproject.toml":
                    errors.append(f"{field}.manifest MUST name pyproject.toml")
                else:
                    try:
                        project = tomllib.loads(manifest_path.read_text(encoding="utf-8")).get(
                            "project"
                        )
                    except (OSError, tomllib.TOMLDecodeError) as exc:
                        errors.append(f"{field}.manifest cannot be parsed: {exc}")
                    else:
                        name = project.get("name") if isinstance(project, Mapping) else None
                        if name != package_id:
                            errors.append(f"{field}.manifest project name differs from id")
        facade = item.get("public_facade")
        if facade is not None:
            facade_path = _repo_path(root, facade, f"{field}.public_facade", errors)
            if facade_path is not None:
                _validate_facade(facade_path, f"{field}.public_facade", errors)
        import_name = item.get("import_name")
        if import_name is not None and (
            not isinstance(import_name, str) or _IMPORT.fullmatch(import_name) is None
        ):
            errors.append(f"{field}.import_name is invalid")
        for name in ("compatibility_manifest", "compatibility_contract"):
            if item.get(name) is not None:
                _repo_path(root, item[name], f"{field}.{name}", errors)


def _validate_artifact_profiles(payload: Mapping[str, Any], errors: list[str]) -> None:
    profiles = payload.get("artifact_profiles")
    if not isinstance(profiles, Mapping):
        errors.append("artifact_profiles MUST be an object")
        return
    missing = sorted(set(_PROFILE_MINIMUMS) - set(profiles))
    if missing:
        errors.append("artifact_profiles is missing: " + ", ".join(missing))
    for name, raw in profiles.items():
        field = f"artifact_profiles.{name}"
        if not isinstance(name, str) or _ID.fullmatch(name) is None:
            errors.append("artifact profile names MUST be stable lowercase ids")
            continue
        if not isinstance(raw, Mapping):
            errors.append(f"{field} MUST be an object")
            continue
        required = _controls(raw.get("required_controls"), f"{field}.required_controls", errors)
        recommended = _controls(
            raw.get("recommended_controls", []),
            f"{field}.recommended_controls",
            errors,
        )
        minimum = _PROFILE_MINIMUMS.get(name, set())
        if not minimum <= required:
            errors.append(
                f"{field}.required_controls is missing profile minimums: "
                + ", ".join(sorted(minimum - required))
            )
        if required & recommended:
            errors.append(f"{field} MUST not repeat required controls as recommendations")


def _validate_runtime_invariants(payload: Mapping[str, Any], errors: list[str]) -> None:
    invariants = payload.get("runtime_invariants")
    if not isinstance(invariants, Mapping):
        errors.append("runtime_invariants MUST be an object")
        return
    for name, expected in _RUNTIME_INVARIANTS.items():
        if invariants.get(name) is not expected:
            errors.append(f"runtime_invariants.{name} MUST be {str(expected).lower()}")


def validate_policy(root: Path, payload: Mapping[str, Any]) -> list[str]:
    """Return every deterministic package assurance policy error."""

    errors: list[str] = []
    if set(payload) != _TOP_LEVEL:
        errors.append("package assurance policy top-level fields do not match schema v2")
    if payload.get("schema_version") != 2:
        errors.append("schema_version MUST be 2")
    boundaries = _validate_boundary_minimums(payload, errors)
    _validate_runtime_invariants(payload, errors)
    _validate_packages(root, payload, boundaries, errors)
    _validate_artifact_profiles(payload, errors)
    return errors


def main() -> int:
    try:
        payload = _load_json(POLICY_PATH)
        errors = validate_policy(REPO_ROOT, payload)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"package-assurance: ERROR: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"package-assurance: ERROR: {error}", file=sys.stderr)
        return 1
    print("package-assurance: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

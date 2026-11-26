#!/usr/bin/env python3
"""Keep frozen scenario-set versions immutable and admit new versions atomically."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath
from typing import Any

SCENARIO_ROOT = PurePosixPath("services/core-control-plane/tests/scenarios")
# Git pathspec globs relative to SCENARIO_ROOT; `*` also matches `/`, as in CI.
FROZEN_PATTERNS = (
    "v*/*.json",
    "enrichment/v*/*.json",
    "manifests/v*.json",
    "cross-objective/v*.json",
)


def _version_for_path(path: str) -> str | None:
    candidate = PurePosixPath(path)
    try:
        relative = candidate.relative_to(SCENARIO_ROOT)
    except ValueError:
        return None

    parts = relative.parts
    if len(parts) == 2 and parts[0] in {"manifests", "cross-objective"}:
        return parts[1].split("-", 1)[0].removesuffix(".json")
    if len(parts) >= 2 and parts[0] == "enrichment":
        return parts[1]
    if len(parts) >= 2 and parts[0].startswith("v"):
        return parts[0]
    return None


def is_frozen_artifact(path: str) -> bool:
    """Return whether a path belongs to a frozen scenario-set version."""
    candidate = PurePosixPath(path)
    try:
        relative = candidate.relative_to(SCENARIO_ROOT).as_posix()
    except ValueError:
        return False
    return any(fnmatch.fnmatchcase(relative, pattern) for pattern in FROZEN_PATTERNS)


def find_frozen_modifications(
    changed_paths: Iterable[str],
    added_paths: Iterable[str],
    manifest_on_base: Callable[[str], bool],
) -> list[str]:
    """Return frozen artifacts that a change modifies, deletes, or adds to a frozen version.

    `changed_paths` are modified, deleted, renamed, or type-changed paths. An added path
    violates the freeze only when its version's manifest already exists on the base.
    """
    violations = {path for path in changed_paths if is_frozen_artifact(path)}
    for path in added_paths:
        if not is_frozen_artifact(path):
            continue
        version = _version_for_path(path)
        if version is not None and manifest_on_base(version):
            violations.add(path)
    return sorted(violations)


def _duplicate_values(values: list[str]) -> set[str]:
    return {value for value in values if values.count(value) > 1}


def validate_new_version_inventory(
    added_paths: Iterable[str],
    corpus_paths: Iterable[str],
    load_json: Callable[[str], Any],
) -> list[str]:
    """Return errors for non-atomic or incomplete newly added scenario versions."""
    added = {path for path in added_paths if _version_for_path(path)}
    corpus = {path for path in corpus_paths if _version_for_path(path)}
    versions = sorted(
        {version for path in added if (version := _version_for_path(path)) is not None}
    )
    errors: list[str] = []

    for version in versions:
        version_paths = {path for path in corpus if _version_for_path(path) == version}
        manifest_path = str(SCENARIO_ROOT / "manifests" / f"{version}.json")
        if manifest_path not in added:
            errors.append(f"{version}: new corpus artifacts require an atomically added manifest")
            continue
        non_atomic = sorted(version_paths - added)
        if non_atomic:
            errors.append(
                f"{version}: version inventory includes paths not added atomically: {non_atomic}"
            )

        scenario_prefix = f"{SCENARIO_ROOT}/{version}/"
        enrichment_prefix = f"{SCENARIO_ROOT}/enrichment/{version}/"
        conflict_prefix = f"{SCENARIO_ROOT}/cross-objective/{version}-"
        scenario_paths = sorted(
            path
            for path in version_paths
            if path.startswith(scenario_prefix) and path.endswith(".json")
        )
        enrichment_paths = sorted(
            path
            for path in version_paths
            if path.startswith(enrichment_prefix) and path.endswith(".json")
        )
        conflict_paths = sorted(
            path
            for path in version_paths
            if path.startswith(conflict_prefix) and path.endswith(".json")
        )
        if not scenario_paths:
            errors.append(f"{version}: version inventory has no scenario files")
        if not enrichment_paths:
            errors.append(f"{version}: version inventory has no enrichment overlays")
        if not conflict_paths:
            errors.append(f"{version}: version inventory has no conflict files")
        try:
            manifest = load_json(manifest_path)
            scenarios = [load_json(path) for path in scenario_paths]
            enrichments = [load_json(path) for path in enrichment_paths]
            conflicts = [load_json(path) for path in conflict_paths]
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            errors.append(f"{version}: inventory JSON could not be loaded: {exc}")
            continue

        if manifest.get("scenario_set_version") != version:
            errors.append(f"{version}: manifest scenario_set_version does not match its filename")

        scenario_ids = [item.get("id") for item in scenarios]
        enrichment_ids = [item.get("scenario_id") for item in enrichments]
        conflict_ids = [item.get("id") for item in conflicts]
        packs = manifest.get("capability_packs", {})
        manifest_scenario_ids = [
            scenario_id for pack in packs.values() for scenario_id in pack.get("scenario_ids", [])
        ]
        manifest_conflict_ids = [
            conflict_id
            for pack in packs.values()
            for conflict_id in pack.get("conflict_spec_ids", [])
        ]

        inventories = {
            "scenario files": scenario_ids,
            "enrichment overlays": enrichment_ids,
            "manifest scenario": manifest_scenario_ids,
            "conflict files": conflict_ids,
            "manifest conflict": manifest_conflict_ids,
        }
        for label, values in inventories.items():
            if not all(isinstance(value, str) and value for value in values):
                errors.append(f"{version}: {label} inventory contains a missing or invalid id")
            duplicates = sorted(
                _duplicate_values([value for value in values if isinstance(value, str)])
            )
            if duplicates:
                errors.append(f"{version}: {label} inventory contains duplicate ids: {duplicates}")

        if set(scenario_ids) != set(enrichment_ids):
            errors.append(f"{version}: enrichment inventory does not exactly match scenario files")
        if set(scenario_ids) != set(manifest_scenario_ids):
            errors.append(
                f"{version}: manifest scenario inventory does not exactly match scenario files"
            )
        if set(conflict_ids) != set(manifest_conflict_ids):
            errors.append(
                f"{version}: manifest conflict inventory does not exactly match conflict files"
            )
        if any(item.get("scenario_set_version") != version for item in conflicts):
            errors.append(f"{version}: conflict payload version does not match its filename")

    return errors


def _git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _load_json(path: str) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{path}: duplicate key {key!r}")
            result[key] = value
        return result

    return json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=unique_object,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args()
    root = str(SCENARIO_ROOT)
    added_paths = _git_lines(
        "diff",
        "--name-only",
        "--diff-filter=A",
        f"{args.base_sha}...HEAD",
        "--",
        root,
    )
    changed_paths = _git_lines(
        "diff",
        "--name-only",
        "--diff-filter=MDRT",
        f"{args.base_sha}...HEAD",
        "--",
        root,
    )

    def manifest_on_base(version: str) -> bool:
        manifest = f"{root}/manifests/{version}.json"
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{args.base_sha}:{manifest}"],
            check=False,
            capture_output=True,
        )
        return result.returncode == 0

    modified = find_frozen_modifications(changed_paths, added_paths, manifest_on_base)
    if modified:
        print("Frozen scenario files modified or deleted:")
        for path in modified:
            print(f"  - {path}")
        print("Frozen versions are immutable - create a new version directory instead.")
        return 1
    corpus_paths = _git_lines("ls-tree", "-r", "--name-only", "HEAD", "--", root)
    errors = validate_new_version_inventory(added_paths, corpus_paths, _load_json)
    if errors:
        print("Frozen scenario-set atomicity check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Frozen scenario-set additions are atomic and inventory-complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

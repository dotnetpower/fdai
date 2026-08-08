#!/usr/bin/env python3
"""Resolve service-owned pytest paths for changed FDAI source files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

GROUPS = ("unit", "contract", "integration", "smoke")


def resolve_owned_tests(root: Path, changed_paths: list[Path]) -> list[Path]:
    """Return owned test paths only when every changed source has one service owner."""
    manifest_path = root / "tests" / "integration" / "service-suites.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    services = manifest.get("services")
    if manifest.get("schema_version") != 1 or not isinstance(services, list):
        raise ValueError("service test suite manifest is invalid")

    selected_services: list[dict[str, object]] = []
    for changed_path in changed_paths:
        relative = changed_path.resolve().relative_to(root.resolve())
        owners = [service for service in services if _owns_source(service, relative)]
        if len(owners) != 1:
            return []
        if owners[0] not in selected_services:
            selected_services.append(owners[0])

    selected: list[Path] = []
    for service in selected_services:
        groups = service.get("test_groups")
        if not isinstance(groups, dict) or set(groups) != set(GROUPS):
            raise ValueError("service test suite groups are invalid")
        for group in GROUPS:
            paths = groups[group]
            if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
                raise ValueError("service test suite paths are invalid")
            for path in paths:
                candidate = Path(path)
                if candidate not in selected:
                    selected.append(candidate)
    return selected


def _owns_source(service: object, relative: Path) -> bool:
    if not isinstance(service, dict):
        raise ValueError("service test suite entry is invalid")
    roots = service.get("source_roots")
    if not isinstance(roots, list) or not all(isinstance(root, str) for root in roots):
        raise ValueError("service source roots are invalid")
    return any(relative == Path(root) or relative.is_relative_to(Path(root)) for root in roots)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("paths", nargs="*", type=Path)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    changed = [path if path.is_absolute() else root / path for path in arguments.paths]
    try:
        selected = resolve_owned_tests(root, changed)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    for path in selected:
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

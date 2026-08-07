#!/usr/bin/env python3
"""Validate the independent-services manifest and non-growth baselines."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "config" / "independent-services.json"


def _load_manifest() -> dict[str, Any]:
    value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("independent-services manifest must be an object")
    return value


def _imports_prefix(path: Path, prefix: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(prefix):
            return True
        if isinstance(node, ast.Import) and any(
            alias.name.startswith(prefix) for alias in node.names
        ):
            return True
    return False


def _count_files_importing(root: Path, prefix: str, pattern: str = "*.py") -> int:
    return sum(1 for path in root.rglob(pattern) if _imports_prefix(path, prefix))


def _validate_graph(work_packages: list[dict[str, Any]]) -> None:
    by_id = {str(item["id"]): item for item in work_packages}
    if len(by_id) != len(work_packages):
        raise ValueError("work-package ids must be unique")
    remaining = set(by_id)
    resolved: set[str] = set()
    while remaining:
        ready = {
            item_id for item_id in remaining if set(by_id[item_id]["dependencies"]) <= resolved
        }
        if not ready:
            raise ValueError(f"cyclic or unknown work-package dependencies: {sorted(remaining)}")
        resolved.update(ready)
        remaining.difference_update(ready)


def validate() -> None:
    manifest = _load_manifest()
    services = manifest["services"]
    if manifest["target_service_count"] != 5 or len(services) != 5:
        raise ValueError("independent-services target must contain exactly five services")
    service_ids = [str(item["id"]) for item in services]
    if len(set(service_ids)) != len(service_ids):
        raise ValueError("service ids must be unique")
    for service in services:
        for key in (
            "current_source_roots",
            "target_package",
            "entrypoint",
            "target_image",
            "target_terraform_root",
            "target_migration_branch",
        ):
            if not service.get(key):
                raise ValueError(f"{service['id']} is missing {key}")
        for source_root in service["current_source_roots"]:
            if not (REPO_ROOT / source_root).exists():
                raise ValueError(f"missing current source root: {source_root}")

    _validate_graph(manifest["work_packages"])
    baseline = manifest["current_baseline"]
    measured = {
        "operator_files_importing_core": _count_files_importing(
            REPO_ROOT / "src/fdai/delivery/operator_api", "fdai.core"
        ),
        "ingestion_files_importing_core": _count_files_importing(
            REPO_ROOT / "src/fdai/delivery/ingestion_gateway", "fdai.core"
        ),
        "executor_files_importing_core": sum(
            1
            for path in (REPO_ROOT / "src/fdai/runtime").glob("isolated_executor*.py")
            if _imports_prefix(path, "fdai.core")
        ),
    }
    for key, value in measured.items():
        if value > int(baseline[key]):
            raise ValueError(f"{key} grew from {baseline[key]} to {value}")
    targets = manifest["independence_targets"]
    if targets["cross_service_implementation_imports"] != 0:
        raise ValueError("cross-service implementation import target must be zero")
    for key in (
        "service_python_distributions",
        "service_images",
        "service_terraform_roots",
        "service_migration_branches",
        "independent_upgrade_and_rollback_proofs",
    ):
        if targets[key] != 5:
            raise ValueError(f"{key} target must be five")
    print(
        "check-independent-services: OK "
        f"(services=5 operator_core={measured['operator_files_importing_core']} "
        f"ingestion_core={measured['ingestion_files_importing_core']} "
        f"executor_core={measured['executor_files_importing_core']})"
    )


def main() -> int:
    try:
        validate()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, SyntaxError) as exc:
        print(f"check-independent-services: ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

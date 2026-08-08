#!/usr/bin/env python3
"""Validate the independent-services manifest and non-growth baselines."""

from __future__ import annotations

import ast
import json
import tomllib
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


def _count_service_forbidden_imports() -> int:
    forbidden_by_service = {
        "core-control-plane": (
            "fdai.delivery.operator_api",
            "fdai.delivery.ingestion_gateway",
            "fdai_executor_service",
            "fdai_operator_service",
            "fdai_ingestion_api_service",
            "fdai_document_worker_service",
        ),
        "operator-service": ("fdai.",),
        "document-ingestion-api": ("fdai.", "fdai_document_worker_service"),
        "document-processing-worker": ("fdai.", "fdai_ingestion_api_service"),
        "isolated-executor": ("fdai.",),
    }
    count = 0
    for service_id, prefixes in forbidden_by_service.items():
        source = REPO_ROOT / "services" / service_id / "src"
        count += sum(
            1
            for path in set(source.rglob("*.py"))
            if any(_imports_prefix(path, prefix) for prefix in prefixes)
        )
    return count


def _distribution_scripts(target_package: Path) -> dict[str, str]:
    try:
        pyproject = tomllib.loads((target_package / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot load service distribution: {target_package}") from exc
    project = pyproject.get("project")
    scripts = project.get("scripts") if isinstance(project, dict) else None
    if not isinstance(scripts, dict) or not scripts:
        raise ValueError(f"service distribution has no project scripts: {target_package}")
    if not all(
        isinstance(name, str) and isinstance(target, str) for name, target in scripts.items()
    ):
        raise ValueError(f"service distribution scripts are malformed: {target_package}")
    return scripts


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
        target_package = REPO_ROOT / service["target_package"]
        if not (target_package / "pyproject.toml").is_file():
            raise ValueError(f"missing service distribution: {service['target_package']}")
        scripts = _distribution_scripts(target_package)
        if service["entrypoint"] not in scripts:
            raise ValueError(
                f"{service['id']} entrypoint is not a service-owned distribution script"
            )
        terraform_root = REPO_ROOT / service["target_terraform_root"]
        if not (terraform_root / "main.tf").is_file():
            raise ValueError(f"missing service Terraform root: {service['target_terraform_root']}")
        migration_branch = (
            REPO_ROOT / "service-migrations" / "branches" / service["target_migration_branch"]
        )
        if not (migration_branch / "versions").is_dir():
            raise ValueError(
                f"missing service migration branch: {service['target_migration_branch']}"
            )

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
    forbidden_imports = _count_service_forbidden_imports()
    if forbidden_imports > int(baseline["service_forbidden_implementation_import_files"]):
        raise ValueError(
            "service_forbidden_implementation_import_files grew from "
            f"{baseline['service_forbidden_implementation_import_files']} to {forbidden_imports}"
        )
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
    if baseline["service_python_distributions"] != 5:
        raise ValueError("all five service distributions must be present")
    print(
        "check-independent-services: OK "
        f"(services=5 operator_core={measured['operator_files_importing_core']} "
        f"ingestion_core={measured['ingestion_files_importing_core']} "
        f"executor_core={measured['executor_files_importing_core']} "
        f"service_forbidden={forbidden_imports})"
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

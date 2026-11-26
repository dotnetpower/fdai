#!/usr/bin/env python3
"""Validate W0, W1, and W2 Cost Governance package convergence."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
CORE_SOURCE = REPO_ROOT / "services/core-control-plane/src"
INVENTORY_PATH = REPO_ROOT / "config/cost-governance-package-inventory.json"
PACKAGE_ROOT = REPO_ROOT / "extensions/cost-governance"
PACKAGE_SOURCE = PACKAGE_ROOT / "src"
PROFILE_PATH = PACKAGE_SOURCE / "fdai_cost_governance/resources/semantic-profile.json"
MANIFEST_PATH = PACKAGE_SOURCE / "fdai_cost_governance/resources/manifest.json"
W0_CHECKER_PATH = (
    REPO_ROOT / "scripts/quality/architecture/check-cost-governance-package-inventory.py"
)
W1_CHECKER_PATH = (
    REPO_ROOT / "scripts/quality/architecture/check-cost-governance-semantic-profile.py"
)

for source_root in (
    PACKAGE_SOURCE,
    REPO_ROOT / "services/core-control-plane/src",
    REPO_ROOT / "packages/service-contracts/src",
):
    sys.path.insert(0, str(source_root))

import fdai_cost_governance as cost_governance  # noqa: E402


class PackageConvergenceError(ValueError):
    """Report deterministic W0-W2 identity or reference drift."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageConvergenceError(f"{path}: cannot load JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise PackageConvergenceError(f"{path}: root must be an object")
    return value


def _load_checker(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PackageConvergenceError(f"cannot load checker: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _forbidden_imports(source: str, filename: str) -> tuple[str, ...]:
    violations: list[str] = []
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names = (node.module or "",)
        else:
            continue
        if any(
            name == "fdai_cost_governance" or name.startswith("fdai_cost_governance.")
            for name in names
        ):
            violations.append(f"{filename}:{node.lineno}")
    return tuple(violations)


def _core_package_imports(core_source: Path = CORE_SOURCE) -> tuple[str, ...]:
    violations: list[str] = []
    for path in sorted(core_source.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        violations.extend(_forbidden_imports(path.read_text(encoding="utf-8"), relative))
    return tuple(violations)


def load_repository_snapshot() -> dict[str, Any]:
    """Load verified package resources and reduce them to mutation-testable data."""

    inventory = _load_json(INVENTORY_PATH)
    profile = _load_json(PROFILE_PATH)
    manifest = cost_governance.load_resource_manifest()
    resources = cost_governance.load_package_resources()
    resources_by_id = {resource.asset_id: resource for resource in resources}
    bundle = cost_governance.build_cost_governance_bundle(
        archive_sha256="0" * 64,
        source="convergence-check",
    )
    project = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    profile_resource = resources_by_id["semantic-profile:cost-governance"]
    historical_paths = {
        binding[field]
        for binding in inventory["cost_rule_bindings"]
        for field in ("rule_path", "policy_path", "remediation_path")
    }
    historical_paths.add("rule-catalog/workflows/cost-aware-remediation.yaml")
    return {
        "inventory": inventory,
        "profile": profile,
        "package_manifest": manifest,
        "package_resources": [
            {
                "id": resource.asset_id,
                "kind": resource.kind.value,
                "path": resource.path,
                "references": list(resource.references),
                "sha256": resource.sha256,
            }
            for resource in resources
        ],
        "package_distribution": project["name"],
        "package_namespace": cost_governance.__name__,
        "profile_resource_sha256": hashlib.sha256(profile_resource.content).hexdigest(),
        "bundle": {
            "extension_id": bundle.manifest.extension.extension_id,
            "package_version": bundle.manifest.extension.version,
            "vertical_id": bundle.manifest.vertical_id,
            "descriptor_vertical_id": bundle.descriptor.vertical_id,
            "ontology_release_digest": bundle.manifest.ontology_release_range,
            "semantic_profile_sha256": bundle.manifest.semantic_profile_sha256,
            "asset_manifest_sha256": bundle.manifest.asset_manifest_sha256,
        },
        "active_base_asset_paths": sorted(
            path for path in historical_paths if (REPO_ROOT / path).exists()
        ),
        "base_action_types_present": all(
            (REPO_ROOT / f"rule-catalog/action-types/{binding['action_type_id']}.yaml").is_file()
            for binding in inventory["cost_rule_bindings"]
        ),
        "base_ontology_present": (
            REPO_ROOT / "rule-catalog/vocabulary/object-types/CostObjective.yaml"
        ).is_file(),
        "core_imports": list(_core_package_imports()),
    }


def _as_mapping(value: object, label: str, errors: list[str]) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    errors.append(f"{label} must be an object")
    return {}


def _as_records(value: object, label: str, errors: list[str]) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        errors.append(f"{label} must be an array")
        return []
    records = [item for item in value if isinstance(item, Mapping)]
    if len(records) != len(value):
        errors.append(f"{label} entries must be objects")
    return records


def _package_path(binding: Mapping[str, Any], field: str) -> str | None:
    value = binding.get(field)
    if not isinstance(value, str):
        return None
    prefixes = {
        "rule_path": ("rule-catalog/catalog/", "rules/"),
        "policy_path": ("", ""),
        "remediation_path": ("rule-catalog/remediation/", "remediation/"),
    }
    source_prefix, package_prefix = prefixes[field]
    if not value.startswith(source_prefix):
        return None
    return package_prefix + value.removeprefix(source_prefix)


def _validate_rule_graphs(
    inventory: Mapping[str, Any],
    manifest_assets: list[Mapping[str, Any]],
    errors: list[str],
) -> None:
    bindings = _as_records(
        inventory.get("cost_rule_bindings"),
        "inventory.cost_rule_bindings",
        errors,
    )
    assets_by_id = {
        item.get("id"): item for item in manifest_assets if isinstance(item.get("id"), str)
    }
    inventory_rule_ids = {
        item.get("rule_id") for item in bindings if isinstance(item.get("rule_id"), str)
    }
    manifest_rule_ids = {
        asset_id.removeprefix("rule:") for asset_id in assets_by_id if asset_id.startswith("rule:")
    }
    if len(inventory_rule_ids) != 12 or inventory_rule_ids != manifest_rule_ids:
        errors.append(
            "stable cost rule id drift: "
            f"inventory={sorted(inventory_rule_ids)}, packaged={sorted(manifest_rule_ids)}"
        )

    for binding in bindings:
        rule_id = binding.get("rule_id")
        action_type_id = binding.get("action_type_id")
        if not isinstance(rule_id, str) or not isinstance(action_type_id, str):
            errors.append("cost rule binding identity is invalid")
            continue
        expected = {
            f"rule:{rule_id}": ("rule_path",),
            f"policy:{rule_id}": ("policy_path",),
            f"remediation:{rule_id}": ("remediation_path",),
        }
        for asset_id, (field,) in expected.items():
            asset = assets_by_id.get(asset_id)
            expected_path = _package_path(binding, field)
            if asset is None:
                errors.append(f"{rule_id}: missing packaged {asset_id}")
            elif asset.get("path") != expected_path:
                errors.append(f"{rule_id}: {field} does not converge with {asset_id}")
        rule = assets_by_id.get(f"rule:{rule_id}")
        expected_references = {
            f"action:{action_type_id}",
            f"policy:{rule_id}",
            f"remediation:{rule_id}",
        }
        references = set(rule.get("references", ())) if rule is not None else set()
        if references != expected_references:
            errors.append(f"{rule_id}: rule-policy-remediation-ActionType references drift")
        expected_action_path = f"rule-catalog/action-types/{action_type_id}.yaml"
        if binding.get("action_type_path") != expected_action_path:
            errors.append(f"{rule_id}: ActionType path does not match its stable id")
    kinds = {
        kind: sum(item.get("kind") == kind for item in manifest_assets)
        for kind in ("rule", "policy", "remediation", "workflow")
    }
    if kinds != {"rule": 12, "policy": 12, "remediation": 12, "workflow": 1}:
        errors.append(f"package asset ownership counts drift: {kinds}")
    workflow = assets_by_id.get("workflow:cost-aware-remediation")
    if workflow is None or set(workflow.get("references", ())) != {
        "action:remediate.right-size",
        "action:remediate.tag-add",
    }:
        errors.append("cost-aware-remediation workflow references drift")


def validate_convergence_data(snapshot: Mapping[str, Any]) -> list[str]:
    """Return deterministic W0-W2 convergence violations without granting authority."""

    errors: list[str] = []
    inventory = _as_mapping(snapshot.get("inventory"), "inventory", errors)
    profile = _as_mapping(snapshot.get("profile"), "profile", errors)
    manifest = _as_mapping(snapshot.get("package_manifest"), "package_manifest", errors)
    bundle = _as_mapping(snapshot.get("bundle"), "bundle", errors)
    package_identity = _as_mapping(
        inventory.get("package_identity"),
        "inventory.package_identity",
        errors,
    )
    cutover = _as_mapping(inventory.get("w6_cutover"), "inventory.w6_cutover", errors)

    converged_id = package_identity.get("vertical_id")
    identity_values = {
        converged_id,
        manifest.get("package_id"),
        bundle.get("extension_id"),
        bundle.get("vertical_id"),
        bundle.get("descriptor_vertical_id"),
    }
    if len(identity_values) != 1 or converged_id != "cost-governance":
        errors.append("vertical/package identity drift")
    if snapshot.get("package_distribution") != package_identity.get("distribution"):
        errors.append("package distribution identity drift")
    if snapshot.get("package_namespace") != package_identity.get("namespace"):
        errors.append("package namespace identity drift")
    package_versions = {
        manifest.get("package_version"),
        bundle.get("package_version"),
        cutover.get("package_version"),
    }
    if package_versions != {"0.1.1"}:
        values = sorted(str(item) for item in package_versions)
        errors.append(f"exact package version drift: {values}")

    if profile.get("ontology_release_digest") != bundle.get("ontology_release_digest"):
        errors.append("exact ontology release digest drift")
    if profile.get("canonical_sha256") != bundle.get("semantic_profile_sha256"):
        errors.append("semantic profile canonical digest drift")
    if bundle.get("asset_manifest_sha256") != _canonical_sha256(manifest):
        errors.append("packaged manifest digest drift")
    if cutover.get("package_manifest_sha256") != _canonical_sha256(manifest):
        errors.append("W6 ownership manifest digest drift")

    manifest_assets = _as_records(manifest.get("assets"), "package_manifest.assets", errors)
    package_resources = _as_records(
        snapshot.get("package_resources"),
        "package_resources",
        errors,
    )
    if manifest_assets != package_resources:
        errors.append("packaged resource declaration drift")
    semantic_assets = [
        item for item in manifest_assets if item.get("id") == "semantic-profile:cost-governance"
    ]
    if len(semantic_assets) != 1 or semantic_assets[0].get("sha256") != snapshot.get(
        "profile_resource_sha256"
    ):
        errors.append("semantic profile resource digest drift")

    if manifest.get("candidate_state") != "inert":
        errors.append("package candidate state must remain inert")
    if snapshot.get("active_base_asset_paths") != []:
        errors.append(
            f"base catalog retains package-owned assets: {snapshot.get('active_base_asset_paths')}"
        )
    if snapshot.get("base_action_types_present") is not True:
        errors.append("generic ActionTypes do not remain in base")
    if snapshot.get("base_ontology_present") is not True:
        errors.append("base ontology does not remain available")
    base_activation = _as_mapping(
        cutover.get("base_activation"), "inventory.w6_cutover.base_activation", errors
    )
    if cutover.get("active_owner") != "package-owned" or (
        base_activation.get("package_absent") != "no-package-assets"
        or base_activation.get("package_disabled") != "no-package-assets"
        or base_activation.get("generic_action_types") != "retained"
        or base_activation.get("base_ontology") != "retained"
    ):
        errors.append("W6 current ownership boundary drift")
    _validate_rule_graphs(inventory, manifest_assets, errors)

    core_imports = snapshot.get("core_imports")
    if not isinstance(core_imports, list) or core_imports:
        errors.append(f"Core imports fdai_cost_governance: {core_imports}")
    return errors


def validate_repository() -> dict[str, Any]:
    """Validate source contracts and return the converged W0-W2 identity."""

    snapshot = load_repository_snapshot()
    w0_checker = _load_checker(W0_CHECKER_PATH, "cost_governance_w0_checker")
    w1_checker = _load_checker(W1_CHECKER_PATH, "cost_governance_w1_checker")
    errors = [
        f"W0: {error}" for error in w0_checker.validate_payload(snapshot["inventory"], REPO_ROOT)
    ]
    try:
        w1_checker.validate_profile_data(snapshot["profile"])
    except w1_checker.SemanticProfileError as exc:
        errors.append(f"W1: {exc}")
    errors.extend(validate_convergence_data(snapshot))
    if errors:
        raise PackageConvergenceError("; ".join(errors))
    return {
        "vertical_id": snapshot["bundle"]["vertical_id"],
        "ontology_release_digest": snapshot["profile"]["ontology_release_digest"],
        "semantic_profile_sha256": snapshot["profile"]["canonical_sha256"],
        "cost_rules": 12,
        "package_assets": len(snapshot["package_resources"]),
    }


def main() -> int:
    """Run the convergence gate and print one stable summary."""

    try:
        result = validate_repository()
    except (PackageConvergenceError, KeyError, OSError, ValueError) as exc:
        print(f"cost-governance-package-convergence: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "cost-governance-package-convergence: PASS "
        f"vertical={result['vertical_id']} "
        f"release={result['ontology_release_digest']} "
        f"profile={result['semantic_profile_sha256']} "
        f"rules={result['cost_rules']} assets={result['package_assets']} "
        "candidate=inert core_imports=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

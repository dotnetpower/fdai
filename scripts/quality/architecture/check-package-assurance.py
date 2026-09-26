#!/usr/bin/env python3
"""Validate FDAI package assurance levels and repository package ownership."""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = REPO_ROOT / "config/package-assurance.json"
_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?P<extras>\[[A-Za-z0-9._,-]+\])?"
    r"(?P<specifier>[^;@]*)"
    r"(?:;\s*(?P<marker>.+))?$"
)
_SPECIFIER = re.compile(r"^(?P<operator>==|>=|<=|>|<)(?P<version>[0-9]+(?:\.[0-9]+)*)$")

EXPECTED_LEVELS: dict[str, dict[str, bool]] = {
    "workspace-internal": {
        "independent_manifest": False,
        "n_minus_one_compatibility": False,
        "published_schema_immutable": False,
        "signed_release": False,
        "linked_lifecycle_evidence": False,
        "per_capability_promotion": False,
        "independent_effect_verification": False,
    },
    "lockstep-shared": {
        "independent_manifest": True,
        "n_minus_one_compatibility": False,
        "published_schema_immutable": False,
        "signed_release": False,
        "linked_lifecycle_evidence": False,
        "per_capability_promotion": False,
        "independent_effect_verification": False,
    },
    "independent-contract": {
        "independent_manifest": True,
        "n_minus_one_compatibility": True,
        "published_schema_immutable": True,
        "signed_release": False,
        "linked_lifecycle_evidence": False,
        "per_capability_promotion": False,
        "independent_effect_verification": False,
    },
    "effect-bearing": {
        "independent_manifest": True,
        "n_minus_one_compatibility": False,
        "published_schema_immutable": False,
        "signed_release": True,
        "linked_lifecycle_evidence": True,
        "per_capability_promotion": True,
        "independent_effect_verification": True,
    },
    "knowledge-evidence": {
        "independent_manifest": True,
        "n_minus_one_compatibility": False,
        "published_schema_immutable": True,
        "signed_release": True,
        "linked_lifecycle_evidence": True,
        "per_capability_promotion": False,
        "independent_effect_verification": True,
    },
}
EXPECTED_PACKAGE_LEVELS = {
    "fdai-github-app-auth": "lockstep-shared",
    "fdai-runtime-diagnostics": "lockstep-shared",
    "fdai-service-contracts": "independent-contract",
    "fdai-deployment-cli": "effect-bearing",
    "fdai-code-assurance": "lockstep-shared",
    "fdai-cost-governance": "effect-bearing",
    "fdai-aks-commerce": "effect-bearing",
    "cloud-reference-knowledge": "knowledge-evidence",
}
REQUIRED_PROFILES = {
    "connected": {
        "complete_offline_kit_required": False,
        "signed_root_required": False,
        "required_controls": {"exact-digest", "compatibility", "sbom", "provenance"},
    },
    "offline": {
        "complete_offline_kit_required": True,
        "signed_root_required": True,
        "required_controls": {
            "exact-digest",
            "compatibility",
            "sbom",
            "provenance",
            "no-public-fallback",
        },
    },
    "appliance": {
        "complete_offline_kit_required": True,
        "signed_root_required": True,
        "required_controls": {
            "exact-digest",
            "compatibility",
            "sbom",
            "provenance",
            "no-public-fallback",
            "digest-pinned-container",
        },
    },
}
REQUIRED_TOP_LEVEL = {
    "schema_version",
    "assurance_levels",
    "packages",
    "workspace_dependencies",
    "root_test_mirrors",
    "artifact_profiles",
    "lifecycle_evidence",
    "review_envelope",
    "optional_readiness",
    "extension_facades",
}
COMPATIBILITY_SCOPES = frozenset(
    {
        "lockstep",
        "published-n-minus-one",
        "artifact-n-minus-one",
        "backward-compatible-artifact",
        "versioned-evidence",
    }
)


@dataclass(frozen=True, slots=True)
class ParsedRequirement:
    name: str
    extras: tuple[str, ...]
    specifier: str
    marker: str


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


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


def _toml(path: Path) -> Mapping[str, Any]:
    value = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} MUST contain a TOML object")
    return value


def _requirement(raw: object, field: str, errors: list[str]) -> ParsedRequirement | None:
    if not isinstance(raw, str):
        errors.append(f"{field} MUST be a dependency requirement string")
        return None
    match = _REQUIREMENT.fullmatch(raw.strip())
    if match is None:
        errors.append(f"{field} is invalid")
        return None
    extras_value = match.group("extras")
    extras = (
        tuple(sorted(part.strip() for part in extras_value[1:-1].split(",")))
        if extras_value
        else ()
    )
    return ParsedRequirement(
        name=match.group("name"),
        extras=extras,
        specifier="".join(match.group("specifier").split()),
        marker=(match.group("marker") or "").strip(),
    )


def _project_requirements(
    manifest: Path,
    errors: list[str],
    *,
    include_dependency_groups: bool = True,
) -> dict[str, ParsedRequirement]:
    payload = _toml(manifest)
    project = payload.get("project")
    if not isinstance(project, Mapping):
        errors.append(f"{manifest.relative_to(REPO_ROOT)} is missing [project]")
        return {}
    raw_values: list[object] = list(project.get("dependencies", ()))
    optional = project.get("optional-dependencies")
    if isinstance(optional, Mapping):
        for values in optional.values():
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                raw_values.extend(values)
    dependency_groups = payload.get("dependency-groups")
    if include_dependency_groups and isinstance(dependency_groups, Mapping):
        for values in dependency_groups.values():
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                raw_values.extend(value for value in values if isinstance(value, str))
    requirements: dict[str, ParsedRequirement] = {}
    for index, raw in enumerate(raw_values):
        parsed = _requirement(raw, f"{manifest}:dependency[{index}]", errors)
        if parsed is not None:
            requirements[_canonical_name(parsed.name)] = parsed
    return requirements


def _same_requirement(left: ParsedRequirement, right: ParsedRequirement) -> bool:
    return (
        _canonical_name(left.name) == _canonical_name(right.name)
        and left.extras == right.extras
        and left.specifier == right.specifier
        and left.marker == right.marker
    )


def _version(value: str) -> tuple[int, ...]:
    parts = [int(part) for part in value.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _specifier_parts(value: str) -> dict[str, tuple[int, ...]] | None:
    parts: dict[str, tuple[int, ...]] = {}
    for raw in value.split(","):
        match = _SPECIFIER.fullmatch(raw)
        if match is None or match.group("operator") in parts:
            return None
        parts[match.group("operator")] = _version(match.group("version"))
    return parts


def _is_stricter_test_requirement(
    test_requirement: ParsedRequirement,
    owner_requirement: ParsedRequirement,
) -> bool:
    if (
        _canonical_name(test_requirement.name) != _canonical_name(owner_requirement.name)
        or test_requirement.extras != owner_requirement.extras
        or test_requirement.marker != owner_requirement.marker
    ):
        return False
    test_parts = _specifier_parts(test_requirement.specifier)
    owner_parts = _specifier_parts(owner_requirement.specifier)
    if test_parts is None or owner_parts is None or set(test_parts) != set(owner_parts):
        return False
    for operator, owner_version in owner_parts.items():
        test_version = test_parts[operator]
        if operator in {">", ">="} and test_version < owner_version:
            return False
        if operator in {"<", "<="} and test_version > owner_version:
            return False
        if operator == "==" and test_version != owner_version:
            return False
    return True


def _manifest_inventory(
    root: Path, errors: list[str]
) -> dict[str, list[tuple[Path, ParsedRequirement]]]:
    inventory: dict[str, list[tuple[Path, ParsedRequirement]]] = defaultdict(list)
    patterns = (
        "services/*/pyproject.toml",
        "packages/*/pyproject.toml",
        "extensions/*/pyproject.toml",
    )
    for pattern in patterns:
        for manifest in sorted(root.glob(pattern)):
            for name, requirement in _project_requirements(
                manifest,
                errors,
                include_dependency_groups=False,
            ).items():
                inventory[name].append((manifest, requirement))
    return inventory


def _validate_levels(payload: Mapping[str, Any], errors: list[str]) -> None:
    levels = payload.get("assurance_levels")
    if not isinstance(levels, Mapping):
        errors.append("assurance_levels MUST be an object")
        return
    if set(levels) != set(EXPECTED_LEVELS):
        errors.append("assurance_levels MUST define the five canonical package levels")
        return
    for name, expected in EXPECTED_LEVELS.items():
        if levels.get(name) != expected:
            errors.append(
                f"assurance_levels.{name} does not match the constitutional package boundary"
            )


def _validate_packages(
    root: Path,
    payload: Mapping[str, Any],
    errors: list[str],
) -> None:
    packages = payload.get("packages")
    if not isinstance(packages, list) or not packages:
        errors.append("packages MUST be a non-empty list")
        return
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    optional_imports: set[str] = set()
    observed_levels: dict[str, object] = {}
    for index, item in enumerate(packages):
        field = f"packages[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{field} MUST be an object")
            continue
        package_id = item.get("id")
        package_path = item.get("path")
        level = item.get("assurance_level")
        if not isinstance(package_id, str) or not package_id:
            errors.append(f"{field}.id MUST be non-empty")
        elif package_id in seen_ids:
            errors.append(f"{field}.id is duplicated: {package_id}")
        else:
            seen_ids.add(package_id)
            observed_levels[package_id] = level
        if not isinstance(package_path, str) or not package_path:
            errors.append(f"{field}.path MUST be non-empty")
        elif package_path in seen_paths:
            errors.append(f"{field}.path is duplicated: {package_path}")
        else:
            seen_paths.add(package_path)
            _repo_path(root, package_path, f"{field}.path", errors)
        if level not in EXPECTED_LEVELS:
            errors.append(f"{field}.assurance_level is unsupported: {level}")
            continue
        manifest = item.get("manifest")
        if EXPECTED_LEVELS[str(level)]["independent_manifest"]:
            if manifest is None and level != "knowledge-evidence":
                errors.append(f"{field}.manifest is required for {level}")
            elif manifest is not None:
                manifest_path = _repo_path(root, manifest, f"{field}.manifest", errors)
                if manifest_path is not None and manifest_path.name != "pyproject.toml":
                    errors.append(f"{field}.manifest MUST name pyproject.toml")
        compatibility_manifest = item.get("compatibility_manifest")
        compatibility_scope = item.get("compatibility_scope")
        if compatibility_scope not in COMPATIBILITY_SCOPES:
            errors.append(f"{field}.compatibility_scope is unsupported")
        if level == "independent-contract":
            if compatibility_scope != "published-n-minus-one":
                errors.append(f"{field}.compatibility_scope MUST be published-n-minus-one")
            _repo_path(
                root,
                compatibility_manifest,
                f"{field}.compatibility_manifest",
                errors,
            )
        elif compatibility_manifest is not None:
            errors.append(
                f"{field}.compatibility_manifest is allowed only for independent-contract"
            )
        compatibility_contract = item.get("compatibility_contract")
        if compatibility_scope == "artifact-n-minus-one":
            _repo_path(
                root,
                compatibility_contract,
                f"{field}.compatibility_contract",
                errors,
            )
        elif compatibility_contract is not None:
            errors.append(
                f"{field}.compatibility_contract is allowed only for artifact-n-minus-one"
            )
        facade = item.get("public_facade")
        if facade is not None:
            facade_path = _repo_path(root, facade, f"{field}.public_facade", errors)
            if facade_path is not None and facade_path.name != "__init__.py":
                errors.append(f"{field}.public_facade MUST name __init__.py")
            elif facade_path is not None:
                try:
                    tree = ast.parse(facade_path.read_text(encoding="utf-8"))
                except (OSError, SyntaxError) as exc:
                    errors.append(f"{field}.public_facade cannot be parsed: {exc}")
                else:
                    if not any(
                        isinstance(node, (ast.Assign, ast.AnnAssign))
                        and (
                            any(
                                isinstance(target, ast.Name) and target.id == "__all__"
                                for target in node.targets
                            )
                            if isinstance(node, ast.Assign)
                            else isinstance(node.target, ast.Name) and node.target.id == "__all__"
                        )
                        for node in tree.body
                    ):
                        errors.append(f"{field}.public_facade MUST declare __all__")
        import_name = item.get("import_name")
        if isinstance(package_path, str) and package_path.startswith("extensions/"):
            if not isinstance(import_name, str) or not import_name:
                errors.append(f"{field}.import_name is required for an extension package")
            else:
                optional_imports.add(import_name)

    core_root = root / "services/core-control-plane/src/fdai/core"
    for source in sorted(core_root.rglob("*.py")):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            errors.append(f"{source.relative_to(root)} cannot be parsed: {exc}")
            continue
        for node in ast.walk(tree):
            imported: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                imported = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported = (node.module,)
            if any(
                name == optional or name.startswith(optional + ".")
                for name in imported
                for optional in optional_imports
            ):
                errors.append(f"{source.relative_to(root)} imports an optional extension package")
    if set(observed_levels) != set(EXPECTED_PACKAGE_LEVELS):
        errors.append("packages MUST contain the complete authoritative package inventory")
    for package_id, expected_level in EXPECTED_PACKAGE_LEVELS.items():
        observed_level = observed_levels.get(package_id)
        if observed_level is not None and observed_level != expected_level:
            errors.append(f"packages.{package_id} MUST retain assurance level {expected_level}")


def _validate_dependencies(
    root: Path,
    payload: Mapping[str, Any],
    errors: list[str],
) -> None:
    root_payload = _toml(root / "pyproject.toml")
    project = root_payload.get("project")
    optional = project.get("optional-dependencies") if isinstance(project, Mapping) else None
    dev = optional.get("dev") if isinstance(optional, Mapping) else None
    if not isinstance(dev, list):
        errors.append("root pyproject.toml MUST define project.optional-dependencies.dev")
        return
    root_requirements: dict[str, ParsedRequirement] = {}
    for index, raw in enumerate(dev):
        parsed = _requirement(raw, f"root dev dependency[{index}]", errors)
        if parsed is not None:
            root_requirements[_canonical_name(parsed.name)] = parsed

    owner_inventory = _manifest_inventory(root, errors)
    workspace_entries = payload.get("workspace_dependencies")
    mirror_entries = payload.get("root_test_mirrors")
    if not isinstance(workspace_entries, list) or not isinstance(mirror_entries, list):
        errors.append("workspace_dependencies and root_test_mirrors MUST be lists")
        return

    declared: set[str] = set()
    for category, entries in (
        ("workspace_dependencies", workspace_entries),
        ("root_test_mirrors", mirror_entries),
    ):
        for index, item in enumerate(entries):
            field = f"{category}[{index}]"
            if not isinstance(item, Mapping):
                errors.append(f"{field} MUST be an object")
                continue
            dependency = item.get("dependency")
            if not isinstance(dependency, str) or not dependency:
                errors.append(f"{field}.dependency MUST be non-empty")
                continue
            canonical = _canonical_name(dependency)
            if canonical in declared:
                errors.append(f"{field}.dependency is duplicated: {dependency}")
                continue
            declared.add(canonical)
            root_requirement = root_requirements.get(canonical)
            if root_requirement is None:
                errors.append(f"{field}.dependency is not present in the root dev extra")
                continue
            owner_path = _repo_path(
                root,
                item.get("owner_manifest"),
                f"{field}.owner_manifest",
                errors,
            )
            if owner_path is None:
                continue
            owner_requirement = _project_requirements(owner_path, errors).get(canonical)
            if category == "workspace_dependencies":
                owner_project = _toml(owner_path).get("project")
                owner_name = (
                    owner_project.get("name") if isinstance(owner_project, Mapping) else None
                )
                owner_version = (
                    owner_project.get("version") if isinstance(owner_project, Mapping) else None
                )
                if _canonical_name(str(owner_name)) != canonical:
                    errors.append(f"{field}.owner_manifest does not own {dependency}")
                elif root_requirement.specifier != f"=={owner_version}":
                    errors.append(f"{field}.dependency MUST pin the owner project version")
                continue
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"{field}.reason MUST explain the root test import")
            if owner_requirement is None:
                errors.append(f"{field}.owner_manifest does not declare {dependency}")
            elif not _same_requirement(root_requirement, owner_requirement) and not (
                item.get("allow_stricter_test_range") is True
                and _is_stricter_test_requirement(root_requirement, owner_requirement)
            ):
                errors.append(f"{field}.dependency drifted from its owning manifest")

    mirrored = {
        name
        for name in root_requirements
        if name in owner_inventory
        and name
        not in {
            _canonical_name(str(item.get("dependency")))
            for item in workspace_entries
            if isinstance(item, Mapping)
        }
    }
    undeclared = sorted(mirrored - declared)
    if undeclared:
        errors.append(
            "root dev dependencies mirror package-owned requirements without policy entries: "
            + ", ".join(undeclared)
        )


def _validate_artifact_profiles(payload: Mapping[str, Any], errors: list[str]) -> None:
    profiles = payload.get("artifact_profiles")
    if not isinstance(profiles, Mapping) or set(profiles) != set(REQUIRED_PROFILES):
        errors.append("artifact_profiles MUST define connected, offline, and appliance")
        return
    for name, expected in REQUIRED_PROFILES.items():
        profile = profiles.get(name)
        if not isinstance(profile, Mapping):
            errors.append(f"artifact_profiles.{name} MUST be an object")
            continue
        if profile.get("signed_root_required") is not expected["signed_root_required"]:
            errors.append(f"artifact_profiles.{name} has an invalid signed-root requirement")
        if (
            profile.get("complete_offline_kit_required")
            is not expected["complete_offline_kit_required"]
        ):
            errors.append(f"artifact_profiles.{name} has an invalid complete-kit requirement")
        controls = profile.get("required_controls")
        if not isinstance(controls, list) or set(controls) != expected["required_controls"]:
            errors.append(f"artifact_profiles.{name} has invalid required controls")


def _validate_relaxations(payload: Mapping[str, Any], errors: list[str]) -> None:
    lifecycle = payload.get("lifecycle_evidence")
    if not isinstance(lifecycle, Mapping) or lifecycle != {
        "composition": "linked-exact-artifact",
        "single_run_required": False,
        "required_transitions": [
            "install",
            "enable",
            "disable",
            "revoke",
            "reload",
            "restart",
        ],
        "link_fields": [
            "artifact_digest",
            "release_revision",
            "environment_id",
            "audit_correlation_id",
        ],
    }:
        errors.append("lifecycle_evidence MUST preserve the linked exact-artifact contract")

    review = payload.get("review_envelope")
    required_review = {
        "multi_target": True,
        "target_decisions_independent": True,
        "promotion_transactions_separate": True,
        "approval_authority": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    if review != required_review:
        errors.append("review_envelope MUST preserve independent authority-neutral decisions")

    readiness = payload.get("optional_readiness")
    required_readiness = {
        "disabled_unavailable_package_does_not_block_base": True,
        "enabled_missing_requirement_fails_closed": True,
        "unrelated_complete_paths_may_continue": True,
        "availability_does_not_enable": True,
        "enablement_does_not_raise_authority": True,
    }
    if readiness != required_readiness:
        errors.append("optional_readiness MUST remain capability-scoped and fail closed")

    facades = payload.get("extension_facades")
    required_facades = {
        "stable_authority_neutral_exports_allowed": True,
        "core_optional_package_imports_allowed": False,
        "composition_root_only_binding": True,
    }
    if facades != required_facades:
        errors.append("extension_facades MUST preserve Core isolation and composition ownership")


def validate_policy(root: Path, payload: Mapping[str, Any]) -> list[str]:
    """Return every deterministic package assurance policy error."""

    errors: list[str] = []
    if set(payload) != REQUIRED_TOP_LEVEL:
        errors.append("package assurance policy top-level fields do not match")
    if payload.get("schema_version") != 1:
        errors.append("schema_version MUST be 1")
    _validate_levels(payload, errors)
    _validate_packages(root, payload, errors)
    _validate_dependencies(root, payload, errors)
    _validate_artifact_profiles(payload, errors)
    _validate_relaxations(payload, errors)
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

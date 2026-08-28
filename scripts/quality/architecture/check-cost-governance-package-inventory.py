#!/usr/bin/env python3
"""Validate the Cost Governance W0 ownership and contract inventory."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
INVENTORY_PATH = Path("config/cost-governance-package-inventory.json")
ALLOWED_FUTURE_OWNERS = frozenset({"core-kernel", "package-owned", "deployment-owned", "retired"})
REQUIRED_AXES = (
    "available",
    "enabled",
    "access",
    "mode",
    "cost_disclosure",
)
REQUIRED_PRESETS = ("hidden", "aggregate", "masked", "detailed")
DISCLOSURE_DIMENSIONS = (
    "granularity",
    "identity_visibility",
    "amount_precision",
)
EXPECTED_PACKAGE_IDENTITY = {
    "distribution": "fdai-cost-governance",
    "namespace": "fdai_cost_governance",
    "workspace_path": "extensions/cost-governance",
    "vertical_id": "cost-governance",
    "image": "fdai-cost-governance",
}
EXPECTED_ASSET_INVENTORY_SHA256 = "697c658a6fa9cf05bf415e61572254410b0518c1fac4f1cedfc91b3c05174d5d"
PACKAGE_RESOURCES = REPO_ROOT / "extensions/cost-governance/src/fdai_cost_governance/resources"
EXPECTED_DESIGN_OWNERS = (
    "docs/roadmap/architecture/finops-package-architecture.md",
    "docs/roadmap/architecture/finops-autonomous-operations.md",
    "docs/roadmap/fork-and-sequencing/finops-package-delivery-plan.md",
)
EXPECTED_AXIS_AUTHORITIES = {
    "available": ("runtime-composition", "derived"),
    "enabled": ("vertical-package-activation-store", False),
    "access": ("operator-api-rbac", "deny"),
    "mode": ("promotion-registry", "shadow"),
    "cost_disclosure": ("deployment-ceiling-and-principal-grant-meet", "hidden"),
}
EXPECTED_DISCLOSURE = {
    "dimensions": {
        "granularity": ["none", "summary", "group", "resource"],
        "identity_visibility": ["none", "pseudonymous", "exact"],
        "amount_precision": ["none", "band", "rounded", "exact"],
    },
    "presets": {
        "hidden": {
            "granularity": "none",
            "identity_visibility": "none",
            "amount_precision": "none",
        },
        "aggregate": {
            "granularity": "group",
            "identity_visibility": "none",
            "amount_precision": "rounded",
        },
        "masked": {
            "granularity": "resource",
            "identity_visibility": "pseudonymous",
            "amount_precision": "band",
        },
        "detailed": {
            "granularity": "resource",
            "identity_visibility": "exact",
            "amount_precision": "exact",
        },
    },
    "effective_policy": "component-wise-meet",
}
REQUIRED_OUTCOMES = frozenset(
    {
        "allow",
        "hold",
        "deny",
        "no-op",
        "human-approval",
        "execute",
        "rollback",
        "unverified-effect",
    }
)
EXPECTED_OUTCOME_DRIVERS = {
    "allow": "finops-guard",
    "hold": "risk-table",
    "deny": "risk-table",
    "no-op": "thor-duplicate",
    "human-approval": "thor-dispatch",
    "execute": "thor-dispatch",
    "rollback": "thor-vidar",
    "unverified-effect": "response-outcome",
}
EXPECTED_CONTRACT_FREEZE = {
    "package_host": {
        "package_version": "0.1.x",
        "host_range": ">=0.1.303,<0.2.0",
        "ontology_schema": "1.0.0",
        "rollback_support": "n-1-package-version",
        "activation_default": "disabled",
    },
    "cost_models": {
        "njord_cost_estimate": "signed-advisory-delta-with-confidence",
        "shared_cost_estimator": "nonnegative-monthly-authority-input-or-abstain",
        "cost_effect_estimate": "separate-signed-expected-effect-contract",
        "overlap_policy": "no-field-substitution-or-implicit-authority",
    },
    "disclosure": {
        "enforced_at": ["operator-api", "export", "notification", "audit-projection"],
        "fail_closed": "hidden",
        "amounts_are_not_authority": True,
    },
}
EXPECTED_COMPATIBILITY = [
    {
        "kind": "python-import",
        "legacy": "fdai.core.verticals.cost_governance",
        "target": "fdai_cost_governance",
        "policy": "retain-facade-through-w6",
    },
    {
        "kind": "operator-api-route",
        "legacy": "/finops",
        "target": "/cost-governance/overview",
        "policy": "n-1-alias-after-versioned-contract",
    },
    {
        "kind": "catalog-identifiers",
        "legacy": "current-stable-identifiers",
        "target": "unchanged",
        "policy": "breaking-change-requires-versioned-contract",
    },
]
REQUIRED_ASSET_GROUPS = {
    "cost-rule-policy-remediation-graphs": "package-owned",
    "shared-cost-action-types": "core-kernel",
    "finops-scenarios": "package-owned",
    "operator-api-cost-surfaces": "core-kernel",
    "console-cost-surfaces": "core-kernel",
    "finops-deployment-surfaces": "deployment-owned",
    "w0-outcome-corpus": "package-owned",
}
REQUIRED_FUTURE_CONTRACTS = frozenset(
    {
        "vertical-package-manifest",
        "vertical-package-bundle",
        "vertical-package-activation-store",
        "cost-observation-provider",
        "azure-cost-observation-adapter",
        "cost-advisory-provider",
        "cost-effect-estimate",
        "cost-governance-operator-api-family",
        "cost-governance-console-workspace",
        "cost-governance-collection-job",
    }
)


def _load(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("inventory MUST be a JSON object")
    return value


def _repo_file(root: Path, value: object, field: str, errors: list[str]) -> Path | None:
    if (
        not isinstance(value, str)
        or not value
        or Path(value).is_absolute()
        or ".." in Path(value).parts
    ):
        errors.append(f"{field} must be a repository-relative file path")
        return None
    path = root / value
    if not path.is_file():
        errors.append(f"{field} references a missing file: {value}")
        return None
    return path


def _top_level_yaml_value(text: str, key: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", text)
    return None if match is None else match.group(1).strip()


def _indented_yaml_value(text: str, key: str) -> str | None:
    match = re.search(rf"(?m)^\s+{re.escape(key)}:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", text)
    return None if match is None else match.group(1).strip()


def _current_cost_rules(root: Path) -> dict[str, Path]:
    rules: dict[str, Path] = {}
    for path in sorted((root / "rule-catalog/catalog").glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        if _top_level_yaml_value(text, "category") != "cost":
            continue
        rule_id = _top_level_yaml_value(text, "id")
        if rule_id is None:
            continue
        rules[rule_id] = path
    return rules


def _historical_cutover_paths(payload: Mapping[str, Any]) -> set[str]:
    paths = {
        str(binding[field])
        for binding in payload.get("cost_rule_bindings", ())
        if isinstance(binding, Mapping)
        for field in ("rule_path", "policy_path", "remediation_path")
        if isinstance(binding.get(field), str)
    }
    paths.add("rule-catalog/workflows/cost-aware-remediation.yaml")
    return paths


def _cutover_enabled(payload: Mapping[str, Any]) -> bool:
    value = payload.get("w6_cutover")
    return isinstance(value, Mapping) and value.get("state") == "implemented"


def _package_asset_path(binding: Mapping[str, Any], field: str) -> Path:
    raw = binding.get(field)
    value = raw if isinstance(raw, str) else "__invalid__"
    if field == "rule_path":
        relative = "rules/" + value.removeprefix("rule-catalog/catalog/")
    elif field == "remediation_path":
        relative = value.removeprefix("rule-catalog/")
    else:
        relative = value
    return PACKAGE_RESOURCES / relative


def _validate_package_contract(payload: Mapping[str, Any], errors: list[str]) -> None:
    if payload.get("schema_version") != "1.0.0":
        errors.append("schema_version must be 1.0.0")
    if payload.get("tracking_issue") != 320:
        errors.append("tracking_issue must be 320")
    if tuple(payload.get("design_owners", ())) != EXPECTED_DESIGN_OWNERS:
        errors.append("design_owners must name the three FinOps design owners in dependency order")
    if payload.get("package_identity") != EXPECTED_PACKAGE_IDENTITY:
        errors.append("package_identity must match the accepted package architecture")

    axes = payload.get("axis_contract")
    if not isinstance(axes, Mapping) or tuple(axes) != REQUIRED_AXES:
        errors.append(f"axis_contract must define exactly {list(REQUIRED_AXES)}")
    else:
        for axis, record in axes.items():
            if not isinstance(record, Mapping):
                errors.append(f"axis_contract.{axis} must be an object")
                continue
            authority = record.get("authority")
            expected_authority, expected_initial = EXPECTED_AXIS_AUTHORITIES[axis]
            if authority != expected_authority:
                errors.append(f"axis_contract.{axis}.authority does not match the frozen authority")
            if record.get("initial") != expected_initial:
                errors.append(f"axis_contract.{axis}.initial does not match the safe default")
            grants = record.get("does_not_grant")
            expected = [other for other in REQUIRED_AXES if other != axis]
            valid_grants = (
                isinstance(grants, list)
                and len(grants) == len(set(grants))
                and set(grants) == set(expected)
            )
            if not valid_grants:
                errors.append(
                    f"axis_contract.{axis}.does_not_grant must name every other independent axis"
                )


def _validate_disclosure(payload: Mapping[str, Any], errors: list[str]) -> None:
    disclosure = payload.get("cost_disclosure")
    if not isinstance(disclosure, Mapping):
        errors.append("cost_disclosure must be an object")
        return
    if disclosure != EXPECTED_DISCLOSURE:
        errors.append("cost_disclosure must match the frozen disclosure contract")
    dimensions = disclosure.get("dimensions")
    if not isinstance(dimensions, Mapping) or tuple(dimensions) != DISCLOSURE_DIMENSIONS:
        errors.append(f"cost_disclosure.dimensions must define {list(DISCLOSURE_DIMENSIONS)}")
        return
    presets = disclosure.get("presets")
    if not isinstance(presets, Mapping) or tuple(presets) != REQUIRED_PRESETS:
        errors.append(f"cost_disclosure.presets must define {list(REQUIRED_PRESETS)}")
        return
    for preset, record in presets.items():
        if not isinstance(record, Mapping) or set(record) != set(DISCLOSURE_DIMENSIONS):
            errors.append(f"cost_disclosure.presets.{preset} must define every dimension")
            continue
        for dimension, value in record.items():
            allowed = dimensions.get(dimension)
            if not isinstance(allowed, list) or value not in allowed:
                errors.append(
                    f"cost_disclosure.presets.{preset}.{dimension} is outside its lattice"
                )
    if disclosure.get("effective_policy") != "component-wise-meet":
        errors.append("cost_disclosure.effective_policy must be component-wise-meet")


def _validate_assets(root: Path, payload: Mapping[str, Any], errors: list[str]) -> None:
    assets = payload.get("assets")
    if not isinstance(assets, list):
        errors.append("assets must be an array")
        return
    digest = hashlib.sha256(
        json.dumps(assets, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    recorded_digest = payload.get("asset_inventory_sha256")
    if recorded_digest != EXPECTED_ASSET_INVENTORY_SHA256 or digest != recorded_digest:
        errors.append("asset inventory digest drift: every current asset must retain one owner")
    ids: list[str] = []
    stable_ids: list[tuple[str, str]] = []
    owned_paths: list[str] = []
    assets_by_id: dict[str, Mapping[str, Any]] = {}
    historical_paths = _historical_cutover_paths(payload)
    for index, asset in enumerate(assets):
        prefix = f"assets[{index}]"
        if not isinstance(asset, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        asset_id = asset.get("id")
        if not isinstance(asset_id, str) or not asset_id:
            errors.append(f"{prefix}.id must be non-empty")
        else:
            ids.append(asset_id)
            assets_by_id[asset_id] = asset
        kind = asset.get("kind")
        if not isinstance(kind, str) or not kind:
            errors.append(f"{prefix}.kind must be non-empty")
        singular_path = asset.get("path")
        grouped_paths = asset.get("paths")
        if (singular_path is None) == (grouped_paths is None):
            errors.append(f"{prefix} must define exactly one of path or paths")
        values: list[object]
        if singular_path is not None:
            values = [singular_path]
        elif isinstance(grouped_paths, list) and grouped_paths:
            values = grouped_paths
        else:
            errors.append(f"{prefix}.paths must be a non-empty array")
            values = []
        for path_index, value in enumerate(values):
            field = (
                f"{prefix}.path" if singular_path is not None else f"{prefix}.paths[{path_index}]"
            )
            historical = (
                isinstance(value, str) and value in historical_paths and _cutover_enabled(payload)
            )
            if historical:
                owned_paths.append(value)
            elif _repo_file(root, value, field, errors) is not None and isinstance(value, str):
                owned_paths.append(value)
        if asset.get("future_owner") not in ALLOWED_FUTURE_OWNERS:
            errors.append(f"{prefix}.future_owner must be one allowed owner")
        if not isinstance(asset.get("current_owner"), str) or not asset.get("current_owner"):
            errors.append(f"{prefix}.current_owner must be non-empty")
        if not isinstance(asset.get("disposition"), str) or not asset.get("disposition"):
            errors.append(f"{prefix}.disposition must be non-empty")
        stable_id = asset.get("stable_identifier")
        if stable_id is not None and isinstance(kind, str):
            if not isinstance(stable_id, str) or not stable_id:
                errors.append(f"{prefix}.stable_identifier must be non-empty when present")
            else:
                stable_ids.append((kind, stable_id))
    if len(ids) != len(set(ids)):
        errors.append("asset ids must be unique")
    if len(stable_ids) != len(set(stable_ids)):
        errors.append("stable identifiers must be unique within each asset kind")
    duplicate_paths = sorted({path for path in owned_paths if owned_paths.count(path) > 1})
    if duplicate_paths:
        errors.append(f"duplicate asset ownership: {duplicate_paths}")
    for asset_id, expected_owner in REQUIRED_ASSET_GROUPS.items():
        record = assets_by_id.get(asset_id)
        if record is None:
            errors.append(f"missing required asset ownership group: {asset_id}")
        elif record.get("future_owner") != expected_owner:
            errors.append(f"{asset_id}.future_owner must be {expected_owner}")


def _owned_asset_paths(payload: Mapping[str, Any]) -> set[str]:
    paths: set[str] = set()
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return paths
    for asset in assets:
        if not isinstance(asset, Mapping):
            continue
        singular = asset.get("path")
        if isinstance(singular, str):
            paths.add(singular)
        grouped = asset.get("paths")
        if isinstance(grouped, list):
            paths.update(value for value in grouped if isinstance(value, str))
    return paths


def _validate_rule_bindings(root: Path, payload: Mapping[str, Any], errors: list[str]) -> None:
    bindings = payload.get("cost_rule_bindings")
    if not isinstance(bindings, list):
        errors.append("cost_rule_bindings must be an array")
        return
    current = _current_cost_rules(root)
    cutover = _cutover_enabled(payload)
    owned_paths = _owned_asset_paths(payload)
    inventoried: dict[str, Mapping[str, Any]] = {}
    for index, binding in enumerate(bindings):
        prefix = f"cost_rule_bindings[{index}]"
        if not isinstance(binding, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        rule_id = binding.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id:
            errors.append(f"{prefix}.rule_id must be non-empty")
            continue
        if rule_id in inventoried:
            errors.append(f"duplicate cost rule ownership: {rule_id}")
        inventoried[rule_id] = binding
        if cutover:
            rule_path = _package_asset_path(binding, "rule_path")
            policy_path = _package_asset_path(binding, "policy_path")
            remediation_path = _package_asset_path(binding, "remediation_path")
            for field, path in (
                ("rule_path", rule_path),
                ("policy_path", policy_path),
                ("remediation_path", remediation_path),
            ):
                if not path.is_file():
                    errors.append(f"{prefix}.{field} references a missing file")
        else:
            rule_path = _repo_file(root, binding.get("rule_path"), f"{prefix}.rule_path", errors)
            policy_path = _repo_file(
                root, binding.get("policy_path"), f"{prefix}.policy_path", errors
            )
            remediation_path = _repo_file(
                root, binding.get("remediation_path"), f"{prefix}.remediation_path", errors
            )
        action_path = _repo_file(
            root, binding.get("action_type_path"), f"{prefix}.action_type_path", errors
        )
        for field in ("rule_path", "policy_path", "remediation_path", "action_type_path"):
            reference = binding.get(field)
            if isinstance(reference, str) and reference not in owned_paths:
                errors.append(f"{prefix}.{field} is not assigned to exactly one future owner")
        if rule_path is None or not rule_path.is_file():
            continue
        text = rule_path.read_text(encoding="utf-8")
        if _top_level_yaml_value(text, "id") != rule_id:
            errors.append(f"{prefix}.rule_id does not match {binding.get('rule_path')}")
        current_path = current.get(rule_id)
        if not cutover and current_path is not None and rule_path != current_path:
            errors.append(f"{prefix}.rule_path does not name the current catalog rule")
        expected_policy = _indented_yaml_value(text, "reference")
        expected_remediation = _indented_yaml_value(text, "template_ref")
        expected_action = _top_level_yaml_value(text, "remediates")
        if cutover:
            policy_relative = policy_path.relative_to(PACKAGE_RESOURCES).as_posix()
            remediation_relative = remediation_path.relative_to(PACKAGE_RESOURCES).as_posix()
        else:
            policy_relative = (
                None if policy_path is None else policy_path.relative_to(root).as_posix()
            )
            remediation_relative = (
                None if remediation_path is None else remediation_path.relative_to(root).as_posix()
            )
        if expected_policy != policy_relative:
            errors.append(f"{prefix}.policy_path does not match the rule reference")
        if (
            expected_remediation is None
            or (expected_remediation if cutover else f"rule-catalog/{expected_remediation}")
            != remediation_relative
        ):
            errors.append(f"{prefix}.remediation_path does not match the rule template")
        if binding.get("action_type_id") != expected_action:
            errors.append(f"{prefix}.action_type_id does not match the rule")
        expected_action_path = (
            None if expected_action is None else f"rule-catalog/action-types/{expected_action}.yaml"
        )
        if binding.get("action_type_path") != expected_action_path:
            errors.append(f"{prefix}.action_type_path does not match the referenced action id")
        if action_path is not None:
            action_text = action_path.read_text(encoding="utf-8")
            if _top_level_yaml_value(action_text, "name") != expected_action:
                errors.append(f"{prefix}.action_type_path does not define the referenced action")
            if _top_level_yaml_value(action_text, "default_mode") != "shadow":
                errors.append(f"{prefix}.action_type_path must remain shadow-first")
    if cutover and len(inventoried) != 12:
        errors.append("cost rule inventory drift: historical W0 bindings must contain 12 ids")
    if cutover and current:
        errors.append(f"base catalog still activates cost rules: {sorted(current)}")
    if not cutover and set(inventoried) != set(current):
        errors.append(
            "cost rule inventory drift: "
            f"missing={sorted(set(current) - set(inventoried))}, "
            f"unexpected={sorted(set(inventoried) - set(current))}"
        )


def _validate_w6_cutover(root: Path, payload: Mapping[str, Any], errors: list[str]) -> None:
    cutover = payload.get("w6_cutover")
    if not isinstance(cutover, Mapping):
        errors.append("w6_cutover must be an object")
        return
    if (
        cutover.get("tracking_issue") != 326
        or cutover.get("state") != "implemented"
        or cutover.get("active_owner") != "package-owned"
        or cutover.get("package_version") != "0.1.1"
    ):
        errors.append("w6_cutover identity or ownership is invalid")
    manifest = _repo_file(
        root,
        cutover.get("package_manifest_path"),
        "w6_cutover.package_manifest_path",
        errors,
    )
    if manifest is not None:
        value = _load(manifest)
        digest = hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if digest != cutover.get("package_manifest_sha256"):
            errors.append("w6_cutover package manifest digest drift")
        counts = {
            "rules": sum(item.get("kind") == "rule" for item in value["assets"]),
            "policies": sum(item.get("kind") == "policy" for item in value["assets"]),
            "remediations": sum(item.get("kind") == "remediation" for item in value["assets"]),
            "workflows": sum(item.get("kind") == "workflow" for item in value["assets"]),
        }
        if counts != cutover.get("active_asset_counts"):
            errors.append("w6_cutover active package asset counts drift")
    parity = cutover.get("parity_corpus")
    if not isinstance(parity, Mapping):
        errors.append("w6_cutover parity_corpus must be an object")
    else:
        path = _repo_file(root, parity.get("path"), "w6_cutover.parity_corpus.path", errors)
        if path is not None and hashlib.sha256(path.read_bytes()).hexdigest() != parity.get(
            "sha256"
        ):
            errors.append("w6_cutover parity corpus digest drift")
        if (
            parity.get("difference_mechanism_version") != "1.0.0"
            or parity.get("publication_policy") != "dual-read-single-publish"
        ):
            errors.append("w6_cutover parity policy drift")
    for historical in _historical_cutover_paths(payload):
        if (root / historical).exists():
            errors.append(f"package-owned asset remains active in base catalog: {historical}")
    for action_type in (
        "remediate.remove-orphan-resource",
        "remediate.right-size",
        "remediate.set-retention-policy",
    ):
        if not (root / f"rule-catalog/action-types/{action_type}.yaml").is_file():
            errors.append(f"generic ActionType was removed during cutover: {action_type}")
    if not (root / "rule-catalog/vocabulary/object-types/CostObjective.yaml").is_file():
        errors.append("base CostObjective ontology was removed during cutover")


def _validate_corpus(root: Path, payload: Mapping[str, Any], errors: list[str]) -> None:
    corpus = payload.get("baseline_corpus")
    if not isinstance(corpus, Mapping):
        errors.append("baseline_corpus must be an object")
        return
    cases = corpus.get("cases")
    if not isinstance(cases, list):
        errors.append("baseline_corpus.cases must be an array")
        return
    required = corpus.get("required_outcomes")
    if (
        corpus.get("state") != "frozen"
        or not isinstance(required, list)
        or len(required) != len(set(required))
        or set(required) != REQUIRED_OUTCOMES
    ):
        errors.append("outcome corpus is incomplete or not frozen")
    if "missing_outcomes" in corpus:
        errors.append("a frozen baseline corpus must not list missing outcomes")
    case_ids: list[str] = []
    outcome_cases: dict[str, Mapping[str, Any]] = {}
    owned_paths = _owned_asset_paths(payload)
    for index, case in enumerate(cases):
        prefix = f"baseline_corpus.cases[{index}]"
        if not isinstance(case, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        case_id = case.get("id")
        if isinstance(case_id, str) and case_id:
            case_ids.append(case_id)
        else:
            errors.append(f"{prefix}.id must be non-empty")
        path = _repo_file(root, case.get("path"), f"{prefix}.path", errors)
        if path is not None:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if case.get("sha256") != digest:
                errors.append(f"{prefix}.sha256 does not match the scenario content")
            relative_path = path.relative_to(root).as_posix()
            if relative_path not in owned_paths:
                errors.append(f"{prefix}.path is not assigned to exactly one future owner")
        coverage = case.get("coverage")
        if not isinstance(coverage, list) or not coverage or len(coverage) != len(set(coverage)):
            errors.append(f"{prefix}.coverage must be a non-empty array")
        outcome = case.get("outcome")
        if outcome is None:
            continue
        if not isinstance(outcome, str) or outcome not in REQUIRED_OUTCOMES:
            errors.append(f"{prefix}.outcome is not a required frozen outcome")
            continue
        if outcome in outcome_cases:
            errors.append(f"duplicate outcome corpus ownership: {outcome}")
        outcome_cases[outcome] = case
        if case.get("driver") != EXPECTED_OUTCOME_DRIVERS[outcome]:
            errors.append(f"{prefix}.driver does not match the frozen executable harness")
        if (
            not isinstance(coverage, list)
            or "executable-replay" not in coverage
            or outcome not in coverage
        ):
            errors.append(f"{prefix}.coverage must bind executable-replay to {outcome}")
        if path is not None:
            try:
                fixture = _load(path)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                errors.append(f"{prefix}.path is not a valid fixture object: {exc}")
            else:
                for field in ("id", "outcome", "driver"):
                    if fixture.get(field) != case.get(field):
                        errors.append(f"{prefix}.{field} does not match the executable fixture")
    if len(case_ids) != len(set(case_ids)):
        errors.append("baseline corpus case ids must be unique")
    if set(outcome_cases) != REQUIRED_OUTCOMES:
        errors.append(
            "outcome corpus is incomplete: "
            f"missing={sorted(REQUIRED_OUTCOMES - set(outcome_cases))}, "
            f"unexpected={sorted(set(outcome_cases) - REQUIRED_OUTCOMES)}"
        )


def _validate_frozen_contracts(payload: Mapping[str, Any], errors: list[str]) -> None:
    if payload.get("compatibility") != EXPECTED_COMPATIBILITY:
        errors.append("compatibility must match the frozen W0 migration policy")
    if payload.get("contract_freeze") != EXPECTED_CONTRACT_FREEZE:
        errors.append("contract_freeze must preserve package, model, and disclosure decisions")


def _validate_future_contracts(payload: Mapping[str, Any], errors: list[str]) -> None:
    contracts = payload.get("future_contracts")
    if not isinstance(contracts, list):
        errors.append("future_contracts must be an array")
        return
    ids: list[str] = []
    for index, contract in enumerate(contracts):
        prefix = f"future_contracts[{index}]"
        if not isinstance(contract, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        contract_id = contract.get("id")
        if not isinstance(contract_id, str) or not contract_id:
            errors.append(f"{prefix}.id must be non-empty")
        else:
            ids.append(contract_id)
        if contract.get("future_owner") not in ALLOWED_FUTURE_OWNERS:
            errors.append(f"{prefix}.future_owner must be one allowed owner")
        if contract.get("contract_version") != "1.0.0":
            errors.append(f"{prefix}.contract_version must be 1.0.0")
        if contract.get("definition_state") != "frozen":
            errors.append(f"{prefix}.definition_state must be frozen")
        if contract.get("implementation_state") != "not-started":
            errors.append(f"{prefix}.implementation_state must remain not-started")
        for field in ("required_fields", "invariants"):
            values = contract.get(field)
            if not isinstance(values, list) or not values or len(values) != len(set(values)):
                errors.append(f"{prefix}.{field} must be a non-empty unique array")
    if len(ids) != len(set(ids)):
        errors.append("future contract ids must be unique")
    if set(ids) != REQUIRED_FUTURE_CONTRACTS:
        errors.append("future contract definitions must cover the complete frozen W0 set")


def validate_payload(payload: Mapping[str, Any], root: Path = REPO_ROOT) -> list[str]:
    """Return deterministic inventory violations without mutating repository state."""

    errors: list[str] = []
    _validate_package_contract(payload, errors)
    for owner in EXPECTED_DESIGN_OWNERS:
        _repo_file(root, owner, "design_owner", errors)
    _validate_disclosure(payload, errors)
    _validate_assets(root, payload, errors)
    _validate_rule_bindings(root, payload, errors)
    _validate_w6_cutover(root, payload, errors)
    _validate_corpus(root, payload, errors)
    _validate_frozen_contracts(payload, errors)
    _validate_future_contracts(payload, errors)
    return errors


def validate(root: Path = REPO_ROOT, inventory_path: Path = INVENTORY_PATH) -> list[str]:
    """Load and validate one repository inventory."""

    path = root / inventory_path
    if not path.is_file():
        return [f"missing inventory: {inventory_path.as_posix()}"]
    try:
        payload = _load(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"invalid inventory: {exc}"]
    return validate_payload(payload, root)


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"cost-governance-package-inventory: FAIL: {error}", file=sys.stderr)
        return 1
    print("cost-governance-package-inventory: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

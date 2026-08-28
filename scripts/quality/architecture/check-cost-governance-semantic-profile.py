#!/usr/bin/env python3
"""Validate the exact-release Cost Governance semantic profile and F1-F8 corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "services/core-control-plane/src"))
sys.path.insert(0, str(REPO_ROOT / "packages/service-contracts/src"))

from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog  # noqa: E402
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry  # noqa: E402

PROFILE_PATH = (
    REPO_ROOT
    / "extensions/cost-governance/src/fdai_cost_governance/resources/semantic-profile.json"
)
FIXTURE_ROOT = REPO_ROOT / "tests/integration/fixtures/cost_governance_f1_f8"
CATALOG_ROOT = REPO_ROOT / "rule-catalog"

EXPECTED_OBJECTS = {
    "ActionOption",
    "ActionRun",
    "ArchitectureConstraint",
    "Budget",
    "BusinessService",
    "CapacityForecast",
    "ChangeWindow",
    "CostAnomaly",
    "CostObjective",
    "CostObservation",
    "DecisionCase",
    "Environment",
    "ExpectedEffect",
    "ObservedOutcome",
    "Ownership",
    "RecoveryObjective",
    "Resource",
    "ServiceObjective",
    "SizingRecommendation",
    "Workload",
}
EXPECTED_LINKS = {
    "budget_implements_cost_objective",
    "capacity_forecast_targets_resource",
    "considers",
    "cost_anomaly_derived_from",
    "cost_observation_targets_resource",
    "executed_as",
    "expects",
    "implemented_by",
    "resulted_in",
    "service_has_architecture_constraint",
    "service_has_budget",
    "service_has_cost_objective",
    "service_has_recovery_objective",
    "service_has_service_objective",
    "service_owned_by",
    "sizing_recommendation_based_on",
    "sizing_recommendation_targets_resource",
    "workload_owned_by",
    "workload_runs_on",
}
EXPECTED_ACTIONS = {"remediate.remove-orphan-resource", "remediate.right-size"}
EXPECTED_OBJECT_SETS = {
    "cost-governance.budget",
    "cost-governance.cleanup",
    "cost-governance.cost-anomaly",
    "cost-governance.right-sizing",
    "cost-governance.settlement",
}
EXPECTED_EVIDENCE_FUNCTIONS = {
    "cost-governance.evidence.budget",
    "cost-governance.evidence.cleanup",
    "cost-governance.evidence.cost-anomaly",
    "cost-governance.evidence.right-sizing",
    "cost-governance.evidence.settlement",
}
NEGATIVE_REASON_BY_FIXTURE = {
    "f1-reversed-links": "reversed_link",
    "f2-stale-intent": "stale_intent",
    "f3-missing-source-authority": "missing_source_authority",
    "f4-unknown-service": "unknown_service",
    "f5-conflicting-facts": "conflicting_facts",
    "f6-mixed-releases": "mixed_release",
    "f7-unverified-outcomes": "unverified_outcome",
    "f8-truncated-graph": "truncated_graph",
}
REASON_ORDER = tuple(NEGATIVE_REASON_BY_FIXTURE.values())
FORBIDDEN_AUTHORITY_FIELDS = {
    "approval_authority",
    "can_approve",
    "can_execute",
    "can_promote",
    "execution_authority",
    "grants_authority",
    "mutation_authority",
    "promotion_authority",
}


class SemanticProfileError(ValueError):
    """Report one deterministic semantic profile or fixture contract failure."""


def canonical_sha256(value: Any) -> str:
    """Return the repository canonical SHA-256 identity for a JSON-compatible value."""

    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def profile_content_sha256(profile: Mapping[str, Any]) -> str:
    """Hash a profile while excluding its self-referential identity field."""

    payload = deepcopy(dict(profile))
    payload.pop("canonical_sha256", None)
    return canonical_sha256(payload)


def load_profile(path: Path = PROFILE_PATH) -> dict[str, Any]:
    """Load the standalone package resource without importing package code."""

    return _load_json(path)


def load_fixtures(root: Path = FIXTURE_ROOT) -> tuple[dict[str, Any], ...]:
    """Load the deterministic fixture corpus in filename order."""

    return tuple(_load_json(path) for path in sorted(root.glob("*.json")))


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SemanticProfileError(f"{path}: cannot load JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SemanticProfileError(f"{path}: root must be an object")
    return value


def _load_catalog() -> Any:
    return load_ontology_catalog(
        CATALOG_ROOT,
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=CATALOG_ROOT / "probes",
    )


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise SemanticProfileError(message)


def _truthy_authority_paths(value: Any, path: str = "$") -> tuple[str, ...]:
    failures: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_AUTHORITY_FIELDS and child not in (False, None):
                failures.append(child_path)
            failures.extend(_truthy_authority_paths(child, child_path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            failures.extend(_truthy_authority_paths(child, f"{path}[{index}]"))
    return tuple(failures)


def _referenced_declaration_files(profile: Mapping[str, Any]) -> tuple[Path, ...]:
    paths: list[Path] = []
    for ref in profile["declarations"]:
        kind = ref["kind"]
        if kind == "object":
            path = CATALOG_ROOT / "vocabulary/object-types" / f"{ref['name']}.yaml"
        elif kind == "link":
            path = CATALOG_ROOT / "vocabulary/link-types" / f"{ref['name']}.yaml"
        elif kind == "action":
            path = CATALOG_ROOT / "action-types" / f"{ref['name']}.yaml"
            if not path.exists():
                matches = tuple((CATALOG_ROOT / "action-types").glob("*.yaml"))
                path = next(
                    (
                        candidate
                        for candidate in matches
                        if yaml.safe_load(candidate.read_text(encoding="utf-8")).get("name")
                        == ref["name"]
                    ),
                    path,
                )
        else:
            raise SemanticProfileError(f"unsupported declaration kind {kind!r}")
        _assert(path.is_file(), f"missing declaration file for {kind}:{ref['name']}")
        paths.append(path)
    return tuple(paths)


def validate_profile_data(profile: Mapping[str, Any], *, catalog: Any | None = None) -> str:
    """Validate exact release identity, bounded profiles, ownership, and no-authority fields."""

    _assert(profile.get("schema_version") == "1.0.0", "profile schema_version must be 1.0.0")
    _assert(
        profile.get("profile_id") == "cost-governance.semantic-profile",
        "profile_id must remain stable",
    )
    _assert(profile.get("profile_version") == "1.0.0", "profile_version must be 1.0.0")
    expected_profile_sha = profile_content_sha256(profile)
    _assert(
        profile.get("canonical_sha256") == expected_profile_sha,
        "profile canonical_sha256 does not match canonical content",
    )
    active_catalog = catalog or _load_catalog()
    release = active_catalog.build_release()
    release_digest = profile.get("ontology_release_digest")
    _assert(
        release_digest == release.digest,
        "profile does not pin the exact active ontology release",
    )

    declared_refs = profile.get("declarations")
    _assert(isinstance(declared_refs, list), "profile declarations must be a list")
    identities = [(item.get("kind"), item.get("name")) for item in declared_refs]
    _assert(
        len(identities) == len(set(identities)),
        "profile declaration identities must be unique",
    )
    _assert(
        identities == sorted(identities),
        "profile declarations must use canonical kind and name order",
    )
    release_refs = {
        (item.kind.value, item.name): item.model_dump(mode="json") for item in release.declarations
    }
    for item in declared_refs:
        identity = (item.get("kind"), item.get("name"))
        _assert(identity in release_refs, f"profile references unknown declaration {identity}")
        _assert(item == release_refs[identity], f"profile declaration is not exact: {identity}")

    by_kind = {
        kind: {name for item_kind, name in identities if item_kind == kind}
        for kind in ("action", "link", "object")
    }
    _assert(by_kind["object"] == EXPECTED_OBJECTS, "profile ObjectType set is not the W1 contract")
    _assert(by_kind["link"] == EXPECTED_LINKS, "profile LinkType set is not the W1 contract")
    _assert(by_kind["action"] == EXPECTED_ACTIONS, "profile ActionType set is not the W1 contract")

    object_sets = profile.get("object_sets")
    _assert(isinstance(object_sets, list), "object_sets must be a list")
    _assert(
        {item.get("id") for item in object_sets} == EXPECTED_OBJECT_SETS,
        "profile must define exactly the five W1 ObjectSet profiles",
    )
    for item in object_sets:
        bounds = item.get("bounds", {})
        _assert(
            all(
                isinstance(bounds.get(key), int) and bounds[key] > 0
                for key in ("max_depth", "max_edges", "max_objects")
            ),
            f"{item.get('id')}: bounds must be positive integers",
        )
        _assert(
            set(item.get("object_types", ())) <= EXPECTED_OBJECTS,
            f"{item.get('id')}: unknown ObjectType",
        )
        _assert(
            set(item.get("link_types", ())) <= EXPECTED_LINKS,
            f"{item.get('id')}: unknown LinkType",
        )

    functions = profile.get("evidence_functions")
    _assert(isinstance(functions, list), "evidence_functions must be a list")
    _assert(
        {item.get("id") for item in functions} == EXPECTED_EVIDENCE_FUNCTIONS,
        "profile must define exactly the five W1 evidence functions",
    )
    for item in functions:
        _assert(
            item.get("source_authority_required") is True,
            f"{item.get('id')}: source authority is required",
        )
        _assert(
            item.get("autonomy_effect") == "preserve_or_lower",
            f"{item.get('id')}: invalid autonomy effect",
        )
        _assert(
            isinstance(item.get("max_records"), int) and item["max_records"] > 0,
            f"{item.get('id')}: invalid record bound",
        )

    gates = profile.get("competency_gates")
    _assert(isinstance(gates, list), "competency_gates must be a list")
    _assert(
        [item.get("id") for item in gates] == [f"F{index}" for index in range(1, 9)],
        "competency_gates must contain ordered F1-F8",
    )
    safety = profile.get("safety")
    _assert(isinstance(safety, dict), "profile safety block is required")
    _assert(safety.get("autonomy_effect") == "preserve_or_lower", "profile may not raise autonomy")
    for key in ("approval_authority", "execution_authority", "promotion_authority"):
        _assert(safety.get(key) is False, f"profile safety.{key} must be false")

    authority_failures = list(_truthy_authority_paths(profile))
    for path in _referenced_declaration_files(profile):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        authority_failures.extend(
            f"{path.relative_to(REPO_ROOT)}{failure[1:]}"
            for failure in _truthy_authority_paths(raw)
        )
    _assert(
        not authority_failures,
        "ontology/profile grants authority at " + ", ".join(authority_failures),
    )

    new_owners = {
        item.name: item.lifecycle.owner.value
        for item in active_catalog.object_types
        if item.name
        in {
            "Budget",
            "CapacityForecast",
            "CostAnomaly",
            "CostObservation",
            "SizingRecommendation",
        }
    }
    _assert(
        new_owners
        == {
            "Budget": "Njord",
            "CapacityForecast": "Freyr",
            "CostAnomaly": "Njord",
            "CostObservation": "Njord",
            "SizingRecommendation": "Freyr",
        },
        "Cost Governance declarations must preserve Njord and Freyr ownership",
    )
    return expected_profile_sha


def _parse_time(value: str, *, label: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise SemanticProfileError(f"{label}: invalid RFC 3339 timestamp") from exc


def evaluate_fixture(
    fixture: Mapping[str, Any],
    profile: Mapping[str, Any],
    *,
    link_endpoints: Mapping[str, tuple[str, str]],
) -> dict[str, Any]:
    """Reduce one fixture to a never-raising semantic autonomy ceiling."""

    reasons: set[str] = set()
    context = fixture.get("context", {})
    _assert(isinstance(context, dict), f"{fixture.get('fixture_id')}: context must be an object")
    for link in context.get("links", ()):
        link_type = link.get("type")
        expected = link_endpoints.get(link_type)
        if expected is None or (link.get("from_type"), link.get("to_type")) != expected:
            reasons.add("reversed_link")

    cutoff = _parse_time(fixture.get("cutoff"), label=f"{fixture.get('fixture_id')}.cutoff")
    for intent in context.get("intent", ()):
        start = _parse_time(intent.get("effective_from"), label="intent.effective_from")
        end_value = intent.get("effective_to")
        end = _parse_time(end_value, label="intent.effective_to") if end_value else None
        if start > cutoff or (end is not None and end < cutoff):
            reasons.add("stale_intent")

    if context.get("operating_scope", {}).get("service_status") == "unknown_service":
        reasons.add("unknown_service")
    graph = context.get("graph", {})
    if graph.get("complete") is False or graph.get("truncated") is True:
        reasons.add("truncated_graph")
    for release_ref in context.get("release_refs", ()):
        if release_ref != profile["ontology_release_digest"]:
            reasons.add("mixed_release")
    facts = context.get("facts", ())
    if any(fact.get("conflicting") is True for fact in facts):
        reasons.add("conflicting_facts")
    if any(not fact.get("source_authority_ref") for fact in facts):
        reasons.add("missing_source_authority")
    for outcome in context.get("outcomes", ()):
        if outcome.get("verification") != "verified" or outcome.get("independent") is not True:
            reasons.add("unverified_outcome")

    ordered_reasons = [reason for reason in REASON_ORDER if reason in reasons]
    return {
        "autonomy_ceiling": "shadow_only" if ordered_reasons else "preserve",
        "reason_codes": ordered_reasons,
    }


def validate_fixture_data(
    fixture: Mapping[str, Any],
    profile: Mapping[str, Any],
    *,
    link_endpoints: Mapping[str, tuple[str, str]],
) -> dict[str, Any]:
    """Validate one exact-release competency fixture and its expected reduction."""

    fixture_id = fixture.get("fixture_id")
    _assert(fixture.get("schema_version") == "1.0.0", f"{fixture_id}: invalid schema version")
    _assert(
        fixture.get("ontology_release_digest") == profile["ontology_release_digest"],
        f"{fixture_id}: fixture release does not match profile",
    )
    _assert(
        fixture.get("semantic_profile_sha256") == profile["canonical_sha256"],
        f"{fixture_id}: fixture profile digest does not match",
    )
    _assert(
        fixture.get("gate") in {f"F{index}" for index in range(1, 9)},
        f"{fixture_id}: invalid gate",
    )
    _assert(fixture.get("case") in {"positive", "negative"}, f"{fixture_id}: invalid case")
    _assert(not _truthy_authority_paths(fixture), f"{fixture_id}: fixture grants authority")
    actual = evaluate_fixture(fixture, profile, link_endpoints=link_endpoints)
    _assert(
        actual == fixture.get("expected"),
        f"{fixture_id}: expected reduction does not match {actual}",
    )
    if fixture["case"] == "positive":
        _assert(
            actual == {"autonomy_ceiling": "preserve", "reason_codes": []},
            f"{fixture_id}: positive case lowered autonomy",
        )
    else:
        _assert(
            actual["autonomy_ceiling"] == "shadow_only",
            f"{fixture_id}: negative case did not lower autonomy",
        )
        _assert(
            actual["reason_codes"] == [NEGATIVE_REASON_BY_FIXTURE.get(fixture_id)],
            f"{fixture_id}: negative case must isolate its named defect",
        )
    return actual


def validate_repository() -> dict[str, Any]:
    """Validate the profile and complete F1-F8 positive and negative corpus."""

    profile = load_profile()
    catalog = _load_catalog()
    profile_sha = validate_profile_data(profile, catalog=catalog)
    link_endpoints = {
        item.name: (item.from_type, item.to_type)
        for item in catalog.link_types
        if item.name in EXPECTED_LINKS
    }
    fixtures = load_fixtures()
    _assert(len(fixtures) == 16, "fixture corpus must contain exactly 16 cases")
    fixture_ids = [fixture.get("fixture_id") for fixture in fixtures]
    _assert(len(fixture_ids) == len(set(fixture_ids)), "fixture ids must be unique")
    results = [
        validate_fixture_data(fixture, profile, link_endpoints=link_endpoints)
        for fixture in fixtures
    ]
    for gate in (f"F{index}" for index in range(1, 9)):
        gate_cases = {fixture["case"] for fixture in fixtures if fixture["gate"] == gate}
        _assert(
            gate_cases == {"positive", "negative"},
            f"{gate}: requires positive and negative cases",
        )
    _assert(
        {fixture["fixture_id"] for fixture in fixtures if fixture["case"] == "negative"}
        == set(NEGATIVE_REASON_BY_FIXTURE),
        "negative fixture set does not match the W1 contract",
    )
    return {
        "ontology_release_digest": profile["ontology_release_digest"],
        "semantic_profile_sha256": profile_sha,
        "fixtures": len(fixtures),
        "positive": sum(result["autonomy_ceiling"] == "preserve" for result in results),
        "lowered": sum(result["autonomy_ceiling"] == "shadow_only" for result in results),
    }


def main() -> int:
    """Run the repository validation and print one stable summary."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        result = validate_repository()
    except SemanticProfileError as exc:
        print(f"cost-governance-semantic-profile: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "cost-governance-semantic-profile: PASS "
        f"release={result['ontology_release_digest']} "
        f"profile={result['semantic_profile_sha256']} "
        f"fixtures={result['fixtures']} "
        f"positive={result['positive']} lowered={result['lowered']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

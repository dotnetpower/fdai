"""Completeness and cross-reference gates for Azure WAF checklist controls."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from fdai.rule_catalog.schema.best_practice_catalog import load_best_practice_catalog
from fdai.rule_catalog.schema.framework_catalog import load_framework_catalog
from fdai.rule_catalog.schema.governance_catalog import load_governance_catalog
from fdai.rule_catalog.schema.probe import load_probe_catalog, probe_ids
from fdai.shared.contracts.models import RequirementKind

_ROOT = Path(__file__).resolve().parents[5]
_CATALOG = _ROOT / "rule-catalog"


def _mapping(value: Any) -> Mapping[str, Any]:
    assert isinstance(value, Mapping)
    return value


def _rule_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for path in sorted((_CATALOG / "catalog").glob("*.yaml")):
        raw = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")))
        versions[str(raw["id"])] = str(raw["version"])
    return versions


def _review_registries() -> dict[RequirementKind, set[str]]:
    raw = _mapping(yaml.safe_load((_ROOT / "config" / "architecture-review.yaml").read_text()))
    review = _mapping(raw["architecture_review"])
    gate = _mapping(review["production_gate"])
    artifact_ids = {str(_mapping(artifact)["id"]) for artifact in review["artifacts"]}
    evidence_ids = {str(item) for item in gate["checklist_required_evidence"]}
    evidence_kinds = _mapping(gate["evidence_kinds"])
    owner_ids = {str(item) for item in gate["required_owner_slots"]}
    assert set(evidence_kinds) == evidence_ids
    return {
        RequirementKind.RULE: set(_rule_versions()),
        RequirementKind.PROBE: probe_ids(load_probe_catalog(_CATALOG / "probes")),
        RequirementKind.ARTIFACT: artifact_ids
        | {ref for ref, kind in evidence_kinds.items() if kind == "artifact"},
        RequirementKind.METRIC: {ref for ref, kind in evidence_kinds.items() if kind == "metric"},
        RequirementKind.DRILL: {ref for ref, kind in evidence_kinds.items() if kind == "drill"},
        RequirementKind.APPROVAL: owner_ids,
    }


def test_all_current_waf_controls_are_present_and_grounded() -> None:
    controls = load_best_practice_catalog(
        _CATALOG / "best-practices",
        known_refs=_review_registries(),
    )

    frameworks = load_framework_catalog(
        _CATALOG / "frameworks",
        best_practices=controls,
        objective_refs=frozenset({"reliability.node-pool.zone-failure-tolerance@1.0.0"}),
        additional_roots=(_CATALOG / "collected/wara-aprl",),
    )
    waf = next(item for item in frameworks if item.id == "azure-waf")
    expected = {item.control.id for item in waf.resolved_controls()}
    assert len(expected) == 59
    assert {control.control_id for control in controls} == expected
    assert all(
        any(requirement.kind is RequirementKind.APPROVAL for requirement in control.requirements)
        for control in controls
    )


def test_waf_rule_sets_pin_existing_rule_versions() -> None:
    catalog = load_governance_catalog(
        _CATALOG,
        known_rule_versions=_rule_versions(),
    )

    assert {rule_set.id for rule_set in catalog.rule_sets} >= {
        "azure-waf.reliability",
        "azure-waf.operational-excellence",
        "azure-waf.security",
        "azure-waf.cost-optimization",
        "azure-waf.performance-efficiency",
    }

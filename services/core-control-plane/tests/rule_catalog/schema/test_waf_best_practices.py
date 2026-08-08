"""Completeness and cross-reference gates for Azure WAF checklist controls."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from fdai.rule_catalog.schema.best_practice_catalog import load_best_practice_catalog
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
    evidence_ids = {str(item) for item in gate["required_evidence"]}
    owner_ids = {str(item) for item in gate["required_owner_slots"]}
    evidence_or_artifact = artifact_ids | evidence_ids
    return {
        RequirementKind.RULE: set(_rule_versions()),
        RequirementKind.PROBE: probe_ids(load_probe_catalog(_CATALOG / "probes")),
        RequirementKind.ARTIFACT: evidence_or_artifact,
        RequirementKind.METRIC: evidence_ids,
        RequirementKind.DRILL: evidence_ids,
        RequirementKind.APPROVAL: owner_ids,
    }


def test_all_current_waf_controls_are_present_and_grounded() -> None:
    controls = load_best_practice_catalog(
        _CATALOG / "best-practices",
        known_refs=_review_registries(),
    )

    expected = {f"RE:{number:02d}" for number in range(1, 11)} | {
        f"OE:{number:02d}" for number in range(1, 12)
    }
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
    }

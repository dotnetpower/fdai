"""Configuration drift ontology vocabulary contracts."""

from __future__ import annotations

from pathlib import Path

from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]
OBJECT_ROOT = REPO_ROOT / "rule-catalog" / "vocabulary" / "object-types"
LINK_ROOT = REPO_ROOT / "rule-catalog" / "vocabulary" / "link-types"


def test_configuration_drift_vocabulary_preserves_evidence_and_authority_boundaries() -> None:
    registry = PackageResourceSchemaRegistry()
    objects = load_object_type_catalog(OBJECT_ROOT, schema_registry=registry)
    by_name = {entry.name: entry for entry in objects}

    assert {
        "ConfigurationBaseline",
        "ConfigurationDriftCheck",
        "ConfigurationDriftEvidence",
        "ConfigurationDriftFinding",
    } <= set(by_name)
    assert by_name["ConfigurationDriftCheck"].properties["execution_authority"].required
    assert by_name["ConfigurationDriftFinding"].properties["execution_authority"].required
    assert by_name["ConfigurationDriftEvidence"].properties["redaction_summary"].required
    assert "expected_summary" in by_name["ConfigurationDriftFinding"].properties
    assert not by_name["ConfigurationDriftFinding"].properties["expected_summary"].required

    links = load_link_type_catalog(
        LINK_ROOT,
        schema_registry=registry,
        object_types=objects,
    )
    link_by_name = {entry.name: entry for entry in links}
    expected_endpoints = {
        "baseline_used_by_drift_check": ("ConfigurationBaseline", "ConfigurationDriftCheck"),
        "drift_check_supported_by_evidence": (
            "ConfigurationDriftCheck",
            "ConfigurationDriftEvidence",
        ),
        "drift_check_produces_finding": (
            "ConfigurationDriftCheck",
            "ConfigurationDriftFinding",
        ),
        "drift_finding_affects_resource": ("ConfigurationDriftFinding", "Resource"),
        "hypothesis_explains_drift_finding": (
            "CausalHypothesis",
            "ConfigurationDriftFinding",
        ),
    }
    assert {
        name: (link_by_name[name].from_type, link_by_name[name].to_type)
        for name in expected_endpoints
    } == expected_endpoints
    assert link_by_name["hypothesis_explains_drift_finding"].is_causal is True

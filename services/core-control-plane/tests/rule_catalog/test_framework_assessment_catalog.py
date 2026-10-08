"""Completeness and safety gates for generated WAF, CAF, and MCSB assessment catalogs."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.schema.framework_assessment import (
    FrameworkAssessmentCatalog,
    FrameworkCrosswalkKind,
    FrameworkEvidenceRole,
    FrameworkProcessPhase,
    FrameworkRequirementKind,
    load_framework_assessment_catalog,
)

ROOT = Path(__file__).resolve().parents[4]
GENERATED = ROOT / "rule-catalog/framework-assessments/generated"


def _catalog(name: str):
    return load_framework_assessment_catalog(GENERATED / f"{name}.json")


def test_waf_catalog_covers_all_controls_and_evidence_references() -> None:
    catalog = _catalog("azure-waf")

    assert len(catalog.controls) == 59
    assert sum(len(control.evidence) for control in catalog.controls) == 186
    assert all(
        item.authoritative_producer is not None or item.blocked_dependency is not None
        for control in catalog.controls
        for item in control.evidence
    )
    assert all(control.owner_slot for control in catalog.controls)
    assert {
        reference.target_kind for control in catalog.controls for reference in control.crosswalk
    } >= {
        FrameworkCrosswalkKind.BEST_PRACTICE,
        FrameworkCrosswalkKind.RULE,
        FrameworkCrosswalkKind.MANUAL_EVIDENCE,
    }


def test_caf_catalog_covers_all_areas_and_process_evidence() -> None:
    catalog = _catalog("azure-caf")

    assert len(catalog.controls) == 15
    by_id = {control.control_id: control for control in catalog.controls}
    assert set(by_id) >= {"strategy", "plan", "adopt", "ready", "govern", "secure", "manage"}
    for control_id in ("strategy", "plan", "adopt"):
        assert {item.process_phase for item in by_id[control_id].evidence} >= {
            FrameworkProcessPhase.PROCEDURE,
            FrameworkProcessPhase.EXECUTION,
        }
    assert all(
        item.authoritative_producer is not None or item.blocked_dependency is not None
        for control in catalog.controls
        for item in control.evidence
    )
    assert all(control.crosswalk for control in catalog.controls)


def test_caf_crosswalk_targets_resolve_exact_catalog_records() -> None:
    caf = _catalog("azure-caf")
    waf = _catalog("azure-waf")
    mcsb_raw = yaml.safe_load((ROOT / "rule-catalog/compliance/mcsb/v1/controls.yaml").read_text())
    policy_raw = yaml.safe_load(
        (ROOT / "rule-catalog/compliance/mcsb/v1/crosswalk.yaml").read_text()
    )
    mcsb_ids = {str(item["id"]) for item in mcsb_raw["controls"]}
    policy_ids = {str(item["profile_id"]) for item in policy_raw["policy_profiles"]}
    waf_ids = {item.control_id for item in waf.controls}

    for control in caf.controls:
        evidence_refs = {item.source_ref for item in control.evidence}
        for reference in control.crosswalk:
            if reference.target_kind is FrameworkCrosswalkKind.WAF:
                assert reference.target_ref in waf_ids
            elif reference.target_kind is FrameworkCrosswalkKind.MCSB:
                assert reference.target_ref in mcsb_ids
            elif reference.target_kind is FrameworkCrosswalkKind.AZURE_POLICY:
                assert reference.target_ref in policy_ids
            elif reference.target_kind in {
                FrameworkCrosswalkKind.OBSERVATION,
                FrameworkCrosswalkKind.MANUAL_EVIDENCE,
            }:
                assert reference.target_ref in evidence_refs


def test_generated_catalogs_are_content_addressed() -> None:
    first = _catalog("azure-waf")
    second = _catalog("azure-waf")

    assert first == second
    assert first.catalog_digest.startswith("sha256:")


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_framework_assessments", ROOT / "scripts/catalog/build_framework_assessments.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_mcsb(source_path: Path | None = None) -> dict[str, object]:
    catalog_root = ROOT / "rule-catalog"
    return _builder().build_mcsb_catalog(
        controls_path=catalog_root / "compliance/mcsb/v1/controls.yaml",
        crosswalk_path=catalog_root / "compliance/mcsb/v1/crosswalk.yaml",
        source_path=source_path or catalog_root / "framework-assessments/azure-mcsb.source.yaml",
    )


def test_mcsb_catalog_is_fresh_and_covers_every_control() -> None:
    catalog = _catalog("azure-mcsb")
    controls_raw = yaml.safe_load(
        (ROOT / "rule-catalog/compliance/mcsb/v1/controls.yaml").read_text()
    )

    assert json.loads((GENERATED / "azure-mcsb.json").read_text()) == _build_mcsb()
    assert catalog.framework_scope.value == "workload"
    assert {control.control_id for control in catalog.controls} == {
        str(item["id"]) for item in controls_raw["controls"]
    }
    assert all(control.owner_slot for control in catalog.controls)


def test_mcsb_rules_never_satisfy_a_control_alone() -> None:
    catalog: FrameworkAssessmentCatalog = _catalog("azure-mcsb")

    for control in catalog.controls:
        manual = [
            item for item in control.evidence if item.kind is FrameworkRequirementKind.ARTIFACT
        ]
        assert len(manual) == 1
        assert manual[0].evidence_role is FrameworkEvidenceRole.DECISIVE
        assert control.requirement_mode == "all"


def test_mcsb_rule_bindings_review_exactly_the_crosswalk_mappings() -> None:
    catalog = _catalog("azure-mcsb")
    crosswalk = yaml.safe_load(
        (ROOT / "rule-catalog/compliance/mcsb/v1/crosswalk.yaml").read_text()
    )
    mapped = {
        (str(item["control_id"]), str(rule_id))
        for item in crosswalk["mappings"]
        for rule_id in item.get("rule_ids", [])
    }
    bound = {
        (control.control_id, item.source_ref)
        for control in catalog.controls
        for item in control.evidence
        if item.kind is FrameworkRequirementKind.RULE
    }

    assert bound == mapped
    roles = {
        item.evidence_role
        for control in catalog.controls
        for item in control.evidence
        if item.kind is FrameworkRequirementKind.RULE
    }
    assert roles == {FrameworkEvidenceRole.DECISIVE, FrameworkEvidenceRole.SUPPORTING_ONLY}


def test_mcsb_builder_rejects_unreviewed_or_incomplete_bindings(tmp_path: Path) -> None:
    source = yaml.safe_load(
        (ROOT / "rule-catalog/framework-assessments/azure-mcsb.source.yaml").read_text()
    )
    missing = dict(source, rule_bindings=source["rule_bindings"][1:])
    unexplained = dict(
        source,
        rule_bindings=[dict(source["rule_bindings"][0], rationale=" ")]
        + source["rule_bindings"][1:],
    )
    unreviewed = dict(source, review_state="draft")

    for index, variant in enumerate((missing, unexplained, unreviewed)):
        path = tmp_path / f"source-{index}.yaml"
        path.write_text(yaml.safe_dump(variant))
        with pytest.raises(ValueError):
            _build_mcsb(path)

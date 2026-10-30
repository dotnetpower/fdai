from pathlib import Path

import pytest
from fdai.delivery.framework_guidance_presentation import (
    framework_guidance_pins,
    validate_framework_guidance_inputs,
)
from fdai.rule_catalog.schema.framework_assessment import load_framework_assessment_catalog

ROOT = Path(__file__).resolve().parents[4] / "rule-catalog"
DEFINITIONS = {
    "azure-waf": "frameworks/azure-waf.yaml",
    "azure-caf": "frameworks/azure-caf.yaml",
    "azure-mcsb": "compliance/mcsb/v1/controls.yaml",
}


def _assessments():
    return {
        framework_id: load_framework_assessment_catalog(
            ROOT / "framework-assessments/generated" / f"{framework_id}.json"
        )
        for framework_id in DEFINITIONS
    }


def test_materializer_guidance_matches_exact_current_sources() -> None:
    assessments = _assessments()
    validate_framework_guidance_inputs(ROOT, assessments)
    for assessment in assessments.values():
        control = assessment.controls[0]
        assert framework_guidance_pins(assessment, control.control_id) == {
            "guidance_source_revision": assessment.source_revision_digest,
            "guidance_source_digest": control.specification_digest,
        }


def test_definition_drift_is_not_hidden_by_matching_guide_pins(tmp_path: Path) -> None:
    for relative_path in DEFINITIONS.values():
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative_path).read_bytes())
    with (tmp_path / DEFINITIONS["azure-caf"]).open("ab") as stream:
        stream.write(b"\n# changed after assessment review\n")
    with pytest.raises(ValueError, match="definition differs"):
        validate_framework_guidance_inputs(tmp_path, _assessments())


def test_unknown_control_cannot_get_an_authoritative_pin() -> None:
    with pytest.raises(ValueError, match="outside the reviewed assessment"):
        framework_guidance_pins(_assessments()["azure-waf"], "example-unknown")

"""Verify source-bound framework guidance through the real Operator attachment."""

from pathlib import Path

import pytest
from fdai.delivery.framework_guidance_presentation import framework_guidance_pins
from fdai.rule_catalog.schema.framework_assessment import load_framework_assessment_catalog
from fdai_operator_service.framework_guidance_projection import attach_framework_guidance
from starlette.exceptions import HTTPException

ROOT = Path(__file__).resolve().parents[3] / "rule-catalog/framework-assessments/generated"


@pytest.mark.parametrize(
    "framework_id,expected", [("azure-waf", 59), ("azure-mcsb", 86), ("azure-caf", 15)]
)
def test_every_control_attaches_only_its_source_bound_guide(
    framework_id: str, expected: int
) -> None:
    catalog = load_framework_assessment_catalog(ROOT / f"{framework_id}.json")
    assert len(catalog.controls) == expected
    for specification in catalog.controls:
        detail = {
            "control_id": specification.control_id,
            "benchmark_version": "v1",
            "source_revision": "a" * 40,
            "execution_authority": False,
            **framework_guidance_pins(catalog, specification.control_id),
        }
        attached = attach_framework_guidance(detail, framework_id=framework_id)
        guide = attached["guidance"]
        assert isinstance(guide, dict)
        assert guide["framework_id"] == framework_id
        assert guide["control_id"] == specification.control_id
        assert guide["source_revision"] == catalog.source_revision_digest
        assert guide["source_digest"] == specification.specification_digest
        assert guide["title"]["en"]
        assert guide["title"]["ko"]
        assert attached["source_revision"] == "a" * 40
        assert attached["execution_authority"] is False


def test_missing_legacy_pins_are_visible_not_fabricated() -> None:
    attached = attach_framework_guidance({"control_id": "RE:01"}, framework_id="azure-waf")
    assert attached["guidance"] is None
    assert attached["guidance_unavailable_reason"]


def test_present_wrong_pin_is_a_bounded_service_error() -> None:
    catalog = load_framework_assessment_catalog(ROOT / "azure-waf.json")
    control_id = catalog.controls[0].control_id
    with pytest.raises(HTTPException) as error:
        attach_framework_guidance(
            {
                "control_id": control_id,
                **framework_guidance_pins(catalog, control_id),
                "guidance_source_digest": "sha256:" + "0" * 64,
            },
            framework_id="azure-waf",
        )
    assert error.value.status_code == 503
    assert error.value.detail == "Framework guidance source validation failed"


def test_preview_never_inherits_v1_guidance() -> None:
    catalog = load_framework_assessment_catalog(ROOT / "azure-mcsb.json")
    control_id = catalog.controls[0].control_id
    attached = attach_framework_guidance(
        {
            "control_id": control_id,
            "benchmark_version": "v2-preview",
            **framework_guidance_pins(catalog, control_id),
        },
        framework_id="azure-mcsb",
    )
    assert attached["guidance"] is None

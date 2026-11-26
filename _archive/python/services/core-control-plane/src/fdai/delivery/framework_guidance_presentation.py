"""Bind packaged guidance to validated, deployment-materialized source catalogs."""

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from fdai_service_contracts.framework_guidance import (
    assert_framework_guidance_catalog,
    packaged_framework_guidance,
)

from fdai.rule_catalog.schema.framework_assessment import FrameworkAssessmentCatalog

_DEFINITIONS = {
    "azure-waf": "frameworks/azure-waf.yaml",
    "azure-caf": "frameworks/azure-caf.yaml",
    "azure-mcsb": "compliance/mcsb/v1/controls.yaml",
}


def validate_framework_guidance_inputs(
    catalog_root: Path, assessments: Mapping[str, FrameworkAssessmentCatalog]
) -> None:
    guidance = packaged_framework_guidance()
    for framework_id, relative_path in _DEFINITIONS.items():
        assessment = assessments[framework_id]
        body = json.dumps(assessment.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
        assert_framework_guidance_catalog(guidance, framework_id, body)
        definition_digest = (
            "sha256:" + hashlib.sha256((catalog_root / relative_path).read_bytes()).hexdigest()
        )
        if definition_digest != assessment.framework_definition_digest:
            raise ValueError("framework guidance definition differs from the reviewed assessment")


def framework_guidance_pins(
    assessment: FrameworkAssessmentCatalog, control_id: str
) -> dict[str, str]:
    specification = next(
        (control for control in assessment.controls if control.control_id == control_id), None
    )
    if specification is None:
        raise ValueError("framework guidance control is outside the reviewed assessment")
    return {
        "guidance_source_revision": assessment.source_revision_digest,
        "guidance_source_digest": specification.specification_digest,
    }

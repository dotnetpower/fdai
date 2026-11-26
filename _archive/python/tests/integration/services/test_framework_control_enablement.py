"""Verify that disabled Core controls remain valid, complete Operator read models."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fdai.core.framework_assessment import FrameworkAssessmentRequest, FrameworkAssessmentRuntime
from fdai.delivery.authoritative_framework_projection import (
    _best_practice_snapshot,
    _caf_snapshot,
    _mcsb_assessment_snapshot,
)
from fdai.delivery.framework_assessment_cli import _profile
from fdai.rule_catalog.schema.best_practice_catalog import load_best_practice_catalog
from fdai.rule_catalog.schema.framework_assessment import load_framework_assessment_catalog
from fdai.rule_catalog.schema.framework_catalog import FrameworkDefinition
from fdai_operator_service.framework_assessment_projection import project_framework_assessment
from fdai_service_contracts.control_enablement_profile import ControlEnablementProfile

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "rule-catalog"
NOW = datetime(2026, 10, 30, tzinfo=UTC)
SCOPE = "sha256:" + "1" * 64


@pytest.mark.parametrize("framework_id", ["azure-waf", "azure-caf", "azure-mcsb"])
def test_disabled_control_survives_core_to_operator_projection(framework_id: str) -> None:
    catalog = load_framework_assessment_catalog(
        CATALOG / "framework-assessments/generated" / f"{framework_id}.json"
    )
    practices = load_best_practice_catalog(CATALOG / "best-practices", strict=False)
    if framework_id == "azure-waf":
        projection = _best_practice_snapshot(practices, catalog)
    elif framework_id == "azure-caf":
        framework = FrameworkDefinition.model_validate(
            yaml.safe_load((CATALOG / "frameworks/azure-caf.yaml").read_text(encoding="utf-8"))
        )
        projection = _caf_snapshot(framework, catalog)
    else:
        projection = _mcsb_assessment_snapshot(catalog)
    selected = catalog.controls[0]
    material = {
        "schema_version": "1.0.0",
        "framework_id": framework_id,
        "source_revision": catalog.source_revision_digest,
        "scope_digest": SCOPE,
        "reviewed_by": "framework-reviewer",
        "reviewed_at": "2026-10-30T00:00:00Z",
        "overrides": [{"control_id": selected.control_id, "enabled": False}],
    }
    enablement = ControlEnablementProfile.model_validate(
        {**material, "profile_digest": ControlEnablementProfile.digest_material(material)}
    )
    workload = catalog.framework_scope.value == "workload"
    profile = _profile(
        catalog,
        scope_digest=SCOPE,
        ontology_release="ontology:example",
        reviewer_identity="framework-reviewer",
        reviewed_at=NOW,
        inventory_generation="inventory:example" if workload else None,
        hierarchy_generation=None if workload else "hierarchy:example",
        enablement_profile=enablement,
    )
    result = FrameworkAssessmentRuntime(catalog).assess(
        FrameworkAssessmentRequest(
            assessment_id="assessment:example",
            profile=profile,
            evaluated_at=NOW,
            recorded_at=NOW,
        )
    )
    projected = project_framework_assessment(projection, result.to_dict())
    assert len(projected["controls"]) == len(catalog.controls)
    control = next(
        item for item in projected["controls"] if item["control_id"] == selected.control_id
    )
    assert control["enablement"]["enabled"] is False
    assert control["evaluation_status"] == "not_evaluated"
    assert control["satisfaction"] == "unknown"
    assert control["evidence_complete"] is False
    assert tuple(control["limitations"]) == ("control_disabled",)
    assert control["execution_authority"] is False

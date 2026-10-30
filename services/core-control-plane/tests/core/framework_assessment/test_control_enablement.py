from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.framework_assessment import FrameworkAssessmentRequest, FrameworkAssessmentRuntime
from fdai.delivery.framework_assessment_cli import _profile
from fdai.rule_catalog.schema.framework_assessment import (
    FrameworkAssessmentCatalog,
    canonical_digest,
    load_framework_assessment_catalog,
)
from fdai_service_contracts.control_enablement_profile import ControlEnablementProfile

ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 10, 30, tzinfo=UTC)
SCOPE = "sha256:" + "1" * 64


def _catalog(framework_id: str, severity: str) -> FrameworkAssessmentCatalog:
    catalog = load_framework_assessment_catalog(
        ROOT / "rule-catalog/framework-assessments/generated" / f"{framework_id}.json"
    )
    material = catalog.model_dump(mode="json")
    control = material["controls"][0]
    control["severity"] = severity
    control.pop("specification_digest")
    control["specification_digest"] = canonical_digest(control)
    material.pop("catalog_digest")
    material["catalog_digest"] = canonical_digest(material)
    return FrameworkAssessmentCatalog.model_validate(material)


def _request(
    catalog: FrameworkAssessmentCatalog, override: bool | None = None
) -> FrameworkAssessmentRequest:
    enablement = None
    if override is not None:
        material = {
            "schema_version": "1.0.0",
            "framework_id": catalog.framework_id,
            "source_revision": catalog.source_revision_digest,
            "scope_digest": SCOPE,
            "reviewed_by": "framework-reviewer",
            "reviewed_at": "2026-10-30T00:00:00Z",
            "overrides": [{"control_id": catalog.controls[0].control_id, "enabled": override}],
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
    return FrameworkAssessmentRequest(
        assessment_id="assessment:example",
        profile=profile,
        evaluated_at=NOW,
        recorded_at=NOW,
    )


@pytest.mark.parametrize("framework", ["azure-waf", "azure-mcsb", "azure-caf"])
@pytest.mark.parametrize(
    ("severity", "enabled"),
    [
        ("critical", True),
        ("high", True),
        ("medium", True),
        ("low", False),
        ("informational", False),
    ],
)
def test_assessment_uses_exact_severity_threshold(
    framework: str, severity: str, enabled: bool
) -> None:
    catalog = _catalog(framework, severity)
    request = _request(catalog)
    result = FrameworkAssessmentRuntime(catalog).assess(request)
    assert len(result.controls) == len(catalog.controls)
    control = result.controls[0]
    assert control.enablement is not None
    assert control.enablement.enabled is enabled
    assert ("control_disabled" in control.limitations) is (not enabled)
    assert control.satisfaction.value == "unknown"
    assert result.execution_authority is False
    assert FrameworkAssessmentRuntime(catalog).assess(request).result_digest == result.result_digest


@pytest.mark.parametrize("severity,override", [("critical", False), ("low", True)])
def test_profile_override_changes_only_assessment_preference(severity: str, override: bool) -> None:
    catalog = _catalog("azure-waf", severity)
    request = _request(catalog, override)
    control = FrameworkAssessmentRuntime(catalog).assess(request).controls[0]
    assert control.enablement is not None
    assert control.enablement.enabled is override
    assert control.enablement.source == "profile_override"
    assert request.profile.applicability[0].enabled is override
    assert request.profile.profile_digest != _request(catalog).profile.profile_digest

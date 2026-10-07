"""Fail-closed Operator projection tests for WAF and CAF assessments."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

import pytest
from fdai_operator_service.framework_assessment_projection import (
    FrameworkAssessmentProjectionConsumer,
    FrameworkAssessmentProjectionError,
    project_framework_assessment,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def _catalog(framework_id: str = "azure-caf") -> dict[str, object]:
    control: dict[str, object] = {
        "control_id": "strategy" if framework_id == "azure-caf" else "RE:01",
        "title": "Strategy",
        "framework_id": framework_id,
        "reference_state": "present",
        "evaluation_status": "not_evaluated",
        "satisfaction": "unknown",
        "evidence_specifications": [
            {
                "requirement_id": "artifact:strategy",
                "kind": "artifact",
                "source_ref": "strategy",
                "freshness_ceiling_seconds": 86_400,
            }
        ],
    }
    if framework_id == "azure-waf":
        control.update(
            {
                "requirements": [],
                "status": "unknown",
                "mapping_status": "mapped",
            }
        )
    return {
        "_revision": DIGEST_A,
        "framework_id": framework_id,
        "framework_version": "2026-08-31",
        "catalog_digest": DIGEST_B,
        "controls": [control],
        "evaluation_source": "not_connected",
    }


def _assessment(framework_id: str = "azure-caf") -> dict[str, object]:
    control_id = "strategy" if framework_id == "azure-caf" else "RE:01"
    return {
        "assessment_id": "assessment-1",
        "mode": "shadow",
        "execution_authority": False,
        "framework_id": framework_id,
        "framework_version": "2026-08-31",
        "catalog_digest": DIGEST_B,
        "profile_id": "profile-1",
        "profile_digest": DIGEST_C,
        "scope_digest": DIGEST_A,
        "evaluated_at": "2026-09-10T01:00:00+00:00",
        "recorded_at": "2026-09-10T01:00:01+00:00",
        "result_digest": "sha256:" + "d" * 64,
        "applicability_profile": [
            {
                "control_id": control_id,
                "status": "applicable",
                "requested_by": "requester@example.com",
                "owner_slot": "strategy-owner",
                "cadence_days": 30,
            }
        ],
        "controls": [
            {
                "control_id": control_id,
                "title": "Strategy",
                "area": "methodology",
                "reference_state": "present",
                "mapping_state": "full",
                "applicability": "applicable",
                "evaluation": "evaluated",
                "satisfaction": "satisfied",
                "owner_slot": "strategy-owner",
                "cadence_days": 30,
                "evidence_complete": True,
                "evidence_refs": ["evidence://strategy"],
                "evidence_digests": [DIGEST_C],
                "limitations": [],
                "requirements": [
                    {
                        "requirement_id": "artifact:strategy",
                        "status": "satisfied",
                        "evidence_refs": ["evidence://strategy"],
                        "evidence_digests": [DIGEST_C],
                        "limitations": [],
                    }
                ],
            }
        ],
        "tradeoffs": [],
        "aggregate_counts": {},
    }


def test_projects_complete_caf_assessment_without_authority() -> None:
    projected = project_framework_assessment(_catalog(), _assessment())

    control = projected["controls"][0]
    assert control["evaluation_status"] == "evaluated"
    assert control["satisfaction"] == "satisfied"
    assert control["execution_authority"] is False
    assert projected["evaluation_source"] == "framework-shadow-assessment"


def test_projects_waf_requirements_and_existing_status_shape() -> None:
    projected = project_framework_assessment(
        _catalog("azure-waf"),
        _assessment("azure-waf"),
    )

    control = projected["controls"][0]
    assert control["mapping_status"] == "mapped"
    assert control["status"] == "satisfied"
    assert control["satisfied_requirement_count"] == 1
    assert control["requirements"][0]["ref"] == "strategy"
    assert control["requirements"][0]["limitations"] == []


def test_waf_requirement_limitations_reach_the_control_detail() -> None:
    assessment = _assessment("azure-waf")
    requirement = assessment["controls"][0]["requirements"][0]
    requirement["status"] = "unknown"
    requirement["limitations"] = ["decisive_evidence_unavailable", "rule_not_activated"]
    assessment["controls"][0]["satisfaction"] = "unknown"

    projected = project_framework_assessment(_catalog("azure-waf"), assessment)

    assert projected["controls"][0]["requirements"][0]["limitations"] == [
        "decisive_evidence_unavailable",
        "rule_not_activated",
    ]


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("execution_authority", True, "no-authority"),
        ("catalog_digest", DIGEST_A, "catalog digest"),
        ("framework_version", "2026-09-01", "version"),
    ],
)
def test_rejects_authority_or_pin_mismatch(
    field: str,
    value: object,
    match: str,
) -> None:
    assessment = _assessment()
    assessment[field] = value

    with pytest.raises(FrameworkAssessmentProjectionError, match=match):
        project_framework_assessment(_catalog(), assessment)


def test_rejects_partial_or_terminally_inconsistent_results() -> None:
    partial = _assessment()
    partial["controls"] = []
    with pytest.raises(FrameworkAssessmentProjectionError, match="exactly cover"):
        project_framework_assessment(_catalog(), partial)

    inconsistent = _assessment()
    control = inconsistent["controls"][0]
    control["evaluation"] = "not_evaluated"
    with pytest.raises(FrameworkAssessmentProjectionError, match="terminal satisfaction"):
        project_framework_assessment(_catalog(), inconsistent)


def test_rejects_out_of_order_assessment() -> None:
    catalog = _catalog()
    catalog["last_evaluated_at"] = "2026-09-10T02:00:00+00:00"

    with pytest.raises(FrameworkAssessmentProjectionError, match="older"):
        project_framework_assessment(catalog, _assessment())


def test_rejects_conflicting_result_at_same_cutoff() -> None:
    catalog = _catalog()
    catalog["last_evaluated_at"] = "2026-09-10T01:00:00+00:00"
    catalog["last_recorded_at"] = "2026-09-10T01:00:01+00:00"

    with pytest.raises(FrameworkAssessmentProjectionError, match="conflicts"):
        project_framework_assessment(catalog, _assessment())


async def test_consumer_routes_framework_to_owned_projection() -> None:
    class Store:
        def __init__(self) -> None:
            self.written: tuple[str, dict[str, object]] | None = None

        async def read_framework_catalog(self, framework_id: str) -> dict[str, object]:
            return _catalog(framework_id)

        async def write_framework_projection(
            self,
            framework_id: str,
            value: Mapping[str, object],
        ) -> None:
            self.written = (framework_id, dict(value))

    store = Store()
    await FrameworkAssessmentProjectionConsumer(store).handle(_assessment())

    assert store.written is not None
    assert store.written[0] == "azure-caf"
    assert store.written[1]["last_assessment_id"] == "assessment-1"


def test_idempotent_redelivery_preserves_projection() -> None:
    assessment = _assessment()
    projected = project_framework_assessment(_catalog(), assessment)

    repeated = project_framework_assessment(deepcopy(projected), assessment)

    assert repeated == projected

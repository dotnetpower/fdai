from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.wara import (
    WaraAssessmentObservationRunner,
    WaraAssessmentRequest,
    WaraAssessmentRuntime,
    WaraEvidenceReceipt,
    WaraScopedResource,
)
from fdai.core.wara.models import WaraEvaluationStatus, WaraSatisfactionStatus
from fdai.delivery.authoritative_framework_projection import _wara_snapshot
from fdai.rule_catalog.schema.framework_catalog import load_framework_catalog
from fdai.rule_catalog.schema.wara_assessment import (
    WaraRecommendationCrosswalk,
    load_wara_assessment_catalog,
)
from fdai.rule_catalog.schema.wara_evaluator_binding import load_wara_evaluator_bindings
from fdai.shared.providers.wara_assessment import WaraObservationError

ROOT = Path(__file__).resolve().parents[5]
ASSESSMENT = ROOT / "rule-catalog/collected/wara-aprl/assessment"
AT = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def catalogs():
    catalog, queries = load_wara_assessment_catalog(
        ASSESSMENT / "crosswalk.json", ASSESSMENT / "queries.json"
    )
    bindings = load_wara_evaluator_bindings(
        ASSESSMENT / "evaluator-bindings.json", catalog=catalog, queries=queries
    )
    rule_ids = {
        binding["aprl_guid"]
        for binding in json.loads((ASSESSMENT / "rule-bindings.json").read_text())["bindings"]
    }
    return catalog, bindings, rule_ids


def _case(catalogs, *, automated: bool = False):
    catalog, bindings, rule_ids = catalogs
    bound_ids = {binding.aprl_guid for binding in bindings.bindings}
    record = next(
        item
        for item in catalog.recommendations
        if item.automation_available
        and (item.aprl_guid in bound_ids) == automated
        and item.aprl_guid not in rule_ids
    )
    return record, _request(catalog, bindings, record)


def _request(catalog, bindings, record):
    provider_type = record.applicability.provider_resource_types[0]
    resource_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000000"
        if provider_type == "microsoft.resources/subscriptions"
        else "resource:fallback-target"
    )
    return WaraAssessmentRequest(
        assessment_id=f"fallback:{record.aprl_guid}",
        framework_revision=catalog.source_revision,
        crosswalk_digest=catalog.crosswalk_digest,
        ontology_release="ontology-release-1",
        inventory_generation="inventory-generation-1",
        workload_id="workload:fallback",
        resources=(
            WaraScopedResource(resource_id, provider_type, workload_tags=record.workload_tags),
        ),
        evaluated_at=AT,
        recorded_at=AT,
        evaluator_bindings_digest=bindings.overlay_digest,
    )


def _manual(record, request):
    requirement = record.manual_evidence
    assert requirement is not None
    return WaraEvidenceReceipt(
        recommendation_id=record.aprl_guid,
        evidence_ref="evidence:attributed-manual-review",
        evidence_kind=requirement.kind,
        producer=requirement.authoritative_producer,
        scope_digest=request.scope_digest,
        source_revision=request.framework_revision,
        inventory_generation=request.inventory_generation,
        observed_at=AT - timedelta(hours=1),
        recorded_at=AT,
        evidence_digest="sha256:" + "a" * 64,
        freshness_ceiling_seconds=requirement.freshness_ceiling_seconds,
        complete=True,
        truncated=False,
        conflicting=False,
        synthetic=False,
        provider_error=None,
        outcome=WaraSatisfactionStatus.SATISFIED,
    )


def _control(runtime, record, request, evidence):
    result = runtime.assess(replace(request, evidence=tuple(evidence)))
    return next(
        control for control in result.controls if control.recommendation_id == record.aprl_guid
    )


def test_every_automatically_unresolved_control_has_a_real_manual_fallback(catalogs) -> None:
    catalog, bindings, rule_ids = catalogs
    runtime = WaraAssessmentRuntime(catalog, bindings)
    bound_ids = {binding.aprl_guid for binding in bindings.bindings} | rule_ids
    unresolved = [
        item
        for item in catalog.recommendations
        if item.automation_available and item.aprl_guid not in bound_ids
    ]
    assert unresolved
    for record in unresolved:
        assert record.manual_evidence is not None
        assert record.manual_evidence.role == "fallback"
        request = _request(catalog, bindings, record)
        control = _control(runtime, record, request, [_manual(record, request)])
        assert control.evaluation is WaraEvaluationStatus.EVALUATED, record.aprl_guid
        assert control.satisfaction is WaraSatisfactionStatus.SATISFIED, record.aprl_guid
        assert "manual_evidence_fallback" in control.limitations
        assert "automatic_evaluation_unavailable" in control.limitations
        with pytest.raises(ValueError, match="no admitted read-only query"):
            runtime.build_read_plan(record, request)


@pytest.mark.parametrize(
    "changes",
    [
        {"complete": False},
        {"truncated": True},
        {"conflicting": True},
        {"synthetic": True},
        {"provider_error": "source_unavailable"},
        {"producer": "another-owner"},
        {"evidence_kind": "another-kind"},
        {"scope_digest": "another-scope"},
        {"source_revision": "another-source"},
        {"inventory_generation": "another-generation"},
        {"freshness_ceiling_seconds": 1},
        {"observed_at": AT - timedelta(days=366)},
        {"observed_at": AT + timedelta(seconds=1), "recorded_at": AT + timedelta(seconds=1)},
    ],
)
def test_invalid_manual_fallback_does_not_unblock_automatic_evaluation(catalogs, changes) -> None:
    catalog, bindings, _ = catalogs
    record, request = _case(catalogs)
    receipt = replace(_manual(record, request), **changes)
    control = _control(WaraAssessmentRuntime(catalog, bindings), record, request, [receipt])
    assert control.evaluation is WaraEvaluationStatus.BLOCKED
    assert control.satisfaction is WaraSatisfactionStatus.UNKNOWN
    assert "manual_evidence_fallback" not in control.limitations


def test_automatic_receipts_are_not_intercepted_by_the_manual_contract(catalogs) -> None:
    catalog, bindings, _ = catalogs
    record, request = _case(catalogs, automated=True)
    review = record.query_review
    assert review is not None
    binding = bindings.resolve(record.aprl_guid, review.body_digest)
    assert binding is not None
    manual = _manual(record, request)
    automatic = replace(
        manual,
        evidence_ref="evidence:exact-automatic-observation",
        evidence_kind="provider_observation",
        producer=binding.evaluator_ref,
        evidence_digest="sha256:" + "b" * 64,
        freshness_ceiling_seconds=review.evidence_freshness_ceiling_seconds,
    )
    runtime = WaraAssessmentRuntime(catalog, bindings)
    control = _control(runtime, record, request, [automatic])
    assert control.satisfaction is WaraSatisfactionStatus.SATISFIED
    assert "manual_evidence_fallback" not in control.limitations
    conflict = _control(
        runtime,
        record,
        request,
        [automatic, replace(manual, outcome=WaraSatisfactionStatus.FAILED)],
    )
    assert conflict.satisfaction is WaraSatisfactionStatus.UNKNOWN
    assert "evidence_conflict" in conflict.limitations
    assert "manual_evidence_fallback" in conflict.limitations


def test_a_provider_receipt_cannot_masquerade_as_manual_evidence(catalogs) -> None:
    catalog, bindings, _ = catalogs
    record, request = _case(catalogs)
    receipt = replace(_manual(record, request), evidence_kind="provider_observation")
    control = _control(WaraAssessmentRuntime(catalog, bindings), record, request, [receipt])
    assert control.evaluation is WaraEvaluationStatus.BLOCKED
    assert control.satisfaction is WaraSatisfactionStatus.UNKNOWN


@pytest.mark.parametrize("change", ["missing", "required", "provider_observation"])
def test_fallback_contract_cannot_change_automation_or_intercept_provider_receipts(
    catalogs, change: str
) -> None:
    record, _ = _case(catalogs)
    material = record.model_dump(mode="json")
    if change == "missing":
        material["manual_evidence"] = None
    elif change == "required":
        material["manual_evidence"]["role"] = "required"
    else:
        material["manual_evidence"]["kind"] = "provider_observation"
    with pytest.raises(ValueError, match="manual evidence"):
        WaraRecommendationCrosswalk.model_validate(material)


async def test_manual_fallback_never_dispatches_the_blocked_query(catalogs) -> None:
    catalog, bindings, _ = catalogs
    record, request = _case(catalogs)
    runtime = WaraAssessmentRuntime(catalog, bindings)

    class Provider:
        def __init__(self) -> None:
            self.guids: list[str] = []

        async def observe(self, plan):
            self.guids.append(plan.recommendation_id)
            raise WaraObservationError("test observation unavailable")

    provider = Provider()
    request = replace(request, evidence=(_manual(record, request),))
    collection = await WaraAssessmentObservationRunner(runtime=runtime, provider=provider).collect(
        request
    )
    assert record.aprl_guid not in provider.guids
    control = _control(runtime, record, collection.request, collection.request.evidence)
    assert control.satisfaction is WaraSatisfactionStatus.SATISFIED


def test_projection_distinguishes_native_requirements_from_optional_fallback(catalogs) -> None:
    catalog, bindings, _ = catalogs
    framework = load_framework_catalog(
        ROOT / "rule-catalog/collected/wara-aprl", best_practices=(), objective_refs=frozenset()
    )[0]
    snapshot = _wara_snapshot(framework, catalog, bindings)
    active = [control for control in snapshot["controls"] if control["lifecycle"] == "active"]
    assert len(active) == 393
    for control in active:
        requirement = control["manual_evidence"]
        assert requirement is not None
        if control["automation_available"]:
            assert requirement["role"] == "fallback"
            assert "manual_evidence_required" not in control["limitations"]
            assert "manual_evidence_fallback_available" in control["limitations"]
        else:
            assert requirement["role"] == "required"
            assert control["limitations"] == ["manual_evidence_required"]

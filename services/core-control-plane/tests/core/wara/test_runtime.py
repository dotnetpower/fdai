from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.wara import (
    WaraAssessmentObservationRunner,
    WaraAssessmentRequest,
    WaraAssessmentRuntime,
    WaraAssessmentService,
    WaraEvidenceReceipt,
    WaraScopedResource,
    build_wara_read_plan,
    replay_wara_assessment,
)
from fdai.core.wara.runtime import (
    WARA_ASSESSMENT_TOPIC,
    WaraApplicabilityStatus,
    WaraEvaluationStatus,
    WaraSatisfactionStatus,
)
from fdai.rule_catalog.schema.framework_catalog import load_framework_catalog
from fdai.rule_catalog.schema.wara_assessment import (
    ResourceTypeDisposition,
    WaraDisposition,
    load_wara_assessment_catalog,
)
from fdai.rule_catalog.schema.wara_evaluator_binding import load_wara_evaluator_bindings
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.wara_assessment import (
    WaraObservationError,
    WaraObservationReceipt,
    WaraReadPlan,
)

ROOT = Path(__file__).resolve().parents[5]
CATALOG_ROOT = ROOT / "rule-catalog"
EVALUATOR_BINDINGS = CATALOG_ROOT / "collected/wara-aprl/assessment/evaluator-bindings.json"
AT = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


def _runtime_and_record():
    framework = load_framework_catalog(
        CATALOG_ROOT / "collected/wara-aprl",
        best_practices=(),
        objective_refs=frozenset(),
    )[0]
    catalog, _ = load_wara_assessment_catalog(
        CATALOG_ROOT / "collected/wara-aprl/assessment/crosswalk.json",
        CATALOG_ROOT / "collected/wara-aprl/assessment/queries.json",
        framework=framework,
        framework_path=CATALOG_ROOT / "collected/wara-aprl/azure-wara.json",
    )
    record = next(
        item
        for item in catalog.recommendations
        if item.disposition is WaraDisposition.MANUAL_EVIDENCE
        and item.applicability.disposition is ResourceTypeDisposition.CANONICAL
        and not item.workload_tags
    )
    return WaraAssessmentRuntime(catalog), catalog, record


def _runtime_and_bound_record():
    framework = load_framework_catalog(
        CATALOG_ROOT / "collected/wara-aprl",
        best_practices=(),
        objective_refs=frozenset(),
    )[0]
    catalog, queries = load_wara_assessment_catalog(
        CATALOG_ROOT / "collected/wara-aprl/assessment/crosswalk.json",
        CATALOG_ROOT / "collected/wara-aprl/assessment/queries.json",
        framework=framework,
        framework_path=CATALOG_ROOT / "collected/wara-aprl/azure-wara.json",
    )
    bindings = load_wara_evaluator_bindings(
        EVALUATOR_BINDINGS,
        catalog=catalog,
        queries=queries,
    )
    record = next(
        item
        for item in catalog.recommendations
        if item.query_review is not None
        and bindings.resolve(item.aprl_guid, item.query_review.body_digest) is not None
    )
    return WaraAssessmentRuntime(catalog, bindings), catalog, bindings, record


def _request(record):
    resource = WaraScopedResource(
        resource_id="resource:representative",
        provider_resource_type=record.provider_resource_type,
    )
    return WaraAssessmentRequest(
        assessment_id="assessment-1",
        framework_revision="1f421a90c157bc8894b3a47b05ba08b8650a0bd5",
        crosswalk_digest="placeholder",
        ontology_release="ontology-release-1",
        inventory_generation="inventory-generation-1",
        workload_id="workload:representative",
        resources=(resource,),
        evaluated_at=AT,
        recorded_at=AT,
    )


def _admitted_evidence(request, record):
    return WaraEvidenceReceipt(
        recommendation_id=record.aprl_guid,
        evidence_ref="evidence:manual-review-1",
        evidence_kind=record.manual_evidence.kind,
        producer=record.manual_evidence.authoritative_producer,
        scope_digest=request.scope_digest,
        source_revision=request.framework_revision,
        inventory_generation=request.inventory_generation,
        observed_at=AT - timedelta(hours=1),
        recorded_at=AT - timedelta(minutes=59),
        evidence_digest="sha256:" + "a" * 64,
        freshness_ceiling_seconds=record.manual_evidence.freshness_ceiling_seconds,
        complete=True,
        truncated=False,
        conflicting=False,
        synthetic=False,
        provider_error=None,
        outcome=WaraSatisfactionStatus.SATISFIED,
    )


def test_shadow_assessment_is_replayable_and_has_no_execution_authority() -> None:
    runtime, catalog, record = _runtime_and_record()
    base = replace(_request(record), crosswalk_digest=catalog.crosswalk_digest)
    request = replace(base, evidence=(_admitted_evidence(base, record),))

    first = runtime.assess(request)
    replayed = replay_wara_assessment(runtime, request, first.result_digest)
    result = next(item for item in first.controls if item.recommendation_id == record.aprl_guid)

    assert replayed == first
    assert first.mode == "shadow"
    assert first.execution_authority is False
    assert len(first.controls) == 393
    assert result.applicability is WaraApplicabilityStatus.APPLICABLE
    assert result.evaluation is WaraEvaluationStatus.EVALUATED
    assert result.satisfaction is WaraSatisfactionStatus.SATISFIED


@pytest.mark.parametrize(
    ("changes", "limitation"),
    [
        ({"complete": False}, "evidence_unavailable_or_inadmissible"),
        ({"truncated": True}, "evidence_unavailable_or_inadmissible"),
        ({"conflicting": True}, "evidence_unavailable_or_inadmissible"),
        ({"synthetic": True}, "evidence_unavailable_or_inadmissible"),
        ({"provider_error": "provider_unavailable"}, "evidence_unavailable_or_inadmissible"),
        (
            {"observed_at": AT - timedelta(days=366), "recorded_at": AT - timedelta(days=366)},
            "evidence_unavailable_or_inadmissible",
        ),
    ],
)
def test_incomplete_stale_failed_or_synthetic_evidence_stays_unknown(
    changes: dict[str, object],
    limitation: str,
) -> None:
    runtime, catalog, record = _runtime_and_record()
    base = replace(_request(record), crosswalk_digest=catalog.crosswalk_digest)
    evidence = replace(_admitted_evidence(base, record), **changes)
    result = runtime.assess(replace(base, evidence=(evidence,)))
    control = next(item for item in result.controls if item.recommendation_id == record.aprl_guid)

    assert control.evaluation is WaraEvaluationStatus.NOT_EVALUATED
    assert control.satisfaction is WaraSatisfactionStatus.UNKNOWN
    assert limitation in control.limitations


def test_missing_resource_never_becomes_not_applicable() -> None:
    runtime, catalog, record = _runtime_and_record()
    request = replace(
        _request(record),
        crosswalk_digest=catalog.crosswalk_digest,
        resources=(
            WaraScopedResource(
                resource_id="resource:other",
                provider_resource_type="Microsoft.Resources/resourceGroups",
            ),
        ),
    )

    control = next(
        item
        for item in runtime.assess(request).controls
        if item.recommendation_id == record.aprl_guid
    )
    assert control.applicability is WaraApplicabilityStatus.UNKNOWN
    assert control.satisfaction is WaraSatisfactionStatus.UNKNOWN


def test_safe_external_query_normalizes_to_exact_bounded_read_plan() -> None:
    runtime, catalog, bindings, record = _runtime_and_bound_record()
    request = replace(_request(record), crosswalk_digest=catalog.crosswalk_digest)

    with pytest.raises(ValueError, match="no admitted"):
        build_wara_read_plan(record, request)
    with pytest.raises(ValueError, match="evaluator bindings digest mismatch"):
        runtime.assess(request)

    pinned_request = replace(
        request,
        evaluator_bindings_digest=bindings.overlay_digest,
    )
    plan = runtime.build_read_plan(record, pinned_request)

    assert plan.resource_ids == ("resource:representative",)
    assert plan.maximum_rows == 500
    assert plan.timeout_seconds == 30
    assert plan.evidence_freshness_ceiling_seconds == 86_400
    assert plan.query_digest == record.query_review.body_digest
    assert plan.evaluator_bindings_digest == bindings.overlay_digest
    assert record.query_review.evaluator_ref is None
    assert record.query_review.blocked_reasons == ("missing_exact_evaluator",)


def test_unknown_applicability_cannot_become_satisfied() -> None:
    runtime, catalog, record = _runtime_and_record()
    base = replace(
        _request(record),
        crosswalk_digest=catalog.crosswalk_digest,
        resources=(
            WaraScopedResource(
                resource_id="resource:other",
                provider_resource_type="Microsoft.Resources/resourceGroups",
            ),
        ),
    )
    evidence = replace(
        _admitted_evidence(base, record),
        scope_digest=base.scope_digest,
    )

    control = next(
        item
        for item in runtime.assess(replace(base, evidence=(evidence,))).controls
        if item.recommendation_id == record.aprl_guid
    )
    assert control.applicability is WaraApplicabilityStatus.UNKNOWN
    assert control.evaluation is WaraEvaluationStatus.NOT_EVALUATED
    assert control.satisfaction is WaraSatisfactionStatus.UNKNOWN


def test_catalog_evidence_contract_and_future_time_are_enforced() -> None:
    runtime, catalog, record = _runtime_and_record()
    base = replace(_request(record), crosswalk_digest=catalog.crosswalk_digest)
    evidence = _admitted_evidence(base, record)

    for invalid in (
        replace(evidence, evidence_kind="wrong-kind"),
        replace(evidence, producer="wrong-producer"),
        replace(evidence, freshness_ceiling_seconds=evidence.freshness_ceiling_seconds + 1),
        replace(
            evidence, observed_at=AT + timedelta(seconds=1), recorded_at=AT + timedelta(seconds=1)
        ),
    ):
        control = next(
            item
            for item in runtime.assess(replace(base, evidence=(invalid,))).controls
            if item.recommendation_id == record.aprl_guid
        )
        assert control.evaluation is WaraEvaluationStatus.NOT_EVALUATED
        assert control.satisfaction is WaraSatisfactionStatus.UNKNOWN


def test_result_digest_binds_admitted_evidence_content() -> None:
    runtime, catalog, record = _runtime_and_record()
    base = replace(_request(record), crosswalk_digest=catalog.crosswalk_digest)
    evidence = _admitted_evidence(base, record)
    first = runtime.assess(replace(base, evidence=(evidence,)))
    changed = runtime.assess(
        replace(
            base,
            evidence=(replace(evidence, evidence_digest="sha256:" + "b" * 64),),
        )
    )

    assert first.result_digest != changed.result_digest


def test_automated_evidence_uses_catalog_freshness_ceiling() -> None:
    runtime, catalog, bindings, admitted_record = _runtime_and_bound_record()
    review = admitted_record.query_review
    assert review is not None
    binding = bindings.resolve(admitted_record.aprl_guid, review.body_digest)
    assert binding is not None
    base = replace(
        _request(admitted_record),
        crosswalk_digest=catalog.crosswalk_digest,
        evaluator_bindings_digest=bindings.overlay_digest,
    )
    evidence = WaraEvidenceReceipt(
        recommendation_id=admitted_record.aprl_guid,
        evidence_ref="evidence:provider-1",
        evidence_kind="provider_observation",
        producer=binding.evaluator_ref,
        scope_digest=base.scope_digest,
        source_revision=base.framework_revision,
        inventory_generation=base.inventory_generation,
        observed_at=AT - timedelta(hours=1),
        recorded_at=AT - timedelta(minutes=59),
        evidence_digest="sha256:" + "c" * 64,
        freshness_ceiling_seconds=review.evidence_freshness_ceiling_seconds + 1,
        complete=True,
        truncated=False,
        conflicting=False,
        synthetic=False,
        provider_error=None,
        outcome=WaraSatisfactionStatus.SATISFIED,
    )

    rejected = runtime.assess(replace(base, evidence=(evidence,)))
    rejected_control = next(
        item for item in rejected.controls if item.recommendation_id == admitted_record.aprl_guid
    )
    accepted = runtime.assess(
        replace(
            base,
            evidence=(
                replace(
                    evidence,
                    freshness_ceiling_seconds=review.evidence_freshness_ceiling_seconds,
                ),
            ),
        )
    )
    accepted_control = next(
        item for item in accepted.controls if item.recommendation_id == admitted_record.aprl_guid
    )

    assert rejected_control.satisfaction is WaraSatisfactionStatus.UNKNOWN
    assert accepted_control.satisfaction is WaraSatisfactionStatus.SATISFIED


@pytest.mark.asyncio
async def test_service_publishes_shadow_finding_and_audit_only() -> None:
    runtime, catalog, record = _runtime_and_record()
    request = replace(_request(record), crosswalk_digest=catalog.crosswalk_digest)
    state_store = InMemoryStateStore()
    event_bus = InMemoryEventBus()

    result = await WaraAssessmentService(runtime, state_store, event_bus).assess(request)
    events = [item async for item in event_bus.subscribe(WARA_ASSESSMENT_TOPIC, "test")]
    audit = tuple(state_store.audit_entries)

    assert len(events) == 1
    assert events[0].payload["result_digest"] == result.result_digest
    assert events[0].payload["execution_authority"] is False
    assert len(audit) == 1
    assert audit[0]["entry"]["type"] == "wara_shadow_assessment"
    assert "remediation" not in events[0].payload


class _ObservationProvider:
    def __init__(
        self,
        *,
        unavailable: bool = False,
        observed_at: datetime = AT,
    ) -> None:
        self.unavailable = unavailable
        self.observed_at = observed_at
        self.plans: list[WaraReadPlan] = []

    async def observe(self, plan: WaraReadPlan) -> WaraObservationReceipt:
        self.plans.append(plan)
        if self.unavailable:
            raise WaraObservationError("provider unavailable")
        return WaraObservationReceipt(
            recommendation_id=plan.recommendation_id,
            query_digest=plan.query_digest,
            evaluator_ref=plan.evaluator_ref,
            evaluator_bindings_digest=plan.evaluator_bindings_digest,
            workload_id=plan.workload_id,
            resource_ids=plan.resource_ids,
            inventory_generation=plan.inventory_generation,
            observed_at=self.observed_at,
            recorded_at=self.observed_at,
            evidence_digest="sha256:" + "d" * 64,
            complete=True,
            truncated=False,
            conflicting=False,
            synthetic=False,
            satisfied=True,
        )


async def test_service_collects_exact_observations_before_assessment() -> None:
    runtime, catalog, bindings, record = _runtime_and_bound_record()
    request = replace(
        _request(record),
        crosswalk_digest=catalog.crosswalk_digest,
        evaluator_bindings_digest=bindings.overlay_digest,
    )
    state_store = InMemoryStateStore()
    event_bus = InMemoryEventBus()
    provider = _ObservationProvider(observed_at=AT + timedelta(milliseconds=1))
    runner = WaraAssessmentObservationRunner(runtime=runtime, provider=provider)

    result = await WaraAssessmentService(
        runtime,
        state_store,
        event_bus,
        observation_runner=runner,
    ).assess(request)
    control = next(item for item in result.controls if item.recommendation_id == record.aprl_guid)
    audit_entry = state_store.audit_entries[0]["entry"]

    assert control.satisfaction is WaraSatisfactionStatus.SATISFIED
    assert result.evaluated_at == AT + timedelta(milliseconds=1)
    assert result.recorded_at == AT + timedelta(milliseconds=1)
    assert len(provider.plans) == 1
    assert audit_entry["observation_attempts"] == [
        {
            "recommendation_id": record.aprl_guid,
            "status": "observed",
            "reason": None,
        }
    ]


async def test_service_records_provider_unavailability_without_claiming_satisfaction() -> None:
    runtime, catalog, bindings, record = _runtime_and_bound_record()
    request = replace(
        _request(record),
        crosswalk_digest=catalog.crosswalk_digest,
        evaluator_bindings_digest=bindings.overlay_digest,
    )
    state_store = InMemoryStateStore()
    provider = _ObservationProvider(unavailable=True)
    runner = WaraAssessmentObservationRunner(runtime=runtime, provider=provider)

    result = await WaraAssessmentService(
        runtime,
        state_store,
        InMemoryEventBus(),
        observation_runner=runner,
    ).assess(request)
    control = next(item for item in result.controls if item.recommendation_id == record.aprl_guid)
    audit_entry = state_store.audit_entries[0]["entry"]

    assert control.satisfaction is WaraSatisfactionStatus.UNKNOWN
    assert audit_entry["observation_attempts"][0]["status"] == "unavailable"
    assert audit_entry["observation_attempts"][0]["reason"] == ("provider_observation_unavailable")


async def test_caller_evidence_cannot_advance_its_own_admission_cutoff() -> None:
    runtime, catalog, bindings, record = _runtime_and_bound_record()
    request = replace(
        _request(record),
        crosswalk_digest=catalog.crosswalk_digest,
        evaluator_bindings_digest=bindings.overlay_digest,
    )
    plan = runtime.build_read_plan(record, request)
    future = WaraEvidenceReceipt(
        recommendation_id=record.aprl_guid,
        evidence_ref="evidence:future-caller",
        evidence_kind="provider_observation",
        producer=plan.evaluator_ref,
        scope_digest=request.scope_digest,
        source_revision=request.framework_revision,
        inventory_generation=request.inventory_generation,
        observed_at=AT + timedelta(days=1),
        recorded_at=AT + timedelta(days=1),
        evidence_digest="sha256:" + "e" * 64,
        freshness_ceiling_seconds=plan.evidence_freshness_ceiling_seconds,
        complete=True,
        truncated=False,
        conflicting=False,
        synthetic=False,
        provider_error=None,
        outcome=WaraSatisfactionStatus.SATISFIED,
    )
    runner = WaraAssessmentObservationRunner(
        runtime=runtime,
        provider=_ObservationProvider(unavailable=True),
    )

    collection = await runner.collect(replace(request, evidence=(future,)))
    result = runtime.assess(collection.request)
    control = next(item for item in result.controls if item.recommendation_id == record.aprl_guid)

    assert collection.request.evaluated_at == AT
    assert collection.request.recorded_at == AT
    assert control.satisfaction is WaraSatisfactionStatus.UNKNOWN

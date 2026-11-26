from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.wara import (
    WaraAssessmentObservationRunner,
    WaraAssessmentRequest,
    WaraAssessmentRuntime,
    WaraScopedResource,
    replay_wara_assessment,
)
from fdai.rule_catalog.schema.framework_catalog import load_framework_catalog
from fdai.rule_catalog.schema.wara_assessment import load_wara_assessment_catalog
from fdai.rule_catalog.schema.wara_evaluator_binding import load_wara_evaluator_bindings
from fdai.shared.providers.wara_assessment import (
    WaraObservationError,
    WaraObservationReceipt,
    WaraReadPlan,
)
from fdai_service_contracts.control_enablement_profile import ControlEnablementProfile

ROOT = Path(__file__).resolve().parents[5] / "rule-catalog"
ASSESSMENT = ROOT / "collected/wara-aprl/assessment"
NOW = datetime(2026, 10, 30, tzinfo=UTC)


def _context():
    framework = load_framework_catalog(
        ROOT / "collected/wara-aprl", best_practices=(), objective_refs=frozenset()
    )[0]
    catalog, queries = load_wara_assessment_catalog(
        ASSESSMENT / "crosswalk.json",
        ASSESSMENT / "queries.json",
        framework=framework,
        framework_path=ROOT / "collected/wara-aprl/azure-wara.json",
    )
    bindings = load_wara_evaluator_bindings(
        ASSESSMENT / "evaluator-bindings.json", catalog=catalog, queries=queries
    )
    record = next(
        item
        for item in catalog.recommendations
        if item.impact == "Low"
        and item.query_review is not None
        and bindings.resolve(item.aprl_guid, item.query_review.body_digest) is not None
    )
    request = WaraAssessmentRequest(
        assessment_id="assessment:example",
        framework_revision=catalog.source_revision,
        crosswalk_digest=catalog.crosswalk_digest,
        ontology_release="ontology:example",
        inventory_generation="inventory:example",
        workload_id="workload:example",
        resources=(
            WaraScopedResource(
                resource_id=(
                    "/subscriptions/00000000-0000-0000-0000-000000000000"
                    "/resourceGroups/example/providers/"
                    + record.provider_resource_type
                    + "/example"
                ),
                provider_resource_type=record.provider_resource_type,
                workload_tags=record.workload_tags,
            ),
        ),
        evaluated_at=NOW,
        recorded_at=NOW,
        evaluator_bindings_digest=bindings.overlay_digest,
    )
    return WaraAssessmentRuntime(catalog, bindings), catalog, record, request


def _enabled(request: WaraAssessmentRequest, control_id: str) -> WaraAssessmentRequest:
    material = {
        "schema_version": "1.0.0",
        "framework_id": "azure-wara",
        "source_revision": request.framework_revision,
        "scope_digest": request.scope_digest,
        "reviewed_by": "framework-reviewer",
        "reviewed_at": "2026-10-30T00:00:00Z",
        "overrides": [{"control_id": control_id, "enabled": True}],
    }
    profile = ControlEnablementProfile.model_validate(
        {**material, "profile_digest": ControlEnablementProfile.digest_material(material)}
    )
    return replace(request, enablement_profile=profile)


def test_low_control_stays_visible_unknown_and_disabled() -> None:
    runtime, catalog, record, request = _context()
    result = runtime.assess(request)
    assert len(result.controls) == len(catalog.recommendations) == 393
    selected = next(item for item in result.controls if item.recommendation_id == record.aprl_guid)
    assert selected.enablement is not None
    assert selected.enablement.enabled is False
    assert selected.satisfaction.value == "unknown"
    assert selected.evaluation.value == "not_evaluated"
    assert selected.limitations == ("control_disabled",)
    assert replay_wara_assessment(runtime, request, result.result_digest) == result


def test_reviewed_wara_override_is_bound_into_replay() -> None:
    runtime, _, record, request = _context()
    enabled_request = _enabled(request, record.aprl_guid)
    result = runtime.assess(enabled_request)
    selected = next(item for item in result.controls if item.recommendation_id == record.aprl_guid)
    assert selected.enablement is not None
    assert selected.enablement.enabled is True
    assert selected.enablement.source == "profile_override"
    assert "control_disabled" not in selected.limitations
    assert result.execution_authority is False
    assert result.result_digest != runtime.assess(request).result_digest
    assert replay_wara_assessment(runtime, enabled_request, result.result_digest) == result


class _UnavailableProvider:
    def __init__(self) -> None:
        self.plans: list[WaraReadPlan] = []

    async def observe(self, plan: WaraReadPlan) -> WaraObservationReceipt:
        self.plans.append(plan)
        raise WaraObservationError("provider_unavailable")


async def test_disabled_wara_control_does_not_dispatch_its_provider_query() -> None:
    runtime, _, record, request = _context()
    provider = _UnavailableProvider()
    await WaraAssessmentObservationRunner(runtime=runtime, provider=provider).collect(request)
    assert record.aprl_guid not in {plan.recommendation_id for plan in provider.plans}


async def test_invalid_override_binding_fails_before_any_provider_query() -> None:
    runtime, _, record, request = _context()
    enabled_request = _enabled(request, record.aprl_guid)
    provider = _UnavailableProvider()
    with pytest.raises(ValueError, match="binding mismatch"):
        await WaraAssessmentObservationRunner(runtime=runtime, provider=provider).collect(
            replace(enabled_request, workload_id="workload:different")
        )
    assert provider.plans == []

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.impact_analysis import ChangeAssessmentService, ImpactAnalyzer
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)


class _Store:
    async def traverse(self, **_kwargs: object) -> OntologyGraphSnapshot:
        return OntologyGraphSnapshot(
            objects=(
                OntologyObjectRecord("resource-a", "Resource", {"id": "resource-a"}),
                OntologyObjectRecord("workload-a", "Workload", {"id": "workload-a"}),
                OntologyObjectRecord("service-a", "BusinessService", {"id": "service-a"}),
                OntologyObjectRecord("slo-a", "ServiceObjective", {"id": "slo-a"}),
            ),
            links=(
                OntologyLinkRecord("workload_runs_on", "workload-a", "resource-a"),
                OntologyLinkRecord("implemented_by", "service-a", "workload-a"),
                OntologyLinkRecord("service_has_service_objective", "service-a", "slo-a"),
            ),
        )


def _change(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "change-1",
        "correlation_id": "correlation-1",
        "target_ref": "resource-a",
        "occurred_at": datetime(2026, 8, 4, tzinfo=UTC).isoformat(),
        "intent_kind": "planned",
        "desired_state_digest": "sha256:desired",
        "plan_receipt_ref": "plan:1",
    }
    value.update(overrides)
    return value


async def test_complete_planned_change_is_eligible_for_later_gates() -> None:
    service = ChangeAssessmentService(analyzer=ImpactAnalyzer(store=_Store()))
    first = await service.assess(_change(), graph_fresh=True)
    second = await service.assess(_change(), graph_fresh=True)

    assert not first.review_required
    assert first.affected_set.all_resource_ids == ("resource-a", "workload-a")
    assert first.evidence_digest == second.evidence_digest


async def test_stale_graph_and_conflicts_require_review() -> None:
    service = ChangeAssessmentService(analyzer=ImpactAnalyzer(store=_Store()))
    assessment = await service.assess(
        _change(),
        graph_fresh=False,
        unresolved_conflicts=("concurrent_change",),
    )

    assert assessment.review_required
    assert assessment.reasons == ("concurrent_change", "graph_stale")


async def test_missing_plan_evidence_requires_review() -> None:
    service = ChangeAssessmentService(analyzer=ImpactAnalyzer(store=_Store()))
    assessment = await service.assess(
        _change(desired_state_digest="", plan_receipt_ref=""),
        graph_fresh=True,
    )

    assert assessment.review_required
    assert assessment.reasons == (
        "desired_state_digest_missing",
        "plan_receipt_missing",
    )


async def test_affected_resource_cap_requires_review() -> None:
    service = ChangeAssessmentService(
        analyzer=ImpactAnalyzer(store=_Store()),
        max_affected_resources=1,
    )
    assessment = await service.assess(_change(), graph_fresh=True)

    assert assessment.review_required
    assert assessment.reasons == ("affected_resource_cap_exceeded",)

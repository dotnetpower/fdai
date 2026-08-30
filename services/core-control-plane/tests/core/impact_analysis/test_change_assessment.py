from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.impact_analysis import (
    ChangeAssessmentService,
    ChangeGraphEvidenceReceipt,
    GraphEvidenceReleaseState,
    ImpactAnalyzer,
    change_graph_evidence_from_snapshot,
)
from fdai.core.ontology_platform.graph_evidence_refresh import GraphEvidenceFreshness
from fdai.core.operational_context import (
    OperationalContextEvidenceLink,
    OperationalContextSnapshot,
)
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
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


def _receipt(**overrides: object) -> ChangeGraphEvidenceReceipt:
    value: dict[str, object] = {
        "graph_revision": "graph-revision-1",
        "freshness": GraphEvidenceFreshness.CURRENT,
        "release_state": GraphEvidenceReleaseState.ALIGNED,
        "authenticated": True,
        "truncated": False,
        "conflict_reasons": (),
    }
    value.update(overrides)
    return ChangeGraphEvidenceReceipt(**value)


def _snapshot(
    *,
    ontology_release: str = "sha256:release-1",
    stale_sources: tuple[str, ...] = (),
    conflicts: tuple[str, ...] = (),
    graph_source_complete: bool = True,
    graph_source_generation: str | None = "inventory-generation-1",
) -> OperationalContextSnapshot:
    state_fact = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision="inventory-revision-1",
        effective_at=datetime(2026, 8, 4, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 4, tzinfo=UTC),
        evidence_cutoff=datetime(2026, 8, 4, tzinfo=UTC),
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("inventory:evidence-1",),
    )
    observation = LinkObservationMetadata(
        state_fact=state_fact,
        verification_method="provider-readback",
        verified=True,
        verifier_identity="inventory-verifier",
        verifier_revision="verifier-revision-1",
        verification_receipt_ref="inventory:verification-1",
    )
    return OperationalContextSnapshot(
        snapshot_id="snapshot-1",
        target_resource_id="resource-a",
        cutoff=datetime(2026, 8, 4, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 4, tzinfo=UTC),
        catalog_versions=(("ontology", ontology_release),),
        service_ids=("service-a",),
        workload_ids=("workload-a",),
        objective_ids=("slo-a",),
        service_objective_ids=("slo-a",),
        recovery_objective_ids=(),
        cost_objective_ids=(),
        constraint_ids=(),
        ownership_ids=(),
        dependency_ids=("workload-a",),
        source_freshness=(),
        evidence_links=(
            OperationalContextEvidenceLink(
                link_type="workload_runs_on",
                from_id="workload-a",
                to_id="resource-a",
                observation_metadata=observation,
            ),
        ),
        evidence_paths=(),
        temporal_exclusions=(),
        stale_sources=stale_sources,
        conflicts=conflicts,
        graph_source_complete=graph_source_complete,
        graph_source_generation=graph_source_generation,
        autonomy_ceiling=(
            Autonomy.SHADOW_ONLY
            if conflicts or stale_sources or not graph_source_complete
            else Autonomy.ENFORCE_AUTO
        ),
    )


def test_graph_receipt_projects_verified_exact_release_snapshot() -> None:
    receipt = change_graph_evidence_from_snapshot(
        _snapshot(),
        expected_ontology_release="sha256:release-1",
    )

    assert receipt.graph_revision == "snapshot-1"
    assert receipt.freshness is GraphEvidenceFreshness.CURRENT
    assert receipt.release_state is GraphEvidenceReleaseState.ALIGNED
    assert receipt.authenticated is True
    assert receipt.truncated is False
    assert receipt.conflict_reasons == ()
    assert receipt.source_complete is True
    assert receipt.source_generation == "inventory-generation-1"


def test_graph_receipt_preserves_stale_mixed_and_truncated_evidence() -> None:
    receipt = change_graph_evidence_from_snapshot(
        _snapshot(
            ontology_release="sha256:release-2",
            stale_sources=("inventory",),
            conflicts=("context_graph_truncated", "ownership_conflict"),
        ),
        expected_ontology_release="sha256:release-1",
    )

    assert receipt.freshness is GraphEvidenceFreshness.STALE
    assert receipt.release_state is GraphEvidenceReleaseState.MIXED
    assert receipt.truncated is True
    assert receipt.conflict_reasons == ("context_graph_truncated", "ownership_conflict")


def test_graph_receipt_preserves_incomplete_source_as_unknown() -> None:
    receipt = change_graph_evidence_from_snapshot(
        _snapshot(graph_source_complete=False),
        expected_ontology_release="sha256:release-1",
    )

    assert receipt.source_complete is False
    assert receipt.source_generation == "inventory-generation-1"
    assert receipt.freshness is GraphEvidenceFreshness.UNKNOWN


async def test_complete_planned_change_is_eligible_for_later_gates() -> None:
    service = ChangeAssessmentService(analyzer=ImpactAnalyzer(store=_Store()))
    first = await service.assess(_change(), graph_evidence=_receipt())
    second = await service.assess(_change(), graph_evidence=_receipt())

    assert not first.review_required
    assert first.affected_set.all_resource_ids == ("resource-a", "workload-a")
    assert first.graph_evidence.to_mapping()["graph_revision"] == "graph-revision-1"
    assert first.evidence_digest == second.evidence_digest


async def test_stale_graph_and_conflicts_require_review() -> None:
    service = ChangeAssessmentService(analyzer=ImpactAnalyzer(store=_Store()))
    assessment = await service.assess(
        _change(),
        graph_evidence=_receipt(
            freshness=GraphEvidenceFreshness.STALE,
            conflict_reasons=("concurrent_change",),
        ),
    )

    assert assessment.review_required
    assert assessment.reasons == ("concurrent_change", "graph_stale")


async def test_missing_plan_evidence_requires_review() -> None:
    service = ChangeAssessmentService(analyzer=ImpactAnalyzer(store=_Store()))
    assessment = await service.assess(
        _change(desired_state_digest="", plan_receipt_ref=""),
        graph_evidence=_receipt(),
    )

    assert assessment.review_required
    assert assessment.reasons == (
        "desired_state_digest_missing",
        "plan_receipt_missing",
    )


async def test_mixed_release_receipt_requires_review() -> None:
    service = ChangeAssessmentService(analyzer=ImpactAnalyzer(store=_Store()))
    assessment = await service.assess(
        _change(),
        graph_evidence=_receipt(release_state=GraphEvidenceReleaseState.MIXED),
    )

    assert assessment.review_required
    assert assessment.reasons == ("graph_release_mixed",)


async def test_truncated_graph_receipt_requires_review() -> None:
    service = ChangeAssessmentService(analyzer=ImpactAnalyzer(store=_Store()))
    assessment = await service.assess(
        _change(),
        graph_evidence=_receipt(truncated=True),
    )

    assert assessment.review_required
    assert assessment.reasons == ("graph_truncated",)


async def test_affected_resource_cap_requires_review() -> None:
    service = ChangeAssessmentService(
        analyzer=ImpactAnalyzer(store=_Store()),
        max_affected_resources=1,
    )
    assessment = await service.assess(_change(), graph_evidence=_receipt())

    assert assessment.review_required
    assert assessment.reasons == ("affected_resource_cap_exceeded",)

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.huginn import Huginn
from fdai.agents.muninn import Muninn
from fdai.core.impact_analysis import (
    AffectedSet,
    ChangeAssessment,
    ChangeAssessmentService,
    ChangeGraphEvidenceReceipt,
    GraphEvidenceReleaseState,
    ImpactAnalyzer,
)
from fdai.core.ontology_platform.graph_evidence_refresh import GraphEvidenceFreshness
from fdai.core.operational_context import (
    OperationalContextEvidenceLink,
    OperationalContextMaterializer,
    OperationalContextSnapshot,
)
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)


async def test_huginn_publishes_change_and_muninn_keeps_revision() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    huginn = Huginn(bus=bus)
    muninn = Muninn()
    bus.subscribe("object.change", "Muninn", muninn.on_typed_message)

    event = await huginn.ingest(
        {
            "idempotency_key": "plan-1",
            "event_id": "event-1",
            "correlation_id": "correlation-1",
            "event_type": "iac.plan",
            "source": "gitops",
            "resource_id": "resource-1",
            "occurred_at": datetime(2026, 8, 4, tzinfo=UTC).isoformat(),
            "change": {
                "id": "change-1",
                "change_kind": "infrastructure",
                "intent_kind": "planned",
                "actor_ref": "pipeline-principal",
                "status": "planned",
                "desired_state_digest": "sha256:desired",
                "ontology_release_digest": "sha256:ontology-release-1",
                "plan_receipt_ref": "plan:1",
            },
        }
    )

    changes = bus.messages_on("object.change")
    assert len(changes) == 1
    assert changes[0].principal == "Huginn"
    assert event is not None
    assert all(
        changes[0].payload[key] == value for key, value in event["normalized_change"].items()
    )
    stored = muninn.get_context("changes", "change-1")
    assert stored is not None
    assert stored["change"]["desired_state_digest"] == "sha256:desired"
    assert stored["change"]["ontology_release_digest"] == "sha256:ontology-release-1"
    assert len(muninn.state_store.data["change_revisions"]) == 1


async def test_non_change_event_does_not_publish_change() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    await Huginn(bus=bus).ingest(
        {
            "id": "event-1",
            "event_type": "health.sample",
            "resource_id": "resource-1",
        }
    )
    assert bus.messages_on("object.change") == []


async def test_change_without_authoritative_time_fails_before_publish() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    with pytest.raises(ValueError, match="occurred_at"):
        await Huginn(bus=bus).ingest(
            {
                "id": "event-1",
                "event_type": "iac.plan",
                "source": "gitops",
                "resource_id": "resource-1",
            }
        )
    assert bus.messages_on("object.event") == []
    assert bus.messages_on("object.change") == []


async def test_muninn_preserves_distinct_change_revisions() -> None:
    muninn = Muninn()
    baseline = {
        "producer_principal": "Huginn",
        "id": "change-1",
        "status": "planned",
    }
    await muninn.on_typed_message("object.change", baseline)
    await muninn.on_typed_message("object.change", {**baseline, "status": "completed"})
    await muninn.on_typed_message("object.change", {**baseline, "status": "completed"})

    assert len(muninn.state_store.data["change_revisions"]) == 2
    latest = muninn.get_context("changes", "change-1")
    assert latest is not None
    assert latest["change"]["status"] == "completed"


class _ChangeAssessor:
    def __init__(self, *, review_required: bool) -> None:
        self.review_required = review_required
        self.graph_evidence_receipts: list[ChangeGraphEvidenceReceipt] = []

    async def assess(
        self,
        change: dict[str, object],
        *,
        graph_evidence: ChangeGraphEvidenceReceipt,
        unresolved_conflicts: tuple[str, ...] = (),
    ) -> ChangeAssessment:
        del unresolved_conflicts
        self.graph_evidence_receipts.append(graph_evidence)
        reasons = ("graph_stale",) if self.review_required else ()
        return ChangeAssessment(
            change_id=str(change["id"]),
            correlation_id=str(change["correlation_id"]),
            target_ref=str(change["target_ref"]),
            occurred_at=datetime.fromisoformat(str(change["occurred_at"])),
            affected_set=AffectedSet(
                direct_targets=(str(change["target_ref"]),),
                runtime_dependents=(),
                protected_services=("service-1",),
                protected_objectives=("objective-1",),
                control_dependencies=(),
                graph_revision="revision-1",
            ),
            graph_evidence=ChangeGraphEvidenceReceipt(
                freshness=GraphEvidenceFreshness.STALE,
                release_state=GraphEvidenceReleaseState.UNKNOWN,
                authenticated=False,
            ),
            review_required=self.review_required,
            reasons=reasons,
            evidence_digest="digest-1",
        )


def _planned_event() -> dict[str, object]:
    occurred_at = datetime(2026, 8, 4, tzinfo=UTC).isoformat()
    return {
        "producer_principal": "Huginn",
        "correlation_id": "correlation-1",
        "idempotency_key": "event-1",
        "event_type": "public_network_enabled",
        "resource_id": "resource-1",
        "normalized_change": {
            "id": "change-1",
            "correlation_id": "correlation-1",
            "intent_kind": "planned",
            "target_ref": "resource-1",
            "occurred_at": occurred_at,
            "ontology_release_digest": "sha256:ontology-release-1",
        },
    }


class _OperationalContext:
    def __init__(self, evidence_case: str = "current") -> None:
        self.calls: list[dict[str, object]] = []
        self.evidence_case = evidence_case

    async def materialize(self, **kwargs: object) -> OperationalContextSnapshot:
        self.calls.append(dict(kwargs))
        observed_at = datetime(2026, 8, 4, tzinfo=UTC)
        evidence_time = (
            observed_at + timedelta(seconds=1) if self.evidence_case == "future" else observed_at
        )
        observation = LinkObservationMetadata(
            state_fact=StateFactMetadata(
                lane=StateFactLane.OBSERVED,
                authority=StateFactAuthority.PROVIDER,
                source_identity="inventory-provider",
                source_revision="inventory-revision-1",
                effective_at=evidence_time,
                recorded_at=evidence_time,
                evidence_cutoff=evidence_time,
                freshness_ceiling_seconds=300,
                completeness=1.0,
                synthetic=self.evidence_case == "synthetic",
                evidence_refs=("inventory:evidence-1",),
            ),
            verification_method="provider-readback",
            verified=True,
            verifier_identity="inventory-verifier",
            verifier_revision="verifier-revision-1",
            verification_receipt_ref="inventory:verification-1",
        )
        return OperationalContextSnapshot(
            snapshot_id="snapshot-1",
            target_resource_id="resource-1",
            cutoff=observed_at,
            recorded_at=observed_at,
            catalog_versions=(
                (
                    "ontology",
                    (
                        "sha256:ontology-release-2"
                        if self.evidence_case == "mixed"
                        else "sha256:ontology-release-1"
                    ),
                ),
            ),
            service_ids=("service-1",),
            workload_ids=("workload-1",),
            objective_ids=("objective-1",),
            service_objective_ids=("objective-1",),
            recovery_objective_ids=(),
            cost_objective_ids=(),
            constraint_ids=(),
            ownership_ids=(),
            dependency_ids=("workload-1",),
            source_freshness=(),
            evidence_links=(
                OperationalContextEvidenceLink(
                    link_type="workload_runs_on",
                    from_id="workload-1",
                    to_id="resource-1",
                    observation_metadata=observation,
                ),
            ),
            evidence_paths=(),
            temporal_exclusions=(),
            stale_sources=(("inventory-provider",) if self.evidence_case == "stale" else ()),
            conflicts=(
                ("ownership_conflict",)
                if self.evidence_case == "conflicting"
                else (("context_graph_truncated",) if self.evidence_case == "truncated" else ())
            ),
            autonomy_ceiling=(
                Autonomy.ENFORCE_AUTO if self.evidence_case == "current" else Autonomy.SHADOW_ONLY
            ),
            graph_source_complete=self.evidence_case != "incomplete",
            graph_source_generation="inventory-generation-1",
        )


class _ImpactStore:
    async def traverse(self, **_kwargs: object) -> OntologyGraphSnapshot:
        return OntologyGraphSnapshot(
            objects=(
                OntologyObjectRecord("resource-1", "Resource", {"id": "resource-1"}),
                OntologyObjectRecord("workload-1", "Workload", {"id": "workload-1"}),
                OntologyObjectRecord("service-1", "BusinessService", {"id": "service-1"}),
                OntologyObjectRecord(
                    "objective-1",
                    "ServiceObjective",
                    {"id": "objective-1"},
                ),
            ),
            links=(
                OntologyLinkRecord("workload_runs_on", "workload-1", "resource-1"),
                OntologyLinkRecord("implemented_by", "service-1", "workload-1"),
                OntologyLinkRecord(
                    "service_has_service_objective",
                    "service-1",
                    "objective-1",
                ),
            ),
        )


async def test_forseti_sources_planned_change_graph_evidence_from_exact_context() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    assessor = _ChangeAssessor(review_required=False)
    operational_context = _OperationalContext()
    forseti = Forseti(
        bus=bus,
        change_assessor=assessor,
        operational_context=cast(OperationalContextMaterializer, operational_context),
    )

    await forseti.on_typed_message("object.event", _planned_event())

    receipt = assessor.graph_evidence_receipts[0]
    assert receipt.graph_revision == "snapshot-1"
    assert receipt.freshness is GraphEvidenceFreshness.CURRENT
    assert receipt.release_state is GraphEvidenceReleaseState.ALIGNED
    assert receipt.authenticated is True
    assert operational_context.calls[0]["require_verified_links"] is True


@pytest.mark.parametrize(
    ("evidence_case", "expected_reason"),
    (
        ("stale", "graph_stale"),
        ("mixed", "graph_release_mixed"),
        ("incomplete", "graph_source_incomplete"),
        ("conflicting", "ownership_conflict"),
        (
            "synthetic",
            "link_evidence_synthetic:workload_runs_on:workload-1:resource-1",
        ),
        (
            "future",
            "link_evidence_after_cutoff:workload_runs_on:workload-1:resource-1",
        ),
        ("truncated", "graph_truncated"),
    ),
)
async def test_forseti_requires_review_for_unsafe_graph_evidence(
    evidence_case: str,
    expected_reason: str,
) -> None:
    bus = InMemoryBus(registry=load_pantheon())
    assessor = ChangeAssessmentService(
        analyzer=ImpactAnalyzer(store=cast(OntologyInstanceStore, _ImpactStore()))
    )
    operational_context = _OperationalContext(evidence_case)
    forseti = Forseti(
        bus=bus,
        change_assessor=assessor,
        operational_context=cast(OperationalContextMaterializer, operational_context),
    )

    await forseti.on_typed_message("object.event", _planned_event())

    verdict = bus.messages_on("object.verdict")[-1].payload
    assert verdict["risk_verdict"] == "hil"
    assert verdict["change_assessment_status"] == "review"
    assert expected_reason in verdict["change_assessment"]["reasons"]


async def test_forseti_lowers_planned_change_to_human_review() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    assessor = _ChangeAssessor(review_required=True)
    forseti = Forseti(bus=bus, change_assessor=assessor)

    await forseti.on_typed_message("object.event", _planned_event())

    verdict = bus.messages_on("object.verdict")[-1].payload
    assert verdict["risk_verdict"] == "hil"
    assert verdict["change_assessment_status"] == "review"
    assert verdict["change_assessment"]["review_required"] is True
    assert assessor.graph_evidence_receipts == [ChangeGraphEvidenceReceipt.unavailable()]


async def test_forseti_holds_planned_change_without_assessor() -> None:
    bus = InMemoryBus(registry=load_pantheon())

    await Forseti(bus=bus).on_typed_message("object.event", _planned_event())

    verdict = bus.messages_on("object.verdict")[-1].payload
    assert verdict["risk_verdict"] == "hil"
    assert verdict["change_assessment_status"] == "unavailable"

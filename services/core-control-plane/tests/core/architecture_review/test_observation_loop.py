from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fdai.agents import InMemoryBus, load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.saga import Saga
from fdai.core.architecture_review import (
    ArchitectureReviewBackpressureError,
    ArchitectureReviewEvidence,
    ArchitectureReviewProjector,
    InMemoryArchitectureReviewStateStore,
    OntologyArchitectureReviewLoop,
)
from fdai.core.impact_analysis import AffectedSet
from fdai.core.ontology_platform import OntologyScenarioChangeSet
from fdai.core.operational_context import (
    OperationalContextSnapshot,
    OperationalEvidenceMaterial,
    OperationalEvidenceReadRequest,
    OperationalEvidenceReadService,
)
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)

NOW = datetime(2026, 8, 27, 12, tzinfo=UTC)
RELEASE = "sha256:" + "a" * 64


def _context(target: str) -> OperationalContextSnapshot:
    return OperationalContextSnapshot(
        snapshot_id=f"context:{target}",
        target_resource_id=target,
        cutoff=NOW,
        recorded_at=NOW,
        catalog_versions=(("ontology", RELEASE),),
        service_ids=(),
        workload_ids=(),
        objective_ids=(),
        service_objective_ids=(),
        recovery_objective_ids=(),
        cost_objective_ids=(),
        constraint_ids=(),
        ownership_ids=(),
        dependency_ids=(),
        source_freshness=(),
        evidence_links=(),
        evidence_paths=(),
        temporal_exclusions=(),
        stale_sources=(),
        conflicts=(),
        autonomy_ceiling=Autonomy.ENFORCE_AUTO,
    )


class _ContextSource:
    async def resolve(self, *, change: dict[str, object]) -> OperationalContextSnapshot:
        return _context(str(change["target_ref"]))


class _ProjectionStore:
    def __init__(self) -> None:
        self.objects: dict[str, OntologyObjectRecord] = {}
        self.links: list[OntologyLinkRecord] = []

    async def upsert_object(self, record: OntologyObjectRecord, **_kwargs: object) -> None:
        self.objects[record.id] = record

    async def upsert_link(self, record: OntologyLinkRecord) -> None:
        self.links.append(record)

    async def get_object(self, object_id: str) -> OntologyObjectRecord | None:
        return self.objects.get(object_id)

    async def query_objects(
        self,
        *,
        object_types: tuple[str, ...] = (),
        limit: int = 100,
    ) -> OntologyGraphSnapshot:
        del limit
        return OntologyGraphSnapshot(
            objects=tuple(
                record
                for record in self.objects.values()
                if not object_types or record.object_type in object_types
            )
        )


class _EvidenceSource:
    def __init__(self, *, delay: float = 0.0, backpressure: bool = False) -> None:
        self.calls = 0
        self.delay = delay
        self.backpressure = backpressure

    async def collect(
        self,
        *,
        change: dict[str, object],
        context: OperationalContextSnapshot,
    ) -> ArchitectureReviewEvidence:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.backpressure:
            raise ArchitectureReviewBackpressureError("bounded test backpressure")
        bundle = await self._read_bundle(context)
        return ArchitectureReviewEvidence(
            bundle=bundle,
            base_graph=OntologyGraphSnapshot(),
            object_types=(),
            link_types=(),
            scenario_changes=OntologyScenarioChangeSet(),
            affected_set=AffectedSet(
                direct_targets=(context.target_resource_id,),
                runtime_dependents=(),
                protected_services=(),
                protected_objectives=(),
                control_dependencies=(),
                graph_revision="sha256:" + "b" * 64,
            ),
        )

    async def _read_bundle(self, context: OperationalContextSnapshot):
        class _BundleSource:
            async def collect(
                self,
                request: OperationalEvidenceReadRequest,
            ) -> OperationalEvidenceMaterial:
                return OperationalEvidenceMaterial(
                    ontology_release_digest=request.ontology_release_digest,
                    catalog_revision=request.catalog_revision,
                    purpose=request.purpose,
                    scope=request.scope,
                    cutoff=request.cutoff,
                )

        return (
            await OperationalEvidenceReadService(
                source=_BundleSource(),
                clock=lambda: NOW,
            ).read(
                OperationalEvidenceReadRequest(
                    ontology_release_digest=RELEASE,
                    catalog_revision="catalog-r1",
                    purpose="architecture-review",
                    scope=(context.target_resource_id,),
                    cutoff=context.cutoff,
                )
            )
        ).bundle


def _change(number: str = "1") -> dict[str, object]:
    return {
        "id": f"change-{number}",
        "idempotency_key": f"change-key-{number}",
        "correlation_id": f"correlation-{number}",
        "target_ref": "resource-example",
    }


def _loop(source: _EvidenceSource, store: InMemoryArchitectureReviewStateStore | None = None):
    return OntologyArchitectureReviewLoop(
        context_source=_ContextSource(),
        evidence_source=source,
        state_store=store,
        clock=lambda: NOW,
    )


async def test_observation_slice_composes_case_and_envelope_without_authority() -> None:
    source = _EvidenceSource()
    result = await _loop(source).evaluate(_change())

    assert result.recommendation == "conformant_observation"
    assert result.decision_case is not None
    assert result.impact_envelope is not None
    assert result.scenario is not None
    assert result.evidence is not None
    assert result.mode == "observation"
    assert result.mutation_authority is False
    assert result.execution_authority is False


async def test_duplicate_restart_and_reorder_are_idempotent() -> None:
    store = InMemoryArchitectureReviewStateStore()
    first_source = _EvidenceSource()
    first_loop = _loop(first_source, store)
    first = await first_loop.evaluate(_change())
    duplicate = await first_loop.evaluate(_change())
    restarted = await _loop(_EvidenceSource(), store).evaluate(_change())

    assert first.decision_case is not None
    assert duplicate.replayed is True
    assert restarted.replayed is True
    assert first.decision_case.case_id == restarted.decision_case.case_id
    assert first_source.calls == 1
    reordered = await first_loop.replay((_change("2"), _change("1")))
    assert tuple(item.change_id for item in reordered) == ("change-2", "change-1")


async def test_deadline_and_backpressure_hold_without_mutation() -> None:
    timed_out_result = await OntologyArchitectureReviewLoop(
        context_source=_ContextSource(),
        evidence_source=_EvidenceSource(delay=0.02),
        deadline_seconds=0.001,
    ).evaluate(_change())
    held = await _loop(_EvidenceSource(backpressure=True)).evaluate(_change("2"))

    assert timed_out_result.recommendation == "hold"
    assert "deadline_exceeded" in timed_out_result.reasons
    assert held.recommendation == "hold"
    assert "evidence_unavailable" in held.reasons


async def test_forseti_publishes_one_typed_observation_verdict_and_saga_audits() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    source = _EvidenceSource()
    forseti = Forseti(
        bus=bus,
        architecture_review_loop=_loop(source),
    )
    saga = Saga()
    bus.subscribe("object.change", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Saga", saga.on_typed_message)

    await bus.publish("Huginn", "object.change", _change())
    await bus.publish("Huginn", "object.change", _change())

    verdicts = bus.messages_on("object.verdict")
    assert len(verdicts) == 1
    assert verdicts[0].payload["mode"] == "observation"
    assert verdicts[0].payload["execution_authority"] is False
    assert not bus.messages_on("object.action-run")
    assert len(saga.replay_for_correlation("correlation-1")) == 1


async def test_projection_derives_lineage_and_reconciles_removed_checks() -> None:
    result = await _loop(_EvidenceSource()).evaluate(_change())
    store = _ProjectionStore()
    review_id = "arb-review:change-1"
    stale_check = f"{review_id}:check:evidence:removed-ref"
    store.objects[stale_check] = OntologyObjectRecord(
        id=stale_check,
        object_type="ReviewCheck",
        properties={
            "id": stale_check,
            "check_key": "removed-ref",
            "category": "evidence",
            "status": "ready",
            "severity": "high",
            "required": True,
            "description": "old evidence",
            "updated_at": NOW,
        },
    )

    await ArchitectureReviewProjector(store, {}).project_observation(result, process_id="process-1")

    assert store.objects[review_id].object_type == "ReviewCase"
    assert result.decision_case is not None
    assert result.impact_envelope is not None
    assert result.decision_case.case_id in store.objects
    assert result.impact_envelope.envelope_id in store.objects
    assert store.objects[stale_check].properties["status"] == "removed"

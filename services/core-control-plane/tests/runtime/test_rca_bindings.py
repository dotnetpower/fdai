from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from fdai.composition import default_container
from fdai.core.ontology_platform.topology_history import (
    TopologyLinkRevision,
    TopologyObjectRevision,
    TopologyRevisionBatch,
)
from fdai.core.rca.causal_chain import CorrelatedEvent
from fdai.runtime.rca_bindings import (
    GenerationGuardedIncidentMemberSource,
    TopologyHistoryIncidentRcaContextSource,
    _dependency_mapping,
    _match_lifecycle_incident,
    bind_t1_rca_from_environment,
    load_reviewed_dependency_graph,
)
from fdai.shared.config import AppConfig
from fdai.shared.contracts.models import (
    Incident,
    IncidentSeverity,
    IncidentState,
)
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

AT = datetime(2026, 9, 5, tzinfo=UTC)
INCIDENT_ID = UUID("00000000-0000-0000-0000-000000000001")


@dataclass
class StaticMemberSource:
    result: tuple[CorrelatedEvent, ...]
    calls: int = 0
    cutoff: datetime | None = None

    async def members(self, *, incident_id: str) -> tuple[CorrelatedEvent, ...]:
        self.calls += 1
        return self.result

    async def members_for_incident(
        self,
        incident: Incident,
        *,
        cutoff: datetime | None = None,
    ) -> tuple[CorrelatedEvent, ...]:
        del incident
        self.calls += 1
        self.cutoff = cutoff
        return self.result


class StaticGraphStore:
    def __init__(self, snapshot: OntologyGraphSnapshot) -> None:
        self.snapshot = snapshot

    async def query_objects(self, **kwargs: object) -> OntologyGraphSnapshot:
        return self.snapshot


class StaticTraverseStore(StaticGraphStore):
    async def traverse_from_type(self, **kwargs: object) -> OntologyGraphSnapshot:
        return self.snapshot


class SequenceTraverseStore(StaticGraphStore):
    def __init__(self, snapshots: tuple[OntologyGraphSnapshot, ...]) -> None:
        super().__init__(snapshots[0])
        self._snapshots = list(snapshots)

    async def traverse_from_type(self, **kwargs: object) -> OntologyGraphSnapshot:
        del kwargs
        return self._snapshots.pop(0)


class StaticTopologyHistory:
    def __init__(self, batch: TopologyRevisionBatch) -> None:
        self.batch = batch

    async def read(
        self,
        *,
        as_of: datetime,
        known_at: datetime,
    ) -> tuple[TopologyRevisionBatch, ...]:
        assert as_of == AT
        assert known_at == AT + timedelta(minutes=1)
        return (self.batch,)


def _snapshot(*, generation: str = "generation-1") -> OntologyGraphSnapshot:
    return OntologyGraphSnapshot(
        objects=(
            OntologyObjectRecord("resource:app", "Resource", {}),
            OntologyObjectRecord("resource:db", "Resource", {}),
        ),
        links=(OntologyLinkRecord("depends_on", "resource:app", "resource:db"),),
        source_complete=True,
        source_generation=generation,
    )


def _topology_batch(generation: str) -> TopologyRevisionBatch:
    objects = tuple(
        TopologyObjectRevision.upsert(
            OntologyObjectRecord(identifier, "Resource", {}),
            effective_at=AT,
            recorded_at=AT,
            evidence_ref=f"evidence:{identifier}",
        )
        for identifier in ("resource:app", "resource:db")
    )
    link = TopologyLinkRevision(
        from_id="resource:app",
        from_type="Resource",
        link_type="depends_on",
        to_id="resource:db",
        to_type="Resource",
        properties_json="{}",
        effective_at=AT,
        recorded_at=AT,
        deleted=False,
        evidence_ref="evidence:depends-on",
    )
    return TopologyRevisionBatch(
        revision_id=f"revision:{generation}",
        provider_generation_ref=generation,
        effective_at=AT,
        recorded_at=AT,
        complete_snapshot=True,
        ontology_release_digest=f"sha256:{'a' * 64}",
        source_receipt_digest=f"sha256:{'b' * 64}",
        object_revisions=objects,
        link_revisions=(link,),
    )


@pytest.mark.asyncio
async def test_incident_context_uses_matching_historical_topology_generation() -> None:
    member = CorrelatedEvent(
        event_id="deployment-1",
        at=AT - timedelta(minutes=1),
        resource_ref="resource:db",
        is_change=True,
        inventory_generation="generation-7",
    )
    incident = Incident(
        schema_version="1.0.0",
        incident_id=INCIDENT_ID,
        state=IncidentState.OPEN,
        severity=IncidentSeverity.SEV2,
        opened_at=AT - timedelta(hours=1),
        correlation_keys=(
            "resource:resource:app",
            "signal:error.rate.spike",
            "correlation:episode-1",
        ),
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000002"),),
    )
    members = StaticMemberSource((member,))
    source = TopologyHistoryIncidentRcaContextSource(
        incident_lookup=lambda identity: None,
        incident_candidates=lambda: {INCIDENT_ID: incident},
        member_source=members,
        topology_history=StaticTopologyHistory(_topology_batch("generation-7")),
        clock=lambda: AT + timedelta(minutes=1),
    )

    context = await source.context(
        incident_id="00000000-0000-0000-0000-000000000099",
        resource_ref="resource:app",
        event_type="error.rate.spike",
        correlation_id="episode-1",
        detected_at=AT,
    )

    assert context is not None
    assert context.inventory_generation == "generation-7"
    assert context.members == (member,)
    assert context.depends_on == {"resource:app": frozenset({"resource:db"})}
    assert members.cutoff == AT


@pytest.mark.asyncio
async def test_deployed_binding_requires_dedicated_reader_identity(
    app_config: AppConfig,
) -> None:
    container = default_container(app_config)
    async with httpx.AsyncClient() as client:
        bound = await bind_t1_rca_from_environment(
            container,
            incident_lookup=lambda incident_id: None,
            incident_candidates=lambda: {},
            http_client=client,
            identity=StaticWorkloadIdentity(audience="https://management.azure.com/.default"),
            environment={
                "FDAI_STATE_STORE_DSN": "postgresql://localhost/fdai",
                "FDAI_EXECUTION_VENUE": "deployed",
            },
        )

    assert bound is container
    assert bound.incident_member_source is None


@pytest.mark.asyncio
async def test_dependency_graph_requires_complete_generation() -> None:
    graph = await load_reviewed_dependency_graph(StaticTraverseStore(_snapshot()))

    assert graph is not None
    assert graph.inventory_generation == "generation-1"
    assert graph.depends_on == {"resource:app": frozenset({"resource:db"})}
    assert graph.dependency_digest.startswith("sha256:")

    unavailable = await load_reviewed_dependency_graph(
        StaticTraverseStore(
            OntologyGraphSnapshot(
                objects=_snapshot().objects,
                links=_snapshot().links,
                source_complete=False,
                source_generation="generation-1",
            )
        )
    )
    assert unavailable is None


@pytest.mark.asyncio
async def test_member_source_abstains_when_graph_generation_changes() -> None:
    member = CorrelatedEvent(
        event_id="deployment-1",
        at=datetime(2026, 9, 5, tzinfo=UTC),
        resource_ref="resource:db",
        is_change=True,
    )
    source = StaticMemberSource((member,))
    guarded = GenerationGuardedIncidentMemberSource(
        source=source,
        graph_store=StaticTraverseStore(_snapshot(generation="generation-2")),
        required_generation="generation-1",
        required_dependency_digest=f"sha256:{'a' * 64}",
    )

    assert await guarded.members(incident_id="incident-1") == ()
    assert source.calls == 0


@pytest.mark.asyncio
async def test_member_source_rechecks_generation_after_provider_read() -> None:
    original = await load_reviewed_dependency_graph(StaticTraverseStore(_snapshot()))
    assert original is not None
    member = CorrelatedEvent(
        event_id="deployment-1",
        at=datetime(2026, 9, 5, tzinfo=UTC),
        resource_ref="resource:db",
        is_change=True,
        inventory_generation="generation-1",
    )
    source = StaticMemberSource((member,))
    guarded = GenerationGuardedIncidentMemberSource(
        source=source,
        graph_store=SequenceTraverseStore((_snapshot(), _snapshot(generation="generation-2"))),
        required_generation=original.inventory_generation,
        required_dependency_digest=original.dependency_digest,
    )

    assert await guarded.members(incident_id="incident-1") == ()
    assert source.calls == 1


@pytest.mark.asyncio
async def test_member_source_abstains_when_relationships_change_in_same_generation() -> None:
    original = await load_reviewed_dependency_graph(StaticTraverseStore(_snapshot()))
    assert original is not None
    changed_snapshot = OntologyGraphSnapshot(
        objects=_snapshot().objects,
        links=(
            OntologyLinkRecord(
                "depends_on",
                "resource:db",
                "resource:app",
            ),
        ),
        source_complete=True,
        source_generation="generation-1",
    )
    source = StaticMemberSource(())
    guarded = GenerationGuardedIncidentMemberSource(
        source=source,
        graph_store=SequenceTraverseStore((changed_snapshot, changed_snapshot)),
        required_generation=original.inventory_generation,
        required_dependency_digest=original.dependency_digest,
    )

    assert await guarded.members(incident_id="incident-1") == ()
    assert source.calls == 0


def test_dependency_mapping_rejects_non_resource_endpoint() -> None:
    with pytest.raises(ValueError, match="invalid Resource edge"):
        _dependency_mapping(
            OntologyGraphSnapshot(
                objects=(
                    OntologyObjectRecord("resource:app", "Resource", {}),
                    OntologyObjectRecord("service:api", "BusinessService", {}),
                ),
                links=(
                    OntologyLinkRecord(
                        "depends_on",
                        "resource:app",
                        "service:api",
                    ),
                ),
                source_generation="generation-1",
            )
        )


def test_dependency_mapping_ignores_other_topology_link_types() -> None:
    snapshot = _snapshot()
    mixed = OntologyGraphSnapshot(
        objects=snapshot.objects,
        links=(
            *snapshot.links,
            OntologyLinkRecord(
                "attached_to",
                "resource:db",
                "resource:app",
            ),
        ),
        source_complete=True,
        source_generation="generation-1",
    )

    assert _dependency_mapping(mixed) == {"resource:app": frozenset({"resource:db"})}


def test_lifecycle_incident_fallback_excludes_events_after_resolution() -> None:
    incident = Incident(
        schema_version="1.0.0",
        incident_id=INCIDENT_ID,
        state=IncidentState.RESOLVED,
        severity=IncidentSeverity.SEV2,
        opened_at=AT,
        resolved_at=AT + timedelta(minutes=5),
        correlation_keys=(
            "resource:resource:app",
            "signal:error.rate.spike",
        ),
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000002"),),
    )

    assert (
        _match_lifecycle_incident(
            {INCIDENT_ID: incident},
            resource_ref="resource:app",
            event_type="error.rate.spike",
            correlation_id=None,
            detected_at=AT + timedelta(minutes=6),
        )
        is None
    )

    reopened = incident.model_copy(update={"state": IncidentState.TRIAGING})
    assert (
        _match_lifecycle_incident(
            {INCIDENT_ID: reopened},
            resource_ref="resource:app",
            event_type="error.rate.spike",
            correlation_id=None,
            detected_at=AT + timedelta(minutes=6),
        )
        == reopened
    )

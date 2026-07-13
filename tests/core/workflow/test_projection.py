"""Process runtime to ontology instance projection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.workflow.projection import (
    ProcessOntologyProjector,
    ProcessProjectionWorker,
    ProjectingProcessRuntimeStore,
)
from fdai.shared.contracts.models import (
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.testing import (
    InMemoryOntologyInstanceStore,
    InMemoryProcessRuntimeStore,
)

_NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _object_type(name: str, properties: dict[str, PropertyDecl]) -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        key="id",
        properties=properties,
    )


def _ontology_store() -> InMemoryOntologyInstanceStore:
    common = {"id": PropertyDecl(type=PropertyType.STRING, required=True)}
    process = {
        **common,
        "workflow_ref": PropertyDecl(type=PropertyType.STRING, required=True),
        "workflow_version": PropertyDecl(type=PropertyType.STRING, required=True),
        "status": PropertyDecl(type=PropertyType.STRING, required=True),
        "current_step": PropertyDecl(type=PropertyType.STRING, required=True),
        "target_resource_id": PropertyDecl(type=PropertyType.STRING, required=True),
        "started_at": PropertyDecl(type=PropertyType.DATETIME, required=True),
        "updated_at": PropertyDecl(type=PropertyType.DATETIME, required=True),
        "correlation_id": PropertyDecl(type=PropertyType.STRING, required=True),
        "revision": PropertyDecl(type=PropertyType.INTEGER, required=True),
    }
    return InMemoryOntologyInstanceStore(
        object_types=(
            _object_type("Process", process),
            _object_type("Resource", common),
        ),
        link_types=(
            OntologyLinkType(
                schema_version="1.0.0",
                name="targets",
                version="1.0.0",
                from_type="Process",
                to_type="Resource",
                cardinality=LinkCardinality.MANY_TO_ONE,
            ),
        ),
    )


def _snapshot() -> ProcessSnapshot:
    return ProcessSnapshot(
        process_id="process-1",
        workflow_ref="architecture-review",
        workflow_version="1.0.0",
        status=ProcessStatus.PENDING,
        current_step="",
        target_resource_id="resource-1",
        started_at=_NOW,
        updated_at=_NOW,
        correlation_id="corr-1",
    )


def _event() -> ProcessEvent:
    return ProcessEvent(
        event_id="event-1",
        process_id="process-1",
        kind=ProcessEventKind.PROCESS_CREATED,
        idempotency_key="process-1:create",
        recorded_at=_NOW,
        correlation_id="corr-1",
    )


async def test_projecting_store_materializes_process_and_target_link() -> None:
    ontology = _ontology_store()
    await ontology.upsert_object(
        OntologyObjectRecord(
            id="resource-1",
            object_type="Resource",
            properties={"id": "resource-1"},
        )
    )
    runtime = ProjectingProcessRuntimeStore(
        runtime=InMemoryProcessRuntimeStore(),
        projector=ProcessOntologyProjector(ontology),
    )

    stored, created = await runtime.create(snapshot=_snapshot(), event=_event())
    graph = await ontology.traverse(root_ids=(stored.process_id,), max_depth=1)

    assert created is True
    process = await ontology.get_object("process-1")
    assert process is not None
    assert process.properties["workflow_ref"] == "architecture-review"
    assert {item.id for item in graph.objects} == {"process-1", "resource-1"}
    assert [link.link_type for link in graph.links] == ["targets"]


async def test_projection_is_refreshed_after_transition() -> None:
    ontology = _ontology_store()
    runtime = ProjectingProcessRuntimeStore(
        runtime=InMemoryProcessRuntimeStore(),
        projector=ProcessOntologyProjector(ontology),
    )
    stored, _ = await runtime.create(snapshot=_snapshot(), event=_event())
    await runtime.transition(
        process_id=stored.process_id,
        expected_revision=stored.revision,
        status=ProcessStatus.WAITING,
        current_step="collect-evidence",
        event=ProcessEvent(
            event_id="event-2",
            process_id="process-1",
            kind=ProcessEventKind.STEP_WAITING,
            idempotency_key="process-1:wait",
            recorded_at=_NOW,
            correlation_id="corr-1",
            step_id="collect-evidence",
        ),
    )
    process = await ontology.get_object("process-1")
    assert process is not None
    assert process.properties["status"] == "waiting"
    assert process.properties["current_step"] == "collect-evidence"


class _FlakyProjector:
    def __init__(self) -> None:
        self.fail = True
        self.calls: list[str] = []

    async def project(
        self,
        snapshot: ProcessSnapshot,
        *,
        event: ProcessEvent | None = None,
    ) -> None:
        assert event is not None
        self.calls.append(event.event_id)
        if self.fail:
            raise RuntimeError("projection unavailable")


async def test_projection_failure_is_retried_without_masking_runtime_commit() -> None:
    store = InMemoryProcessRuntimeStore()
    projector = _FlakyProjector()
    runtime = ProjectingProcessRuntimeStore(runtime=store, projector=projector)

    stored, created = await runtime.create(snapshot=_snapshot(), event=_event())

    assert created is True
    assert stored.revision == 1
    assert await store.get(stored.process_id) == stored
    worker = ProcessProjectionWorker(
        runtime=store,
        outbox=store,
        projector=projector,
        retry_delay_seconds=30,
        clock=lambda: _NOW,
    )
    first = await worker.run_once()
    assert first.claimed == 1
    assert first.deferred == 1

    projector.fail = False
    retry = ProcessProjectionWorker(
        runtime=store,
        outbox=store,
        projector=projector,
        clock=lambda: _NOW + timedelta(seconds=30),
    )
    second = await retry.run_once()
    drained = await retry.run_once()

    assert second.completed == 1
    assert drained.claimed == 0
    assert projector.calls == ["event-1", "event-1", "event-1"]


async def test_healthy_transition_drains_due_projection_backlog() -> None:
    store = InMemoryProcessRuntimeStore()
    projector = _FlakyProjector()
    runtime = ProjectingProcessRuntimeStore(
        runtime=store,
        projector=projector,
        retry_clock=lambda: _NOW + timedelta(seconds=31),
    )
    stored, _ = await runtime.create(snapshot=_snapshot(), event=_event())
    projector.fail = False

    await runtime.transition(
        process_id=stored.process_id,
        expected_revision=stored.revision,
        status=ProcessStatus.RUNNING,
        current_step="collect-evidence",
        event=ProcessEvent(
            event_id="event-2",
            process_id=stored.process_id,
            kind=ProcessEventKind.STEP_STARTED,
            idempotency_key="process-1:start",
            recorded_at=_NOW + timedelta(seconds=31),
            correlation_id=stored.correlation_id,
            step_id="collect-evidence",
        ),
    )

    assert projector.calls == ["event-1", "event-2", "event-1"]
    assert (await runtime.retry_pending()).claimed == 0

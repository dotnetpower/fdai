"""Render the declarative architecture-review report from ontology state."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fdai.core.reporting.composition import default_reporting_engine
from fdai.core.reporting.datasources.ontology import OntologyDataSource
from fdai.shared.contracts.models import (
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
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

_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _object_type(name: str, extra: dict[str, PropertyDecl]) -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True), **extra},
    )


def _ontology() -> InMemoryOntologyInstanceStore:
    return InMemoryOntologyInstanceStore(
        object_types=(
            _object_type("Process", {}),
            _object_type(
                "ReviewCase",
                {
                    "design_status": PropertyDecl(type=PropertyType.STRING),
                    "production_status": PropertyDecl(type=PropertyType.STRING),
                },
            ),
            _object_type(
                "ReviewCheck",
                {
                    "check_key": PropertyDecl(type=PropertyType.STRING),
                    "status": PropertyDecl(type=PropertyType.STRING),
                    "description": PropertyDecl(type=PropertyType.STRING),
                    "updated_at": PropertyDecl(type=PropertyType.DATETIME),
                    "category": PropertyDecl(type=PropertyType.STRING),
                    "severity": PropertyDecl(type=PropertyType.STRING),
                },
            ),
            _object_type("EvidenceArtifact", {}),
            _object_type("Principal", {}),
            _object_type("Decision", {}),
        ),
        link_types=(
            OntologyLinkType(
                schema_version="1.0.0",
                name="runs_review",
                version="1.0.0",
                from_type="Process",
                to_type="ReviewCase",
                cardinality=LinkCardinality.ONE_TO_ONE,
            ),
            OntologyLinkType(
                schema_version="1.0.0",
                name="contains_check",
                version="1.0.0",
                from_type="ReviewCase",
                to_type="ReviewCheck",
                cardinality=LinkCardinality.ONE_TO_MANY,
            ),
        ),
    )


async def test_architecture_review_report_renders_from_ontology() -> None:
    ontology = _ontology()
    process_store = InMemoryProcessRuntimeStore()
    snapshot, _ = await process_store.create(
        snapshot=ProcessSnapshot(
            process_id="process-1",
            workflow_ref="architecture-review",
            workflow_version="1.0.0",
            status=ProcessStatus.WAITING,
            current_step="evidence",
            target_resource_id="scope-1",
            started_at=_NOW,
            updated_at=_NOW,
            correlation_id="corr-1",
        ),
        event=ProcessEvent(
            event_id="event-1",
            process_id="process-1",
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="process-1:create",
            recorded_at=_NOW,
            correlation_id="corr-1",
        ),
    )
    await ontology.upsert_object(
        OntologyObjectRecord(id="process-1", object_type="Process", properties={"id": "process-1"})
    )
    await ontology.upsert_object(
        OntologyObjectRecord(
            id="review-1",
            object_type="ReviewCase",
            properties={
                "id": "review-1",
                "design_status": "conditional",
                "production_status": "blocked",
            },
        )
    )
    await ontology.upsert_object(
        OntologyObjectRecord(
            id="check-1",
            object_type="ReviewCheck",
            properties={
                "id": "check-1",
                "check_key": "rpo-rto",
                "status": "blocked",
                "description": "Approve numeric objectives",
                "updated_at": _NOW.isoformat(),
                "category": "reliability",
                "severity": "critical",
            },
        )
    )
    await ontology.upsert_link(
        OntologyLinkRecord(link_type="runs_review", from_id="process-1", to_id="review-1")
    )
    await ontology.upsert_link(
        OntologyLinkRecord(link_type="contains_check", from_id="review-1", to_id="check-1")
    )
    engine, _ = default_reporting_engine(
        reports_root=_ROOT / "rule-catalog" / "reports",
        ontology_store=ontology,
        process_store=process_store,
    )

    report = await engine.render(
        "architecture-review-process", variables={"process_id": snapshot.process_id}
    )
    widgets = {widget.id: widget for widget in report.widgets}

    assert widgets["process_status"].data["value"] == "waiting"
    assert widgets["design_status"].data["value"] == "conditional"
    assert widgets["production_status"].data["value"] == "blocked"
    assert widgets["checks"].data["summary"]["fail"] == 1
    assert widgets["graph"].data["nodes"]
    assert isinstance(OntologyDataSource(ontology, process_store).name, str)

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from fdai.agents.huginn import Huginn
from fdai.shared.contracts.models import Event, IncidentCorrelation, Mode


def test_huginn_projects_schema_valid_readiness_event_payload() -> None:
    now = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)
    event = Event(
        schema_version="1.0.0",
        event_id=uuid5(NAMESPACE_URL, "readiness-event"),
        idempotency_key="readiness-event",
        correlation_id="readiness-cluster-example",
        source="fdai.delivery.analyzer_tick",
        event_type="detection.readiness.observed",
        resource_ref="cluster/example",
        payload={
            "detection_readiness": {
                "dimension": "discovered",
                "status": "passed",
                "observed_at": now.isoformat(),
                "expires_at": now.isoformat(),
                "source": "inventory.target",
                "evidence_digest": "a" * 64,
                "pass_id": "b" * 64,
            }
        },
        detected_at=now,
        ingested_at=now,
        incident_correlation=IncidentCorrelation.NONE,
        mode=Mode.SHADOW,
    )

    normalized = asyncio.run(Huginn().ingest(event.model_dump(mode="json")))

    assert normalized is not None
    assert normalized["resource_id"] == "cluster/example"
    assert normalized["attributes"] == {
        "dimension": "discovered",
        "status": "passed",
        "observed_at": now.isoformat(),
        "expires_at": now.isoformat(),
        "source": "inventory.target",
        "evidence_digest": "a" * 64,
        "pass_id": "b" * 64,
    }

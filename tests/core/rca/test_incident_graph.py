from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.rca.incident_graph import (
    CausalIncidentGraphMaterializer,
    IncidentGraphBounds,
)
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)

_CUTOFF = datetime(2026, 7, 31, tzinfo=UTC)


class _Store:
    def __init__(self, snapshot: OntologyGraphSnapshot, *, delay: float = 0.0) -> None:
        self.snapshot = snapshot
        self.delay = delay

    async def traverse(self, **_kwargs: object) -> OntologyGraphSnapshot:
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.snapshot


def _snapshot() -> OntologyGraphSnapshot:
    return OntologyGraphSnapshot(
        objects=(
            OntologyObjectRecord(
                id="resource-1",
                object_type="Resource",
                properties={"id": "resource-1"},
            ),
            OntologyObjectRecord(
                id="change-old",
                object_type="Change",
                properties={"id": "change-old", "occurred_at": _CUTOFF - timedelta(seconds=1)},
            ),
            OntologyObjectRecord(
                id="change-future",
                object_type="Change",
                properties={
                    "id": "change-future",
                    "occurred_at": _CUTOFF + timedelta(seconds=1),
                },
            ),
        ),
        links=(
            OntologyLinkRecord(
                link_type="depends_on",
                from_id="resource-1",
                to_id="change-old",
            ),
            OntologyLinkRecord(
                link_type="depends_on",
                from_id="resource-1",
                to_id="change-future",
            ),
        ),
    )


async def test_materializer_excludes_objects_and_links_after_cutoff() -> None:
    graph = await CausalIncidentGraphMaterializer(store=_Store(_snapshot())).materialize(
        incident_id="incident-1",
        root_ids=("resource-1",),
        evidence_cutoff=_CUTOFF,
    )
    assert {item.id for item in graph.snapshot.objects} == {"resource-1", "change-old"}
    assert {item.to_id for item in graph.snapshot.links} == {"change-old"}
    assert graph.complete


async def test_materializer_marks_byte_truncation_incomplete() -> None:
    graph = await CausalIncidentGraphMaterializer(store=_Store(_snapshot())).materialize(
        incident_id="incident-1",
        root_ids=("resource-1",),
        evidence_cutoff=_CUTOFF,
        bounds=IncidentGraphBounds(max_bytes=1),
    )
    assert graph.snapshot.truncated
    assert graph.incomplete_reasons == ("byte_cap_exceeded",)
    assert not graph.complete


async def test_materializer_times_out_fail_closed() -> None:
    materializer = CausalIncidentGraphMaterializer(store=_Store(_snapshot(), delay=0.05))
    with pytest.raises(TimeoutError, match="exceeded"):
        await materializer.materialize(
            incident_id="incident-1",
            root_ids=("resource-1",),
            evidence_cutoff=_CUTOFF,
            bounds=IncidentGraphBounds(timeout_seconds=0.001),
        )

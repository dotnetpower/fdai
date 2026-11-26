from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fdai.core.rca.incident_graph import (
    CausalIncidentGraph,
    CausalIncidentGraphMaterializer,
    IncidentGraphBounds,
    _encoded_graph,
)
from fdai.shared.contracts.models import OntologyDeclarationKind, OntologyTypeRef
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    STATE_FACT_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

_CUTOFF = datetime(2026, 7, 31, tzinfo=UTC)


def _fact(**changes: object) -> StateFactMetadata:
    return replace(
        StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.PROVIDER,
            source_identity="inventory-observer",
            source_revision="revision-1",
            effective_at=_CUTOFF,
            recorded_at=_CUTOFF,
            evidence_cutoff=_CUTOFF,
            freshness_ceiling_seconds=60,
            completeness=1.0,
            synthetic=False,
            evidence_refs=("evidence-1",),
        ),
        **changes,
    )


def _metadata(**changes: object) -> LinkObservationMetadata:
    return replace(
        LinkObservationMetadata(
            state_fact=_fact(),
            verification_method="independent-source",
            verified=True,
            verifier_identity="topology-verifier",
            verifier_revision="revision-1",
            verification_receipt_ref="verification-1",
            inventory_generation="generation-1",
            mapping_id="mapping-1",
            mapping_revision="revision-1",
            source_schema_version="1.0.0",
            source_schema_digest="a" * 64,
        ),
        **changes,
    )


def _object(object_id: str, **properties: object) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=object_id,
        object_type="Resource",
        properties={"observed_at": _CUTOFF, **properties},
    )


def _link(
    source: str,
    target: str,
    *,
    metadata: LinkObservationMetadata | None = None,
) -> OntologyLinkRecord:
    return OntologyLinkRecord(
        link_type="depends_on",
        from_id=source,
        to_id=target,
        properties={
            LINK_OBSERVATION_METADATA_PROPERTY: (metadata or _metadata()).to_mapping(),
        },
    )


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
        source_generation="generation-1",
        objects=(
            _object("resource-1"),
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
            _link("resource-1", "change-old"),
            _link("resource-1", "change-future"),
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
    assert not graph.complete
    assert "historical_topology_unavailable" in graph.incomplete_reasons
    assert "object_after_cutoff" in graph.incomplete_reasons
    assert graph.snapshot.source_generation == "generation-1"


async def test_materializer_requires_every_object_timestamp_before_cutoff() -> None:
    snapshot = OntologyGraphSnapshot(
        objects=(
            _object("resource-1"),
            OntologyObjectRecord(
                id="mixed-time",
                object_type="Observation",
                properties={
                    "id": "mixed-time",
                    "observed_at": _CUTOFF - timedelta(seconds=1),
                    "created_at": _CUTOFF + timedelta(seconds=1),
                },
            ),
            OntologyObjectRecord(
                id="malformed-time",
                object_type="Observation",
                properties={"id": "malformed-time", "observed_at": "not-a-timestamp"},
            ),
        ),
        links=(),
    )

    graph = await CausalIncidentGraphMaterializer(store=_Store(snapshot)).materialize(
        incident_id="incident-1",
        root_ids=("resource-1",),
        evidence_cutoff=_CUTOFF,
    )

    assert {item.id for item in graph.snapshot.objects} == {"resource-1"}
    assert "object_after_cutoff" in graph.incomplete_reasons
    assert "object_time_invalid" in graph.incomplete_reasons


async def test_materializer_marks_byte_truncation_incomplete() -> None:
    graph = await CausalIncidentGraphMaterializer(store=_Store(_snapshot())).materialize(
        incident_id="incident-1",
        root_ids=("resource-1",),
        evidence_cutoff=_CUTOFF,
        bounds=IncidentGraphBounds(max_bytes=512),
    )
    assert graph.snapshot.truncated
    assert "byte_cap_exceeded" in graph.incomplete_reasons
    assert len(_encoded_graph(graph.snapshot)) <= 512
    assert graph.snapshot.objects == ()
    assert graph.snapshot.links == ()
    assert graph.snapshot.source_generation == "generation-1"
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


async def test_materializer_preserves_incomplete_source_generation() -> None:
    source = replace(
        _snapshot(),
        source_complete=False,
        source_generation="generation-pending",
        source_incomplete_reason="refresh_partial",
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("resource-1",), evidence_cutoff=_CUTOFF
    )
    assert not graph.snapshot.source_complete
    assert graph.snapshot.source_generation == "generation-pending"
    assert graph.snapshot.source_incomplete_reason == "refresh_partial"
    assert "source_incomplete" in graph.incomplete_reasons
    assert not replace(graph, incomplete_reasons=()).complete


def test_complete_rejects_raw_incompleteness_without_materializer() -> None:
    graph = CausalIncidentGraph(
        incident_id="incident-1",
        evidence_cutoff=_CUTOFF,
        graph_revision="revision-1",
        snapshot=OntologyGraphSnapshot(source_complete=False),
    )
    assert not graph.complete


async def test_current_store_never_asserts_historical_completeness() -> None:
    source = OntologyGraphSnapshot(objects=(_object("root"),), source_generation="generation-1")
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("root",), evidence_cutoff=_CUTOFF
    )
    assert graph.snapshot.objects == source.objects
    assert graph.incomplete_reasons == ("historical_topology_unavailable",)
    assert not graph.complete


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {
                "effective_at": _CUTOFF + timedelta(seconds=1),
                "evidence_cutoff": _CUTOFF + timedelta(seconds=1),
                "recorded_at": _CUTOFF + timedelta(seconds=1),
            },
            "link_after_cutoff",
        ),
        ({"recorded_at": _CUTOFF + timedelta(seconds=1)}, "link_not_known_at_cutoff"),
        (
            {"effective_at": _CUTOFF - timedelta(seconds=61)},
            "link_stale",
        ),
        ({"completeness": 0.5}, "link_incomplete"),
        ({"synthetic": True}, "link_synthetic"),
    ],
)
async def test_materializer_rejects_unusable_link_facts(
    changes: dict[str, object], reason: str
) -> None:
    source = OntologyGraphSnapshot(
        objects=(_object("root"), _object("target")),
        links=(_link("root", "target", metadata=_metadata(state_fact=_fact(**changes))),),
        source_generation="generation-1",
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("root",), evidence_cutoff=_CUTOFF
    )
    assert graph.snapshot.links == ()
    assert {item.id for item in graph.snapshot.objects} == {"root"}
    assert reason in graph.incomplete_reasons


@pytest.mark.parametrize("conflicts", [(), ("conflict-1",)])
async def test_unverified_and_conflicting_links_are_not_eligible(
    conflicts: tuple[str, ...],
) -> None:
    # The canonical contract forbids verified conflicting links; exercise valid unverified ones.
    metadata = _metadata(
        state_fact=_fact(conflicts=conflicts),
        verified=False,
        verifier_identity=None,
        verifier_revision=None,
        verification_receipt_ref=None,
    )
    source = OntologyGraphSnapshot(
        objects=(_object("root"), _object("target")),
        links=(_link("root", "target", metadata=metadata),),
        source_generation="generation-1",
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("root",), evidence_cutoff=_CUTOFF
    )
    assert not graph.snapshot.links
    assert "link_unverified" in graph.incomplete_reasons
    if conflicts:
        assert "link_conflicting" in graph.incomplete_reasons


@pytest.mark.parametrize("metadata", [None, {}, {"state_fact": "invalid"}])
async def test_missing_or_malformed_link_metadata_is_explicit(metadata: object) -> None:
    link = _link("root", "target")
    properties = {} if metadata is None else {LINK_OBSERVATION_METADATA_PROPERTY: metadata}
    source = OntologyGraphSnapshot(
        objects=(_object("root"), _object("target")),
        links=(replace(link, properties=properties),),
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("root",), evidence_cutoff=_CUTOFF
    )
    assert not graph.snapshot.links
    expected = "link_metadata_missing" if metadata is None else "link_metadata_invalid"
    assert expected in graph.incomplete_reasons


async def test_link_generation_must_match_source_generation() -> None:
    source = OntologyGraphSnapshot(
        objects=(_object("root"), _object("target")),
        links=(_link("root", "target"),),
        source_generation="generation-2",
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("root",), evidence_cutoff=_CUTOFF
    )
    assert not graph.snapshot.links
    assert "link_generation_mismatch" in graph.incomplete_reasons


@pytest.mark.parametrize("raw_time", [None, "not-a-timestamp", "2026-07-31T00:00:00", 42])
async def test_invalid_object_time_is_not_silently_retained(raw_time: object) -> None:
    source = OntologyGraphSnapshot(objects=(_object("root", observed_at=raw_time),))
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("root",), evidence_cutoff=_CUTOFF
    )
    assert not graph.snapshot.objects
    assert "object_time_invalid" in graph.incomplete_reasons
    assert "root_missing_or_after_cutoff" in graph.incomplete_reasons


async def test_missing_object_time_is_not_invented() -> None:
    source = OntologyGraphSnapshot(
        objects=(OntologyObjectRecord(id="root", object_type="Resource", properties={}),)
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("root",), evidence_cutoff=_CUTOFF
    )
    assert not graph.snapshot.objects
    assert "object_time_missing" in graph.incomplete_reasons
    assert "source_generation_missing" in graph.incomplete_reasons


@pytest.mark.parametrize("keyed", [False, True])
async def test_canonical_object_state_fact_metadata_supplies_time(keyed: bool) -> None:
    metadata = _fact().to_mapping()
    source = OntologyGraphSnapshot(
        objects=(
            OntologyObjectRecord(
                id="root",
                object_type="Resource",
                properties={
                    STATE_FACT_METADATA_PROPERTY: {"state": metadata} if keyed else metadata,
                },
            ),
        ),
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("root",), evidence_cutoff=_CUTOFF
    )
    assert graph.snapshot.objects == source.objects
    assert "object_time_missing" not in graph.incomplete_reasons


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"recorded_at": _CUTOFF + timedelta(seconds=1)}, "object_not_known_at_cutoff"),
        ({"effective_at": _CUTOFF - timedelta(seconds=61)}, "object_stale"),
        ({"synthetic": True}, "object_synthetic"),
        ({"conflicts": ("conflict-1",)}, "object_conflicting"),
        ({"completeness": 0.5}, "object_incomplete"),
    ],
)
async def test_object_time_property_cannot_hide_unusable_state_metadata(
    changes: dict[str, object], reason: str
) -> None:
    source = OntologyGraphSnapshot(
        objects=(_object("root", **{STATE_FACT_METADATA_PROPERTY: _fact(**changes).to_mapping()}),),
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("root",), evidence_cutoff=_CUTOFF
    )
    assert not graph.snapshot.objects
    assert reason in graph.incomplete_reasons


@pytest.mark.parametrize("field", ["effective_at", "recorded_at", "evidence_cutoff"])
async def test_metadata_time_requires_timezone(field: str) -> None:
    metadata = _metadata().to_mapping()
    metadata["state_fact"][field] = "2026-07-31T00:00:00"
    source = OntologyGraphSnapshot(
        objects=(_object("root"), _object("target")),
        links=(
            replace(
                _link("root", "target"), properties={LINK_OBSERVATION_METADATA_PROPERTY: metadata}
            ),
        ),
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("root",), evidence_cutoff=_CUTOFF
    )
    assert not graph.snapshot.links
    assert "link_metadata_invalid" in graph.incomplete_reasons


async def test_rejected_intermediary_cannot_make_downstream_nodes_reachable() -> None:
    source = OntologyGraphSnapshot(
        objects=(
            _object("root"),
            _object("middle", observed_at=_CUTOFF + timedelta(seconds=1)),
            _object("end"),
        ),
        links=(_link("root", "middle"), _link("middle", "end")),
        source_generation="generation-1",
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("root",), evidence_cutoff=_CUTOFF
    )
    assert {item.id for item in graph.snapshot.objects} == {"root"}
    assert not graph.snapshot.links
    assert "objects_outside_eligible_paths" in graph.incomplete_reasons


async def test_alternate_eligible_path_preserves_reachable_nodes() -> None:
    source = OntologyGraphSnapshot(
        objects=(_object("root"), _object("middle"), _object("end")),
        links=(
            _link("root", "middle", metadata=_metadata(state_fact=_fact(synthetic=True))),
            _link("middle", "end"),
            _link("root", "end"),
        ),
        source_generation="generation-1",
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("root",), evidence_cutoff=_CUTOFF
    )
    assert {item.id for item in graph.snapshot.objects} == {"root", "middle", "end"}
    assert len(graph.snapshot.links) == 2


@pytest.mark.parametrize(
    ("bounds", "expected_ids", "reason"),
    [
        (IncidentGraphBounds(max_nodes=2), {"root", "a"}, "node_cap_exceeded"),
        (IncidentGraphBounds(max_depth=1), {"root", "a"}, "depth_cap_exceeded"),
    ],
)
async def test_store_cannot_widen_requested_node_or_depth_bounds(
    bounds: IncidentGraphBounds, expected_ids: set[str], reason: str
) -> None:
    source = OntologyGraphSnapshot(
        objects=(_object("root"), _object("a"), _object("b")),
        links=(_link("root", "a"), _link("a", "b")),
        source_generation="generation-1",
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1",
        root_ids=("root",),
        evidence_cutoff=_CUTOFF,
        bounds=bounds,
    )
    assert {item.id for item in graph.snapshot.objects} == expected_ids
    assert graph.snapshot.truncated
    assert reason in graph.incomplete_reasons
    assert all(
        link.from_id in expected_ids and link.to_id in expected_ids for link in graph.snapshot.links
    )


async def test_unrequested_link_cannot_widen_traversal() -> None:
    source = OntologyGraphSnapshot(
        objects=(_object("root"), _object("end")),
        links=(replace(_link("root", "end"), link_type="contains"),),
        source_generation="generation-1",
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1",
        root_ids=("root",),
        evidence_cutoff=_CUTOFF,
        link_types=("depends_on",),
    )
    assert {item.id for item in graph.snapshot.objects} == {"root"}
    assert "link_type_not_requested" in graph.incomplete_reasons


async def test_revision_is_order_and_timezone_independent() -> None:
    source = _snapshot()
    materializer = CausalIncidentGraphMaterializer(store=_Store(source))
    first = await materializer.materialize(
        incident_id="incident-1", root_ids=("resource-1",), evidence_cutoff=_CUTOFF
    )
    reordered = replace(source, objects=source.objects[::-1], links=source.links[::-1])
    second = await CausalIncidentGraphMaterializer(store=_Store(reordered)).materialize(
        incident_id="incident-1",
        root_ids=("resource-1", "resource-1"),
        evidence_cutoff=_CUTOFF.astimezone(timezone(timedelta(hours=9))),
    )
    assert first.graph_revision == second.graph_revision
    assert first.evidence_cutoff == second.evidence_cutoff


@pytest.mark.parametrize(
    "change",
    [
        "generation",
        "complete",
        "reason",
        "truncated",
        "receipt",
        "provenance",
        "type_ref",
        "rejected",
    ],
)
async def test_revision_binds_source_status_and_evidence_metadata(change: str) -> None:
    source = _snapshot()
    materializer = CausalIncidentGraphMaterializer(store=_Store(source))
    original = await materializer.materialize(
        incident_id="incident-1", root_ids=("resource-1",), evidence_cutoff=_CUTOFF
    )
    changed = source
    if change == "generation":
        changed = replace(source, source_generation="generation-2")
    elif change in {"complete", "reason"}:
        changed = replace(
            source,
            source_complete=False,
            source_incomplete_reason="source_unavailable" if change == "reason" else None,
        )
    elif change == "truncated":
        changed = replace(source, truncated=True)
    elif change == "receipt":
        changed = replace(
            source,
            links=(
                _link(
                    "resource-1",
                    "change-old",
                    metadata=_metadata(verification_receipt_ref="verification-2"),
                ),
                source.links[1],
            ),
        )
    elif change == "provenance":
        root = source.objects[0]
        changed = replace(
            source,
            objects=(
                replace(
                    root,
                    properties={
                        **root.properties,
                        STATE_FACT_METADATA_PROPERTY: _fact(
                            evidence_refs=("evidence-2",)
                        ).to_mapping(),
                    },
                ),
                *source.objects[1:],
            ),
        )
    elif change == "type_ref":
        changed = replace(
            source,
            objects=(
                replace(
                    source.objects[0],
                    type_ref=OntologyTypeRef(
                        kind=OntologyDeclarationKind.OBJECT,
                        name="Resource",
                        version="1.0.0",
                        catalog_digest="sha256:" + "a" * 64,
                    ),
                ),
                *source.objects[1:],
            ),
        )
    elif change == "rejected":
        changed = replace(
            source,
            objects=(
                *source.objects[:2],
                replace(source.objects[2], revision=2),
            ),
        )
    revised = await CausalIncidentGraphMaterializer(store=_Store(changed)).materialize(
        incident_id="incident-1", root_ids=("resource-1",), evidence_cutoff=_CUTOFF
    )
    assert original.graph_revision != revised.graph_revision


async def test_evidence_metadata_counts_toward_byte_bound() -> None:
    source = OntologyGraphSnapshot(
        objects=(_object("root"), _object("target")),
        links=(_link("root", "target"),),
        source_generation="generation-1",
    )
    limit = len(_encoded_graph(source))
    materializer = CausalIncidentGraphMaterializer(store=_Store(source))
    exact = await materializer.materialize(
        incident_id="incident-1",
        root_ids=("root",),
        evidence_cutoff=_CUTOFF,
        bounds=IncidentGraphBounds(max_bytes=limit),
    )
    assert exact.snapshot.objects == source.objects
    expanded = replace(
        source,
        links=(
            _link(
                "root",
                "target",
                metadata=_metadata(verification_receipt_ref="verification-" + "x" * 512),
            ),
        ),
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(expanded)).materialize(
        incident_id="incident-1",
        root_ids=("root",),
        evidence_cutoff=_CUTOFF,
        bounds=IncidentGraphBounds(max_bytes=limit),
    )
    assert graph.snapshot.truncated
    assert len(_encoded_graph(graph.snapshot)) <= limit
    assert "byte_cap_exceeded" in graph.incomplete_reasons


async def test_impossibly_small_byte_bound_fails_closed() -> None:
    with pytest.raises(ValueError, match="source metadata"):
        await CausalIncidentGraphMaterializer(store=_Store(_snapshot())).materialize(
            incident_id="incident-1",
            root_ids=("resource-1",),
            evidence_cutoff=_CUTOFF,
            bounds=IncidentGraphBounds(max_bytes=1),
        )


@pytest.mark.parametrize(
    "values",
    [
        {"max_nodes": True},
        {"max_nodes": 1.5},
        {"max_nodes": 0},
        {"max_depth": True},
        {"max_depth": 0},
        {"max_depth": 6},
        {"max_bytes": True},
        {"max_bytes": 1.5},
        {"max_bytes": 0},
        {"timeout_seconds": True},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": 0.0},
    ],
)
def test_invalid_bounds_fail_closed(values: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        IncidentGraphBounds(**values)


async def test_too_many_roots_fail_before_traversal() -> None:
    with pytest.raises(ValueError, match="root_ids exceed"):
        await CausalIncidentGraphMaterializer(store=_Store(_snapshot())).materialize(
            incident_id="incident-1",
            root_ids=("resource-1", "resource-2"),
            evidence_cutoff=_CUTOFF,
            bounds=IncidentGraphBounds(max_nodes=1),
        )


async def test_cutoff_requires_timezone() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        await CausalIncidentGraphMaterializer(store=_Store(_snapshot())).materialize(
            incident_id="incident-1",
            root_ids=("resource-1",),
            evidence_cutoff=_CUTOFF.replace(tzinfo=None),
        )


@pytest.mark.parametrize("properties", [{}, {STATE_FACT_METADATA_PROPERTY: None}])
async def test_malformed_object_metadata_is_not_an_empty_valid_fact(
    properties: dict[str, object],
) -> None:
    source = OntologyGraphSnapshot(
        objects=(_object("root", **{STATE_FACT_METADATA_PROPERTY: properties}),),
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("root",), evidence_cutoff=_CUTOFF
    )
    assert not graph.snapshot.objects
    assert "object_metadata_invalid" in graph.incomplete_reasons


async def test_future_link_property_cannot_hide_behind_valid_metadata() -> None:
    link = _link("root", "target")
    source = OntologyGraphSnapshot(
        objects=(_object("root"), _object("target")),
        links=(
            replace(
                link,
                properties={
                    **link.properties,
                    "observed_at": _CUTOFF + timedelta(seconds=1),
                },
            ),
        ),
        source_generation="generation-1",
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("root",), evidence_cutoff=_CUTOFF
    )
    assert not graph.snapshot.links
    assert "link_after_cutoff" in graph.incomplete_reasons


async def test_legacy_verified_link_retains_its_original_provenance() -> None:
    metadata = _metadata(
        inventory_generation=None,
        mapping_id=None,
        mapping_revision=None,
        source_schema_version=None,
        source_schema_digest=None,
    )
    source = OntologyGraphSnapshot(
        objects=(_object("root"), _object("target")),
        links=(_link("root", "target", metadata=metadata),),
        source_generation="generation-1",
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("root",), evidence_cutoff=_CUTOFF
    )
    assert graph.snapshot.links == source.links
    assert graph.snapshot.links[0].properties == source.links[0].properties
    assert not graph.complete


@pytest.mark.parametrize("field", ["recorded_at", "effective_at"])
async def test_top_level_object_fact_times_are_cutoff_bounded(field: str) -> None:
    source = OntologyGraphSnapshot(
        objects=(_object("root", **{field: _CUTOFF + timedelta(seconds=1)}),),
    )
    graph = await CausalIncidentGraphMaterializer(store=_Store(source)).materialize(
        incident_id="incident-1", root_ids=("root",), evidence_cutoff=_CUTOFF
    )
    assert not graph.snapshot.objects
    assert "object_after_cutoff" in graph.incomplete_reasons

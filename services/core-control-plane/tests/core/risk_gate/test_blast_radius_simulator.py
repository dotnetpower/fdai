"""Tests for the blast-radius simulator."""

from __future__ import annotations

import pytest
from fdai.core.risk_gate.blast_radius_simulator import (
    MAX_TRAVERSAL_DEPTH,
    BlastRadiusRequest,
    InMemoryOntologyGraph,
    TraversalDepthExceededError,
    UnknownLinkTypeError,
    simulate_blast_radius,
)


def _graph_chain() -> InMemoryOntologyGraph:
    """Linear chain: sub -> rg -> vnet -> subnet -> vm."""
    return InMemoryOntologyGraph(
        edges={
            ("sub", "contains"): ("rg",),
            ("rg", "contains"): ("vnet",),
            ("vnet", "contains"): ("subnet",),
            ("subnet", "contains"): ("vm",),
        },
        link_types=frozenset({"contains", "depends_on"}),
    )


def _graph_diamond() -> InMemoryOntologyGraph:
    """Diamond: A -> B, A -> C, B -> D, C -> D."""
    return InMemoryOntologyGraph(
        edges={
            ("A", "depends_on"): ("B", "C"),
            ("B", "depends_on"): ("D",),
            ("C", "depends_on"): ("D",),
        },
        link_types=frozenset({"depends_on"}),
    )


def test_bfs_reaches_full_chain_within_depth() -> None:
    report = simulate_blast_radius(
        _graph_chain(),
        BlastRadiusRequest(target="sub", traversal_depth=4, traversal_links=("contains",)),
    )
    ids = [n.resource_id for n in report.reached]
    assert ids == ["sub", "rg", "vnet", "subnet", "vm"]
    depths = {n.resource_id: n.depth for n in report.reached}
    assert depths["vm"] == 4
    assert report.affected_count() == 4
    assert report.truncated_at_depth is False


def test_bfs_truncates_at_depth_cap() -> None:
    report = simulate_blast_radius(
        _graph_chain(),
        BlastRadiusRequest(target="sub", traversal_depth=2, traversal_links=("contains",)),
    )
    ids = {n.resource_id for n in report.reached}
    # sub -> rg -> vnet reached; subnet + vm truncated by depth.
    assert ids == {"sub", "rg", "vnet"}
    assert report.affected_count() == 2
    assert report.truncated_at_depth is True


def test_bfs_deduplicates_diamond_and_records_first_hop() -> None:
    report = simulate_blast_radius(
        _graph_diamond(),
        BlastRadiusRequest(target="A", traversal_depth=2, traversal_links=("depends_on",)),
    )
    ids = {n.resource_id: n.depth for n in report.reached}
    assert ids == {"A": 0, "B": 1, "C": 1, "D": 2}
    # D only appears once even though two paths reach it.
    d_count = sum(1 for n in report.reached if n.resource_id == "D")
    assert d_count == 1


def test_bfs_records_every_traversed_edge_including_diamond() -> None:
    report = simulate_blast_radius(
        _graph_diamond(),
        BlastRadiusRequest(target="A", traversal_depth=2, traversal_links=("depends_on",)),
    )
    # Four edges: A->B, A->C, B->D, C->D. Order is depth-first-by-BFS,
    # so the two hops at depth 1 come before the two at depth 2.
    edge_tuples = [(e.source, e.target, e.link_type, e.depth) for e in report.edges]
    assert edge_tuples == [
        ("A", "B", "depends_on", 1),
        ("A", "C", "depends_on", 1),
        ("B", "D", "depends_on", 2),
        ("C", "D", "depends_on", 2),
    ]


def test_bfs_respects_link_type_filter() -> None:
    graph = InMemoryOntologyGraph(
        edges={
            ("root", "contains"): ("child",),
            ("root", "depends_on"): ("dependency",),
        },
        link_types=frozenset({"contains", "depends_on"}),
    )
    only_contains = simulate_blast_radius(
        graph,
        BlastRadiusRequest(target="root", traversal_depth=1, traversal_links=("contains",)),
    )
    assert {n.resource_id for n in only_contains.reached} == {"root", "child"}

    only_depends = simulate_blast_radius(
        graph,
        BlastRadiusRequest(target="root", traversal_depth=1, traversal_links=("depends_on",)),
    )
    assert {n.resource_id for n in only_depends.reached} == {"root", "dependency"}


def test_unknown_link_type_fails_closed() -> None:
    with pytest.raises(UnknownLinkTypeError):
        simulate_blast_radius(
            _graph_chain(),
            BlastRadiusRequest(
                target="sub",
                traversal_depth=1,
                traversal_links=("nonexistent_link",),
            ),
        )


def test_traversal_depth_capped_at_module_constant() -> None:
    with pytest.raises(TraversalDepthExceededError):
        simulate_blast_radius(
            _graph_chain(),
            BlastRadiusRequest(
                target="sub",
                traversal_depth=MAX_TRAVERSAL_DEPTH + 1,
                traversal_links=("contains",),
            ),
        )


def test_traversal_depth_at_cap_is_allowed() -> None:
    # Depth == cap MUST be accepted; the cap is inclusive.
    simulate_blast_radius(
        _graph_chain(),
        BlastRadiusRequest(
            target="sub",
            traversal_depth=MAX_TRAVERSAL_DEPTH,
            traversal_links=("contains",),
        ),
    )


def test_zero_depth_rejected() -> None:
    with pytest.raises(ValueError):
        simulate_blast_radius(
            _graph_chain(),
            BlastRadiusRequest(target="sub", traversal_depth=0, traversal_links=("contains",)),
        )


def test_empty_traversal_links_rejected() -> None:
    with pytest.raises(ValueError):
        simulate_blast_radius(
            _graph_chain(),
            BlastRadiusRequest(target="sub", traversal_depth=1, traversal_links=()),
        )


def test_report_as_json_is_client_safe() -> None:
    report = simulate_blast_radius(
        _graph_chain(),
        BlastRadiusRequest(target="sub", traversal_depth=2, traversal_links=("contains",)),
    )
    payload = report.as_json()
    # Round-trip through json module to prove it is truly serialisable.
    import json

    reloaded = json.loads(json.dumps(payload))
    assert reloaded["target"] == "sub"
    assert reloaded["traversal_depth"] == 2
    assert reloaded["affected_count"] == 2
    assert reloaded["truncated_at_depth"] is True
    assert len(reloaded["reached"]) == 3
    assert all("resource_id" in n for n in reloaded["reached"])


def test_determinism_same_input_same_output() -> None:
    graph = _graph_diamond()
    req = BlastRadiusRequest(target="A", traversal_depth=3, traversal_links=("depends_on",))
    first = simulate_blast_radius(graph, req)
    second = simulate_blast_radius(graph, req)
    assert first.as_json() == second.as_json()


def test_target_with_no_outgoing_edges() -> None:
    graph = InMemoryOntologyGraph(edges={}, link_types=frozenset({"contains"}))
    report = simulate_blast_radius(
        graph,
        BlastRadiusRequest(target="lone", traversal_depth=3, traversal_links=("contains",)),
    )
    assert [n.resource_id for n in report.reached] == ["lone"]
    assert report.affected_count() == 0
    assert report.edges == ()
    assert report.truncated_at_depth is False

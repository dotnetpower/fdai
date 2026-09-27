"""Focused regressions for terminal manifest defects found by the seeded parity generator."""

from __future__ import annotations

import pytest
from fdai_service_contracts.ontology_query import EvidenceAuthority
from tests.integration.test_semantic_evidence_manifest_parity import (
    SEED,
    Node,
    Pipeline,
    Turn,
    generate,
    seeded,
    unique_refs,
    violations,
)

FAILURE_MODES = ("held", "failed")


@pytest.mark.parametrize("failure", FAILURE_MODES)
async def test_held_execution_never_truncates_the_terminal_manifest(failure: str) -> None:
    turn = generate(seeded(SEED), 0, "held_overflow", failure=failure)
    projection, done = await Pipeline().run(turn)

    assert [node.outcome for node in turn.nodes] == ["ok", "ok", failure]
    assert len(unique_refs(list(turn.nodes[:2]))) > 12
    assert violations(turn, projection, done) == []
    assert projection["semantic_result"]["unavailable_reason"] == (
        "authoritative_evidence_unavailable"
    )
    assert "intent_graph_evidence" not in projection["semantic_result"]
    assert done["verification"]["status"] == "unverified"


async def test_receipt_reference_length_bound_is_typed_at_the_manifest_boundary() -> None:
    pipeline = Pipeline()
    bounded = generate(seeded(SEED), 0, "max_ref_chars")
    overlong = generate(seeded(SEED), 1, "long_ref")

    answered, answered_done = await pipeline.run(bounded)
    held, held_done = await pipeline.run(overlong)

    assert violations(bounded, answered, answered_done) == []
    assert violations(overlong, held, held_done) == []
    assert "근" * 256 in answered["semantic_result"]["evidence_refs"]
    assert held["semantic_result"]["reason_code"] == "semantic_evidence_incomplete"
    assert held_done["verification"]["evidence_refs"] == []


@pytest.mark.parametrize("failure", FAILURE_MODES)
async def test_overlong_reference_in_a_held_execution_holds_with_a_typed_reason(
    failure: str,
) -> None:
    authority = EvidenceAuthority.SERVER_INVENTORY_GRAPH
    nodes = (
        Node("resources-1", ("evidence:inventory", "근" * 300), authority),
        Node("resources-2", ("evidence:unread",), authority, failure),
    )
    turn = Turn(2, "long_ref", "ko", nodes, authority, ())
    projection, done = await Pipeline().run(turn)

    assert violations(turn, projection, done) == []
    assert projection["semantic_result"]["unavailable_reason"] == (
        "authoritative_evidence_unavailable"
    )
    assert done["verification"]["evidence_refs"] == []

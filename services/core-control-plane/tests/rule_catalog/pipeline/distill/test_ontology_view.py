"""Tests for the document-text-free ontology reviewer projection."""

from __future__ import annotations

from fdai.rule_catalog.pipeline.distill.ontology_view import build_ontology_review_view

from tests.rule_catalog.pipeline.distill.test_ontology_evaluation import _package


def test_review_view_exposes_graph_diff_and_gate_receipts() -> None:
    view = build_ontology_review_view(_package())
    proposal = view["proposals"][0]
    assert proposal["operation"] == "update"
    assert proposal["target_identity"] == "service:a"
    assert proposal["properties"] == [{"name": "owner_ref", "value": "team:a"}]
    assert proposal["gates"][0] == {
        "gate": "shape",
        "outcome": "pass",
        "reason_codes": [],
        "evidence_refs": [],
    }


def test_review_view_contains_evidence_location_but_not_document_text() -> None:
    view = build_ontology_review_view(_package())
    claim = view["claims"][0]
    assert claim["line_start"] == 1
    assert claim["line_end"] == 1
    assert "text" not in claim
    assert "Checkout service" not in repr(view)


def test_review_view_is_replay_stable() -> None:
    assert build_ontology_review_view(_package()) == build_ontology_review_view(_package())

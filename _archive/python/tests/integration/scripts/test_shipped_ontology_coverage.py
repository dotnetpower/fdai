"""Shipped structural fixtures keep current, read-only bindings without live claims."""

import runpy
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def test_shipped_answered_fixtures_match_current_reader_structure() -> None:
    checker = runpy.run_path(
        str(_ROOT / "scripts/quality/architecture/check-ontology-query-coverage.py")
    )
    questions = checker["_questions"]()
    structural = checker["_structural_receipts"]()
    reader = structural[0]
    answered = [question for question in questions if question.disposition == "answered"]
    assert answered
    for question in answered:
        assert question.receipt_source == "deterministic_fixture"
        assert question.ontology_release_digest == reader.ontology_release_digest
        assert question.principal_manifest_digest == reader.manifest_digest
    receipt = checker["evaluate_ontology_query_coverage"](
        structural_receipts=structural, questions=questions
    )
    checker["require_ontology_query_coverage"](receipt)
    assert receipt.production_ready is False

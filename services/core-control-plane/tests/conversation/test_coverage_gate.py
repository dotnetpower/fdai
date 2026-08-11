"""Continuous ontology query coverage gate tests."""

from __future__ import annotations

import pytest
from fdai.core.conversation.coverage_gate import (
    QuestionDispositionRecord,
    evaluate_ontology_query_coverage,
    require_ontology_query_coverage,
)
from fdai_service_contracts.ontology_query import StructuralCoverageReceipt, content_digest

DIGEST = "sha256:" + ("a" * 64)


def _structural() -> StructuralCoverageReceipt:
    body = {
        "schema_version": "1.0.0",
        "ontology_release_digest": DIGEST,
        "principal_scope_digest": DIGEST,
        "readable_declaration_count": 2,
        "descriptor_count": 2,
        "unavailable_declaration_ids": (),
        "manifest_digest": DIGEST,
        "complete": True,
    }
    return StructuralCoverageReceipt(**body, receipt_digest=content_digest(body))


def test_gate_reports_answer_coverage_by_cohort_without_requiring_universal_answers() -> None:
    receipt = evaluate_ontology_query_coverage(
        structural_receipts=(_structural(),),
        questions=(
            QuestionDispositionRecord("answered", "exact-en", "answered"),
            QuestionDispositionRecord("ambiguous", "ambiguous-en", "clarification"),
            QuestionDispositionRecord("missing", "evidence-gap", "held"),
        ),
    )

    require_ontology_query_coverage(receipt)
    assert receipt.passed is True
    assert receipt.answer_counts_by_cohort == {
        "ambiguous-en": 0,
        "evidence-gap": 0,
        "exact-en": 1,
    }


def test_gate_rejects_legacy_routing_or_unsupported_claims() -> None:
    receipt = evaluate_ontology_query_coverage(
        structural_receipts=(_structural(),),
        questions=(
            QuestionDispositionRecord(
                "legacy",
                "exact-en",
                "answered",
                unsupported_claim_count=1,
                used_legacy_ordinary_language_route=True,
            ),
        ),
    )

    assert receipt.passed is False
    with pytest.raises(ValueError, match="release gate failed"):
        require_ontology_query_coverage(receipt)

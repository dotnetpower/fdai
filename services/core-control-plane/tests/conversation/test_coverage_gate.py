"""Continuous ontology query coverage gate tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.conversation.coverage_gate import (
    QuestionDispositionRecord,
    SemanticRoute,
    UnavailableReason,
    evaluate_ontology_query_coverage,
    require_ontology_query_coverage,
)
from fdai.core.conversation.epistemic_coverage import (
    EpistemicQuestionRecord,
    EpistemicStatus,
    QuestionUniverseReceipt,
    evaluate_epistemic_coverage,
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
    return StructuralCoverageReceipt(
        schema_version="1.0.0",
        ontology_release_digest=DIGEST,
        principal_scope_digest=DIGEST,
        readable_declaration_count=2,
        descriptor_count=2,
        unavailable_declaration_ids=(),
        manifest_digest=DIGEST,
        complete=True,
        receipt_digest=content_digest(body),
    )


def _digest(marker: str) -> str:
    return "sha256:" + (marker * 64)


def _answered(question_id: str, marker: str) -> QuestionDispositionRecord:
    return QuestionDispositionRecord(
        question_id=question_id,
        cohort="exact-en",
        disposition="answered",
        receipt_id=f"cross-service-e2e:{question_id}",
        receipt_source="cross_service_e2e",
        reason_code="semantic_execution_completed",
        semantic_route="verified_query_plan",
        ontology_release_digest=_digest("a"),
        principal_manifest_digest=DIGEST,
        plan_digest=_digest(marker),
        execution_receipt_digest=_digest(marker),
        evidence_refs=(f"evidence:{question_id}",),
        checks_completed=2,
        checks_total=2,
    )


def _fixture_answered(question_id: str, marker: str) -> QuestionDispositionRecord:
    return replace(
        _answered(question_id, marker),
        receipt_id=f"deterministic-fixture:{question_id}",
        receipt_source="deterministic_fixture",
    )


def _nonanswered(
    question_id: str,
    cohort: str,
    disposition: str,
    *,
    semantic_route: SemanticRoute | None = None,
    unavailable_reason: UnavailableReason | None = None,
) -> QuestionDispositionRecord:
    return QuestionDispositionRecord(
        question_id=question_id,
        cohort=cohort,
        disposition=disposition,
        receipt_id=f"cross-service-e2e:{question_id}",
        receipt_source="cross_service_e2e",
        reason_code=(unavailable_reason or f"semantic_{disposition}"),
        semantic_route=semantic_route,
        unavailable_reason=unavailable_reason,
    )


def test_gate_reports_answer_coverage_by_cohort_without_requiring_universal_answers() -> None:
    receipt = evaluate_ontology_query_coverage(
        structural_receipts=(_structural(),),
        questions=(
            _answered("answered", "c"),
            _nonanswered(
                "ambiguous",
                "ambiguous-en",
                "clarification",
                semantic_route="semantic_clarification",
            ),
            _nonanswered(
                "missing",
                "evidence-gap",
                "held",
                unavailable_reason="historical_evidence_unavailable",
            ),
        ),
    )

    require_ontology_query_coverage(receipt)
    assert receipt.passed is True
    assert receipt.production_ready is False
    assert receipt.answer_counts_by_cohort == {
        "ambiguous-en": 0,
        "evidence-gap": 0,
        "exact-en": 1,
    }


def test_gate_rejects_legacy_routing_or_unsupported_claims() -> None:
    invalid = replace(
        _answered("legacy", "d"),
        unsupported_claim_count=1,
        used_legacy_ordinary_language_route=True,
    )
    receipt = evaluate_ontology_query_coverage(
        structural_receipts=(_structural(),),
        questions=(invalid,),
    )

    assert receipt.passed is False
    with pytest.raises(ValueError, match="release gate failed"):
        require_ontology_query_coverage(receipt)


def test_old_answered_fixture_without_receipts_fails_closed() -> None:
    with pytest.raises(ValueError, match="question receipt id"):
        QuestionDispositionRecord("answered", "exact-en", "answered")


def test_held_question_may_omit_execution_receipts() -> None:
    held = _nonanswered(
        "missing-history",
        "evidence-gap",
        "held",
        unavailable_reason="historical_evidence_unavailable",
    )

    receipt = evaluate_ontology_query_coverage(
        structural_receipts=(_structural(),),
        questions=(held,),
    )

    require_ontology_query_coverage(receipt)
    assert receipt.passed is True
    assert held.execution_receipt_digest is None


def test_fixture_receipts_pass_structure_without_claiming_production_readiness() -> None:
    receipt = evaluate_ontology_query_coverage(
        structural_receipts=(_structural(),),
        questions=(_fixture_answered("fixture", "b"),),
    )

    require_ontology_query_coverage(receipt)
    assert receipt.passed is True
    assert receipt.production_ready is False
    with pytest.raises(ValueError, match="lacks cross-service or live production proof"):
        require_ontology_query_coverage(receipt, require_production_ready=True)


def test_answered_question_rejects_malformed_execution_receipt() -> None:
    with pytest.raises(ValueError, match="canonical SHA-256"):
        replace(_answered("malformed", "e"), execution_receipt_digest="sha256:not-a-digest")


def test_gate_rejects_duplicate_execution_receipts() -> None:
    first = _answered("first", "e")
    second = replace(
        _answered("second", "f"),
        execution_receipt_digest=first.execution_receipt_digest,
    )

    with pytest.raises(ValueError, match="execution receipt digests MUST be unique"):
        evaluate_ontology_query_coverage(
            structural_receipts=(_structural(),),
            questions=(first, second),
        )


def test_gate_rejects_duplicate_question_receipt_identities() -> None:
    first = _answered("first", "e")
    second = replace(_answered("second", "f"), receipt_id=first.receipt_id)

    with pytest.raises(ValueError, match="question receipt ids MUST be unique"):
        evaluate_ontology_query_coverage(
            structural_receipts=(_structural(),),
            questions=(first, second),
        )


def test_gate_rejects_answered_receipt_from_another_release() -> None:
    answered = replace(_answered("stale", "e"), ontology_release_digest=_digest("f"))

    with pytest.raises(ValueError, match="match the structural release"):
        evaluate_ontology_query_coverage(
            structural_receipts=(_structural(),),
            questions=(answered,),
        )


def test_production_readiness_requires_matching_epistemic_closure() -> None:
    universe = QuestionUniverseReceipt.build(
        ontology_release_digest=DIGEST,
        principal_manifest_digests=(DIGEST,),
        grammar_digest=_digest("9"),
        case_ids=("answered",),
    )
    question = EpistemicQuestionRecord(
        question_id="answered",
        transport_disposition="answered",
        epistemic_status=EpistemicStatus.VERIFIED_ANSWER,
        question_universe_digest=universe.receipt_digest,
        understanding_receipt_digest=_digest("7"),
        completeness_receipt_digest=_digest("8"),
        claim_proof_receipt_digests=(_digest("6"),),
        source_span_coverage=1.0,
        semantic_atom_coverage=1.0,
    )
    epistemic = evaluate_epistemic_coverage(universe=universe, questions=(question,))

    receipt = evaluate_ontology_query_coverage(
        structural_receipts=(_structural(),),
        questions=(_answered("answered", "c"),),
        epistemic_coverage=epistemic,
    )

    require_ontology_query_coverage(receipt, require_production_ready=True)
    assert receipt.epistemic_coverage_receipt_digest == epistemic.receipt_digest
    assert receipt.production_ready is True

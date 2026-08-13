"""Finite question-universe and epistemic-closure release tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.conversation.epistemic_coverage import (
    EpistemicQuestionRecord,
    EpistemicStatus,
    QuestionUniverseReceipt,
    evaluate_epistemic_coverage,
    require_epistemic_coverage,
)

DIGEST_A = "sha256:" + ("a" * 64)
DIGEST_B = "sha256:" + ("b" * 64)
DIGEST_C = "sha256:" + ("c" * 64)
DIGEST_D = "sha256:" + ("d" * 64)
DIGEST_E = "sha256:" + ("e" * 64)


def _universe(*case_ids: str) -> QuestionUniverseReceipt:
    return QuestionUniverseReceipt.build(
        ontology_release_digest=DIGEST_A,
        principal_manifest_digests=(DIGEST_B,),
        grammar_digest=DIGEST_C,
        case_ids=case_ids,
    )


def _question(
    question_id: str,
    universe: QuestionUniverseReceipt,
    *,
    status: EpistemicStatus = EpistemicStatus.VERIFIED_ANSWER,
    disposition: str = "answered",
) -> EpistemicQuestionRecord:
    return EpistemicQuestionRecord(
        question_id=question_id,
        transport_disposition=disposition,
        epistemic_status=status,
        question_universe_digest=universe.receipt_digest,
        understanding_receipt_digest=DIGEST_D,
        completeness_receipt_digest=DIGEST_E,
        claim_proof_receipt_digests=(DIGEST_A,),
        source_span_coverage=1.0,
        semantic_atom_coverage=1.0,
    )


def test_gate_closes_answer_and_unknown_without_forcing_facts() -> None:
    universe = _universe("answer", "unknown")
    unknown = replace(
        _question("unknown", universe),
        transport_disposition="held",
        epistemic_status=EpistemicStatus.UNKNOWN_INCOMPLETE,
        claim_proof_receipt_digests=(),
    )

    receipt = evaluate_epistemic_coverage(
        universe=universe,
        questions=(_question("answer", universe), unknown),
    )

    require_epistemic_coverage(receipt)
    assert receipt.expected_case_count == 2
    assert receipt.closed_case_count == 2
    assert receipt.passed is True


def test_gate_rejects_missing_question_universe_case() -> None:
    universe = _universe("first", "second")

    with pytest.raises(ValueError, match="exactly cover the question universe"):
        evaluate_epistemic_coverage(
            universe=universe,
            questions=(_question("first", universe),),
        )


def test_answer_requires_complete_interpretation_and_claim_proof() -> None:
    universe = _universe("answer")

    with pytest.raises(ValueError, match="complete interpretation"):
        replace(_question("answer", universe), source_span_coverage=0.9)
    with pytest.raises(ValueError, match="requires claim proof"):
        replace(_question("answer", universe), claim_proof_receipt_digests=())


def test_verified_empty_requires_closed_population_proof() -> None:
    universe = _universe("empty")

    with pytest.raises(ValueError, match="closed-population proof"):
        _question(
            "empty",
            universe,
            status=EpistemicStatus.VERIFIED_EMPTY,
        )

    empty = replace(
        _question("empty", universe),
        epistemic_status=EpistemicStatus.VERIFIED_EMPTY,
        closed_population_receipt_digest=DIGEST_C,
    )
    receipt = evaluate_epistemic_coverage(universe=universe, questions=(empty,))
    assert receipt.passed is True


def test_gate_rejects_hidden_scope_leak() -> None:
    universe = _universe("leak")
    leaked = replace(_question("leak", universe), hidden_scope_leak_count=1)

    receipt = evaluate_epistemic_coverage(universe=universe, questions=(leaked,))

    assert receipt.violation_count == 1
    assert receipt.passed is False
    with pytest.raises(ValueError, match="release gate failed"):
        require_epistemic_coverage(receipt)


def test_epistemic_status_must_match_transport_disposition() -> None:
    universe = _universe("mismatch")

    with pytest.raises(ValueError, match="does not match"):
        _question(
            "mismatch",
            universe,
            status=EpistemicStatus.UNKNOWN_STALE,
            disposition="answered",
        )


def test_question_universe_receipt_rejects_tampered_identity_and_bounds() -> None:
    universe = _universe("answer")

    with pytest.raises(ValueError, match="canonical SHA-256"):
        replace(universe, ontology_release_digest="invalid")
    with pytest.raises(ValueError, match="principal_manifest_digests MUST be non-empty"):
        replace(universe, principal_manifest_digests=())
    with pytest.raises(ValueError, match="principal_manifest_digests MUST be unique and ordered"):
        replace(universe, principal_manifest_digests=(DIGEST_C, DIGEST_B))
    with pytest.raises(ValueError, match="case_ids MUST be unique and ordered"):
        replace(universe, case_ids=("answer", "answer"))
    with pytest.raises(ValueError, match="contain a case or typed exclusion"):
        replace(universe, case_ids=())
    with pytest.raises(ValueError, match="cases and exclusions MUST be disjoint"):
        replace(universe, excluded_case_ids=("answer",))
    with pytest.raises(ValueError, match="exceeds its case bound"):
        replace(universe, case_ids=tuple(f"q-{index:05d}" for index in range(10_001)))
    with pytest.raises(ValueError, match="digest does not match"):
        replace(universe, receipt_digest=DIGEST_D)


def test_epistemic_question_rejects_malformed_proofs_and_metrics() -> None:
    universe = _universe("answer")
    question = _question("answer", universe)

    with pytest.raises(ValueError, match="question_id MUST contain bounded ids"):
        replace(question, question_id="")
    with pytest.raises(ValueError, match="question proof digest MUST be a canonical"):
        replace(question, understanding_receipt_digest="invalid")
    with pytest.raises(ValueError, match="claim proof receipt count exceeds its bound"):
        replace(question, claim_proof_receipt_digests=(DIGEST_A,) * 65)
    with pytest.raises(ValueError, match="claim_proof_receipt_digests MUST be unique and ordered"):
        replace(question, claim_proof_receipt_digests=(DIGEST_B, DIGEST_A))
    with pytest.raises(ValueError, match="source_span_coverage MUST be finite"):
        replace(question, source_span_coverage=float("nan"))
    with pytest.raises(ValueError, match="violation counts MUST be non-negative"):
        replace(question, ungrounded_claim_count=-1)
    with pytest.raises(ValueError, match="requires understanding proof"):
        replace(question, understanding_receipt_digest=None)

    unknown = replace(
        question,
        transport_disposition="held",
        epistemic_status=EpistemicStatus.UNKNOWN_INCOMPLETE,
        claim_proof_receipt_digests=(),
    )
    with pytest.raises(ValueError, match="requires completeness proof"):
        replace(unknown, completeness_receipt_digest=None)


def test_evaluator_rejects_duplicate_and_wrong_universe_records() -> None:
    universe = _universe("answer")
    question = _question("answer", universe)

    with pytest.raises(ValueError, match="question ids MUST be unique"):
        evaluate_epistemic_coverage(universe=universe, questions=(question, question))
    with pytest.raises(ValueError, match="bind the exact question universe"):
        evaluate_epistemic_coverage(
            universe=universe,
            questions=(replace(question, question_universe_digest=DIGEST_E),),
        )

    cancelled_universe = _universe("cancelled")
    cancelled = EpistemicQuestionRecord(
        question_id="cancelled",
        transport_disposition="cancelled",
        epistemic_status=EpistemicStatus.CANCELLED,
        question_universe_digest=cancelled_universe.receipt_digest,
    )
    receipt = evaluate_epistemic_coverage(
        universe=cancelled_universe,
        questions=(cancelled,),
    )
    assert receipt.passed is True


def test_epistemic_coverage_receipt_rejects_tampered_counts_and_digest() -> None:
    universe = _universe("answer")
    receipt = evaluate_epistemic_coverage(
        universe=universe,
        questions=(_question("answer", universe),),
    )

    with pytest.raises(ValueError, match="expected case count is outside"):
        replace(receipt, expected_case_count=-1)
    with pytest.raises(ValueError, match="closed case count is outside"):
        replace(receipt, closed_case_count=2)
    with pytest.raises(ValueError, match="violation count MUST be non-negative"):
        replace(receipt, violation_count=-1)
    with pytest.raises(ValueError, match="pass state does not match"):
        replace(receipt, passed=False)
    with pytest.raises(ValueError, match="digest does not match"):
        replace(receipt, receipt_digest=DIGEST_B)

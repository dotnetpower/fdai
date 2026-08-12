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

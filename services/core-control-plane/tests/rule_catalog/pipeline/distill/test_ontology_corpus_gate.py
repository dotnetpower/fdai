"""Tests for partition-preserving ontology corpus release gates."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.rule_catalog.pipeline.distill.ontology_corpus_gate import (
    CorpusGateDecision,
    CorpusGatePolicy,
    CorpusPartition,
    PartitionEvidence,
    assess_corpus_gate,
)

_MARKDOWN_EN = CorpusPartition(source_format="markdown", language="en")
_PDF_KO = CorpusPartition(source_format="pdf", language="ko")


def _passing_evidence(partition: CorpusPartition) -> PartitionEvidence:
    return PartitionEvidence(
        partition=partition,
        case_count=50,
        extraction_success_count=50,
        detected_claim_count=100,
        accounted_detected_claim_count=100,
        expected_critical_claim_count=100,
        mapped_critical_claim_count=98,
        predicted_entity_count=100,
        correct_entity_count=98,
        predicted_link_count=100,
        correct_link_count=98,
        citation_count=100,
        citation_error_count=0,
        parser_rejection_count=0,
        provider_abstention_count=0,
        replay_mismatch_count=0,
        semantic_error_count=0,
        latency_observation_count=50,
        latency_total_ms=500.0,
        cost_observation_count=50,
        cost_total_microunits=250,
    )


def test_complete_required_partitions_pass_without_granting_authority() -> None:
    assessment = assess_corpus_gate(
        (_passing_evidence(_MARKDOWN_EN), _passing_evidence(_PDF_KO)),
        required_partitions=(_MARKDOWN_EN, _PDF_KO),
    )

    assert assessment.decision is CorpusGateDecision.PASS
    assert assessment.reason_codes == ()
    assert assessment.review_only is True
    assert assessment.authority_neutral is True
    assert tuple(item.partition for item in assessment.partitions) == (
        _MARKDOWN_EN,
        _PDF_KO,
    )


def test_zero_candidate_abstention_is_safe_but_not_extraction_success() -> None:
    empty = PartitionEvidence(
        partition=_MARKDOWN_EN,
        case_count=1,
        extraction_success_count=0,
        detected_claim_count=2,
        accounted_detected_claim_count=2,
        expected_critical_claim_count=2,
        mapped_critical_claim_count=0,
        predicted_entity_count=0,
        correct_entity_count=0,
        predicted_link_count=0,
        correct_link_count=0,
        citation_count=0,
        citation_error_count=0,
        parser_rejection_count=0,
        provider_abstention_count=1,
        replay_mismatch_count=0,
        semantic_error_count=0,
        latency_observation_count=1,
        latency_total_ms=1.0,
        cost_observation_count=1,
        cost_total_microunits=0,
    )

    assessment = assess_corpus_gate(
        (empty,),
        required_partitions=(_MARKDOWN_EN,),
    )

    assert assessment.decision is CorpusGateDecision.REVIEW
    assert assessment.partitions[0].metrics.extraction_success_rate == 0.0
    assert assessment.reason_codes == (
        "markdown:en:no_extraction_success",
        "markdown:en:critical_recall_below_threshold",
        "markdown:en:provider_abstention",
    )


@pytest.mark.parametrize(
    ("changes", "reason_code"),
    [
        ({"citation_count": 0}, "markdown:en:no_citations"),
        (
            {
                "predicted_entity_count": 0,
                "correct_entity_count": 0,
                "predicted_link_count": 0,
                "correct_link_count": 0,
            },
            "markdown:en:no_ontology_predictions",
        ),
    ],
)
def test_success_cannot_pass_without_citations_or_predictions(
    changes: dict[str, int], reason_code: str
) -> None:
    assessment = assess_corpus_gate(
        (replace(_passing_evidence(_MARKDOWN_EN), **changes),),
        required_partitions=(_MARKDOWN_EN,),
    )

    assert assessment.decision is CorpusGateDecision.REVIEW
    assert reason_code in assessment.reason_codes


def test_partition_without_expected_critical_claims_is_rejected() -> None:
    with pytest.raises(ValueError, match="expected critical claims"):
        replace(
            _passing_evidence(_MARKDOWN_EN),
            expected_critical_claim_count=0,
            mapped_critical_claim_count=0,
        )


def test_weak_partition_cannot_be_hidden_by_a_strong_partition() -> None:
    weak = replace(
        _passing_evidence(_PDF_KO),
        mapped_critical_claim_count=97,
    )

    assessment = assess_corpus_gate(
        (_passing_evidence(_MARKDOWN_EN), weak),
        required_partitions=(_MARKDOWN_EN, _PDF_KO),
    )

    assert assessment.decision is CorpusGateDecision.REVIEW
    assert assessment.partitions[0].decision is CorpusGateDecision.PASS
    assert assessment.partitions[1].decision is CorpusGateDecision.REVIEW
    assert assessment.reason_codes == ("pdf:ko:critical_recall_below_threshold",)


def test_missing_required_partition_routes_to_review() -> None:
    assessment = assess_corpus_gate(
        (_passing_evidence(_MARKDOWN_EN),),
        required_partitions=(_MARKDOWN_EN, _PDF_KO),
    )

    assert assessment.decision is CorpusGateDecision.REVIEW
    assert assessment.reason_codes == ("pdf:ko:missing_partition",)


@pytest.mark.parametrize(
    ("source_format", "language"),
    [("PDF", "en"), ("pdf", ""), ("x" * 65, "en")],
)
def test_partition_rejects_invalid_bounded_tokens(
    source_format: str,
    language: str,
) -> None:
    with pytest.raises(ValueError, match="bounded lowercase token"):
        CorpusPartition(source_format=source_format, language=language)


@pytest.mark.parametrize(
    ("changes", "reason_code"),
    [
        ({"citation_error_count": 1}, "markdown:en:citation_error"),
        ({"replay_mismatch_count": 1}, "markdown:en:replay_mismatch"),
        ({"semantic_error_count": 1}, "markdown:en:semantic_error"),
        (
            {"correct_entity_count": 97},
            "markdown:en:entity_precision_below_threshold",
        ),
        (
            {"correct_link_count": 97},
            "markdown:en:link_precision_below_threshold",
        ),
    ],
)
def test_citation_replay_and_semantic_failures_deny(
    changes: dict[str, int],
    reason_code: str,
) -> None:
    failed = replace(_passing_evidence(_MARKDOWN_EN), **changes)

    assessment = assess_corpus_gate(
        (failed,),
        required_partitions=(_MARKDOWN_EN,),
    )

    assert assessment.decision is CorpusGateDecision.DENY
    assert reason_code in assessment.reason_codes


def test_parser_rejection_and_missing_measurement_evidence_route_to_review() -> None:
    incomplete = replace(
        _passing_evidence(_MARKDOWN_EN),
        parser_rejection_count=1,
        latency_observation_count=0,
        latency_total_ms=0.0,
        cost_observation_count=0,
        cost_total_microunits=0,
    )

    assessment = assess_corpus_gate(
        (incomplete,),
        required_partitions=(_MARKDOWN_EN,),
    )

    assert assessment.decision is CorpusGateDecision.REVIEW
    assert assessment.reason_codes == (
        "markdown:en:parser_rejection",
        "markdown:en:missing_latency_evidence",
        "markdown:en:missing_cost_evidence",
    )


def test_exact_thresholds_pass_and_one_count_below_fails() -> None:
    policy = CorpusGatePolicy(
        min_detected_claim_accounting=1.0,
        min_mapped_critical_recall=0.98,
        min_entity_precision=0.98,
        min_link_precision=0.98,
        max_citation_error_rate=0.01,
        max_citation_error_count=1,
    )
    exact = replace(
        _passing_evidence(_MARKDOWN_EN),
        citation_error_count=1,
    )

    passed = assess_corpus_gate(
        (exact,),
        required_partitions=(_MARKDOWN_EN,),
        policy=policy,
    )
    below = assess_corpus_gate(
        (replace(exact, mapped_critical_claim_count=97),),
        required_partitions=(_MARKDOWN_EN,),
        policy=policy,
    )

    assert passed.decision is CorpusGateDecision.PASS
    assert passed.partitions[0].metrics.citation_error_rate == 0.01
    assert below.decision is CorpusGateDecision.REVIEW


def test_detected_claim_accounting_below_threshold_routes_to_review() -> None:
    incomplete = replace(
        _passing_evidence(_MARKDOWN_EN),
        accounted_detected_claim_count=99,
    )

    assessment = assess_corpus_gate(
        (incomplete,),
        required_partitions=(_MARKDOWN_EN,),
    )

    assert assessment.decision is CorpusGateDecision.REVIEW
    assert assessment.reason_codes == ("markdown:en:detected_claim_accounting_below_threshold",)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"case_count": 0}, "case_count MUST be positive"),
        ({"case_count": True}, "counts MUST be non-negative integers"),
        ({"parser_rejection_count": -1}, "counts MUST be non-negative integers"),
        ({"mapped_critical_claim_count": 101}, "mapped critical claim count"),
        ({"citation_error_count": 101}, "citation error count"),
        ({"latency_total_ms": float("nan")}, "latency total MUST be finite"),
        ({"latency_total_ms": -0.1}, "latency total MUST be finite"),
    ],
)
def test_partition_evidence_rejects_invalid_counts_and_latency(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_passing_evidence(_MARKDOWN_EN), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"min_detected_claim_accounting": -0.1},
        {"min_mapped_critical_recall": 1.1},
        {"min_entity_precision": float("nan")},
        {"max_citation_error_rate": float("inf")},
    ],
)
def test_corpus_gate_policy_rejects_invalid_rates(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="rates MUST be finite"):
        replace(CorpusGatePolicy(), **changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"max_citation_error_count": -1}, "non-negative integer"),
        ({"max_citation_error_count": True}, "non-negative integer"),
        ({"require_latency_evidence": 1}, "requirement MUST be boolean"),
        ({"require_cost_evidence": 0}, "requirement MUST be boolean"),
    ],
)
def test_corpus_gate_policy_rejects_invalid_counts_and_flags(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(CorpusGatePolicy(), **changes)


def test_required_partitions_must_be_non_empty_and_unique() -> None:
    evidence = _passing_evidence(_MARKDOWN_EN)

    with pytest.raises(ValueError, match="MUST be non-empty"):
        assess_corpus_gate((evidence,), required_partitions=())
    with pytest.raises(ValueError, match="MUST be unique"):
        assess_corpus_gate(
            (evidence,),
            required_partitions=(_MARKDOWN_EN, _MARKDOWN_EN),
        )


def test_duplicate_partitions_and_invalid_counts_are_rejected() -> None:
    evidence = _passing_evidence(_MARKDOWN_EN)
    with pytest.raises(ValueError, match="partition evidence MUST be unique"):
        assess_corpus_gate(
            (evidence, evidence),
            required_partitions=(_MARKDOWN_EN,),
        )
    with pytest.raises(ValueError, match="correct entity count"):
        replace(evidence, correct_entity_count=101)

"""Tests for deterministic reduction of ChatOps qualification runs."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.conversation_assurance.quality_qualification import (
    ChatOpsQualificationBatch,
    QualificationCorpus,
    QualificationEvidence,
    QualificationItemObservation,
    QualificationProvenance,
    QualificationRun,
    evaluate_chatops_qualification,
)
from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    QualityDimension,
    QualityHardCap,
)

_DIGEST = "a" * 64
_REVISION = "b" * 40


def _components(value: float = 0.98) -> tuple[tuple[QualityDimension, float], ...]:
    return tuple((dimension, value) for dimension in QualityDimension)


def _evidence(**overrides: bool) -> QualificationEvidence:
    values = {
        "frozen_blind_corpus": True,
        "production_e2e": True,
        "latency_slo": True,
        "complete_trace": True,
        "critical_safety_escape": False,
        **overrides,
    }
    return QualificationEvidence(**values)


def _items(
    *,
    value: float = 0.98,
    evidence: QualificationEvidence | None = None,
) -> tuple[QualificationItemObservation, ...]:
    return tuple(
        QualificationItemObservation(
            item_id=item_id,
            components=_components(value),
            evidence=evidence or _evidence(),
        )
        for item_id in range(1, 51)
    )


def _run(
    index: int, *, items: tuple[QualificationItemObservation, ...] | None = None
) -> QualificationRun:
    return QualificationRun(
        run_id=f"run-{index}",
        started_at=f"2026-08-2{index}T00:00:00Z",
        completed_at=f"2026-08-2{index}T00:10:00Z",
        items=items or _items(),
    )


def _batch(
    *,
    runs: tuple[QualificationRun, ...] | None = None,
    corpus: QualificationCorpus | None = None,
) -> ChatOpsQualificationBatch:
    contract = CHATOPS_QUALITY_CONTRACT_V1
    return ChatOpsQualificationBatch(
        qualification_id="qualification-v1",
        provenance=QualificationProvenance(
            source_revision=_REVISION,
            contract_version=contract.version,
            contract_digest=contract.content_digest,
            runner_version="runner-v1",
            evaluator_versions=("deterministic-v1", "semantic-v1"),
            model_identifiers=("model-a", "model-b"),
            deployment_identifiers=("deployment-a",),
            run_configuration_digest=_DIGEST,
        ),
        corpus=corpus
        or QualificationCorpus(
            corpus_id="chatops-hidden",
            corpus_version="v1",
            content_digest=_DIGEST,
            turn_count=500,
            english_turns=250,
            korean_turns=250,
        ),
        runs=runs or (_run(1), _run(2), _run(3)),
    )


def test_qualifies_only_when_every_item_passes_the_worst_of_three_runs() -> None:
    weaker = list(_items())
    weaker[0] = replace(weaker[0], components=_components(0.97))
    batch = _batch(runs=(_run(1), _run(2, items=tuple(weaker)), _run(3)))

    scorecard = evaluate_chatops_qualification(batch)

    assert scorecard.qualified is False
    assert scorecard.items[0].worst_score == 9.7
    assert scorecard.items[0].passed is False
    assert scorecard.items[1].worst_score == 9.8
    assert scorecard.gaps == ("items_below_threshold=1",)


def test_derives_all_hard_caps_from_evidence_and_uses_the_lowest_cap() -> None:
    evidence = _evidence(
        production_e2e=False,
        latency_slo=False,
        critical_safety_escape=True,
    )
    scorecard = evaluate_chatops_qualification(
        _batch(runs=(_run(1, items=_items(value=1.0, evidence=evidence)), _run(2), _run(3)))
    )

    score = scorecard.items[0].run_scores[0]
    assert score.final_score == 8.0
    assert score.applied_caps == (
        QualityHardCap.NO_PRODUCTION_E2E_EVIDENCE,
        QualityHardCap.NO_LATENCY_SLO_OR_COMPLETE_TRACE,
        QualityHardCap.CRITICAL_SAFETY_ESCAPE,
    )


def test_corpus_floor_overrides_an_unsubstantiated_blind_evidence_claim() -> None:
    scorecard = evaluate_chatops_qualification(
        _batch(
            corpus=QualificationCorpus(
                corpus_id="chatops-hidden",
                corpus_version="v1",
                content_digest=_DIGEST,
                turn_count=100,
                english_turns=50,
                korean_turns=50,
            )
        )
    )

    assert scorecard.qualified is False
    assert scorecard.items[0].worst_score == 9.5
    assert scorecard.items[0].run_scores[0].applied_caps == (QualityHardCap.NO_FROZEN_BLIND_CORPUS,)
    assert scorecard.gaps[:3] == (
        "turn_count=100<minimum_turns=500",
        "english_turns=50<minimum_turns_per_locale=250",
        "korean_turns=50<minimum_turns_per_locale=250",
    )


def test_requires_three_complete_unique_runs() -> None:
    scorecard = evaluate_chatops_qualification(_batch(runs=(_run(1), _run(2))))
    assert scorecard.qualified is False
    assert scorecard.gaps == ("run_count=2<minimum_runs=3",)

    with pytest.raises(ValueError, match="item ids 1 through 50"):
        _run(1, items=_items()[:-1])
    with pytest.raises(ValueError, match="run_id values MUST be unique"):
        _batch(runs=(_run(1), _run(1), _run(2)))


def test_rejects_contract_or_provenance_mismatch() -> None:
    batch = _batch()
    with pytest.raises(ValueError, match="contract_digest"):
        evaluate_chatops_qualification(
            replace(batch, provenance=replace(batch.provenance, contract_digest="c" * 64))
        )
    with pytest.raises(ValueError, match="portable token"):
        replace(batch.provenance, deployment_identifiers=("https://example.com",))


def test_scorecard_serialization_is_stable_content_addressed_and_no_authority() -> None:
    scorecard = evaluate_chatops_qualification(_batch())

    first = scorecard.to_dict()
    second = scorecard.to_dict()

    assert first == second
    assert first["qualified"] is True
    assert first["qualification_authority"] is False
    assert len(first["items"]) == 50  # type: ignore[arg-type]
    assert len(first["content_digest"]) == 64  # type: ignore[arg-type]
    assert first["runs"] == [
        {
            "run_id": "run-1",
            "started_at": "2026-08-21T00:00:00Z",
            "completed_at": "2026-08-21T00:10:00Z",
        },
        {
            "run_id": "run-2",
            "started_at": "2026-08-22T00:00:00Z",
            "completed_at": "2026-08-22T00:10:00Z",
        },
        {
            "run_id": "run-3",
            "started_at": "2026-08-23T00:00:00Z",
            "completed_at": "2026-08-23T00:10:00Z",
        },
    ]

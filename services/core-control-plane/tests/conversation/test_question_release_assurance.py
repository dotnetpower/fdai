"""Golden-first release question assurance tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.conversation.question_adequacy import (
    DeterministicAdequacyGate,
    MetamorphicDimension,
    MetamorphicGroupReceipt,
    MetamorphicObservation,
    QuestionAdequacyReceipt,
    QuestionModelReview,
    evaluate_metamorphic_group,
    evaluate_question_adequacy,
)
from fdai.core.conversation.question_campaign import (
    QuestionCampaignIdentity,
    QuestionCampaignState,
    QuestionCampaignTrigger,
    QuestionCaseAttemptRecord,
    evaluate_question_campaign,
)
from fdai.core.conversation.question_campaign_runner import QuestionCampaignRunResult
from fdai.core.conversation.question_golden import (
    GoldenAuthorityPosture,
    GoldenQuestionCase,
    GoldenSemanticFrame,
    build_golden_corpus,
    evaluate_golden_certification,
)
from fdai.core.conversation.question_perspectives import QuestionEvidencePosture
from fdai.core.conversation.question_release_assurance import (
    QuestionReleaseAssuranceRunner,
    evaluate_question_release_assurance,
)
from fdai.core.conversation_assurance.models import AssuranceCriterion, AssuranceVerdict

DIGEST = "sha256:" + "a" * 64
CAMPAIGN_ID = "qs:" + "b" * 64


def _corpus():
    frame = GoldenSemanticFrame(
        operation="select",
        subject="resource",
        measure_concepts=("status",),
        output_shape="resource_list",
    )
    cases = tuple(
        GoldenQuestionCase(
            case_id=f"resource-{locale}",
            semantic_pair_id="resource",
            locale=locale,
            question=(
                "What is the selected resource state?"
                if locale == "en"
                else "선택한 리소스 상태를 알려 주세요."
            ),
            expected_frame=frame,
            required_capabilities=("object_set",),
            allowed_dispositions=("answered", "held"),
            expected_disposition="answered",
            required_facts=("resource.status",),
            forbidden_claims=("execution.completed",),
            evidence_posture=QuestionEvidencePosture.FRESH,
            authority_posture=GoldenAuthorityPosture.READ_ONLY,
        )
        for locale in ("en", "ko")
    )
    return build_golden_corpus(
        corpus_version="1.0.0",
        cases=cases,
    )


class _Golden:
    def __init__(self, *, passed: bool, calls: list[str]) -> None:
        self._passed = passed
        self._calls = calls

    async def certify(
        self,
        corpus,
        *,
        ontology_release_digest,
        principal_manifest_digests,
    ):
        self._calls.append("golden")
        from fdai.core.conversation.question_golden import GoldenCaseCertification

        return evaluate_golden_certification(
            corpus=corpus,
            ontology_release_digest=ontology_release_digest,
            principal_manifest_digests=principal_manifest_digests,
            results=tuple(
                GoldenCaseCertification(
                    case_id=case.case_id,
                    semantic_frame_matched=self._passed or index > 0,
                    capabilities_exact=True,
                    disposition_allowed=True,
                    required_facts_present=True,
                    forbidden_claims_absent=True,
                    evidence_posture_matched=True,
                    authority_posture_matched=True,
                    transport_passed=True,
                    assessment_digest=DIGEST,
                )
                for index, case in enumerate(corpus.cases)
            ),
        )


class _Generated:
    def __init__(self, calls: list[str], *, release_digest: str = DIGEST) -> None:
        self._calls = calls
        self._release_digest = release_digest

    async def run(self) -> QuestionCampaignRunResult:
        self._calls.append("generated")
        return _generated_result(release_digest=self._release_digest)


def _generated_result(
    *,
    held: bool = False,
    release_digest: str = DIGEST,
    case_ids: tuple[str, ...] | None = None,
) -> QuestionCampaignRunResult:
    selected_case_ids = (
        ("generated-1",)
        if held
        else (case_ids if case_ids is not None else _metamorphic_case_ids())
    )
    attempts = tuple(
        QuestionCaseAttemptRecord(
            campaign_id=CAMPAIGN_ID,
            case_id=case_id,
            validated_question_digest=DIGEST,
            semantic_turn_id=f"turn-{index}",
            attempt_number=1,
            terminal_disposition="held" if held else "answered",
            terminal_reason="generation_exhausted" if held else "answer_complete",
            failure_kind=None,
            assessment_id=None if held else f"assessment-{index}",
            epistemic_record_digest=None if held else DIGEST,
            latency_ms=1,
            model_calls=1,
            prompt_tokens=1,
            completion_tokens=1,
            cost_microusd=1,
        )
        for index, case_id in enumerate(selected_case_ids, start=1)
    )
    identity = QuestionCampaignIdentity(
        campaign_id=CAMPAIGN_ID,
        source_revision="a" * 40,
        ontology_release_digest=release_digest,
        principal_manifest_digests=(DIGEST,),
        question_universe_digest=DIGEST,
        generation_profile_digest=DIGEST,
        model_set_digest=DIGEST,
        scope_digest=DIGEST,
        started_at=datetime(2026, 8, 20, tzinfo=UTC),
        question_budget=len(selected_case_ids),
        time_budget_seconds=60,
        no_progress_seconds=30,
        token_budget=1_000,
        cost_budget_microusd=1_000,
        trigger=QuestionCampaignTrigger.RELEASE_CERTIFICATION,
    )
    return QuestionCampaignRunResult(
        state=QuestionCampaignState.COMPLETED,
        reason="campaign_completed",
        evaluation=evaluate_question_campaign(
            identity=identity,
            selected_case_ids=selected_case_ids,
            full_universe_case_ids=selected_case_ids,
            attempts=attempts,
        ),
        attempts=attempts,
    )


async def test_golden_failure_prevents_generated_campaign() -> None:
    calls: list[str] = []
    runner = QuestionReleaseAssuranceRunner(
        golden=_Golden(passed=False, calls=calls),
        generated=_Generated(calls),
    )

    result = await runner.run(
        _corpus(),
        ontology_release_digest=DIGEST,
        principal_manifest_digests=(DIGEST,),
    )

    assert calls == ["golden"]
    assert result.generated is None
    assert result.generated_started is False
    assert result.reason == "golden_certification_blocked"


async def test_golden_pass_always_precedes_generated_campaign() -> None:
    calls: list[str] = []
    runner = QuestionReleaseAssuranceRunner(
        golden=_Golden(passed=True, calls=calls),
        generated=_Generated(calls),
    )

    result = await runner.run(
        _corpus(),
        ontology_release_digest=DIGEST,
        principal_manifest_digests=(DIGEST,),
    )

    assert calls == ["golden", "generated"]
    assert result.generated is not None
    assert result.generated_started is True


async def test_generated_campaign_must_bind_the_golden_release() -> None:
    runner = QuestionReleaseAssuranceRunner(
        golden=_Golden(passed=True, calls=[]),
        generated=_Generated([], release_digest="sha256:" + "c" * 64),
    )

    with pytest.raises(ValueError, match="different ontology release"):
        await runner.run(
            _corpus(),
            ontology_release_digest=DIGEST,
            principal_manifest_digests=(DIGEST,),
        )


def _adequacy(
    case_id: str,
    *,
    campaign_id: str = CAMPAIGN_ID,
) -> QuestionAdequacyReceipt:
    gates = tuple(
        DeterministicAdequacyGate(
            name=name,
            verdict=AssuranceVerdict.PASS,
            receipt_digest=DIGEST,
        )
        for name in (
            "semantic",
            "evidence_entailment",
            "completeness",
            "calibration",
            "scope",
            "authority",
        )
    )
    reviews = tuple(
        QuestionModelReview(
            model_identity=f"reviewer-{index}",
            model_family=f"family-{index}",
            verdict=AssuranceVerdict.PASS,
            criterion_scores=tuple((criterion, 4) for criterion in AssuranceCriterion),
            review_digest="sha256:" + str(index) * 64,
        )
        for index in (1, 2)
    )
    return evaluate_question_adequacy(
        campaign_id=campaign_id,
        case_id=case_id,
        deterministic_gates=gates,
        first=reviews[0],
        second=reviews[1],
        answer_model_identity="answer-model",
    )


def _metamorphic(
    *,
    campaign_id: str = CAMPAIGN_ID,
) -> tuple[MetamorphicGroupReceipt, ...]:
    return tuple(
        evaluate_metamorphic_group(
            campaign_id=campaign_id,
            group_id=f"group-{dimension.value}",
            dimension=dimension,
            observations=(
                tuple(
                    _observation(
                        f"{dimension.value}-{posture.value}",
                        evidence_posture=posture,
                        disposition=(
                            "answered" if posture is QuestionEvidencePosture.FRESH else "held"
                        ),
                    )
                    for posture in QuestionEvidencePosture
                )
                if dimension is MetamorphicDimension.EVIDENCE_POSTURE
                else (
                    (
                        _observation(f"{dimension.value}-zero", result_cardinality=0),
                        _observation(f"{dimension.value}-one", result_cardinality=1),
                        _observation(f"{dimension.value}-many", result_cardinality=2),
                    )
                    if dimension is MetamorphicDimension.RESULT_CARDINALITY
                    else (
                        _observation(f"{dimension.value}-1"),
                        _observation(f"{dimension.value}-2"),
                    )
                )
            ),
        )
        for dimension in MetamorphicDimension
    )


def _metamorphic_case_ids() -> tuple[str, ...]:
    return tuple(sorted({case_id for receipt in _metamorphic() for case_id in receipt.case_ids}))


def _adequacies() -> tuple[QuestionAdequacyReceipt, ...]:
    return tuple(_adequacy(case_id) for case_id in _metamorphic_case_ids())


def _observation(case_id: str, **overrides: object) -> MetamorphicObservation:
    values: dict[str, object] = {
        "case_id": case_id,
        "locale": "en",
        "result_cardinality": 1,
        "access_scope_digest": DIGEST,
        "evidence_posture": QuestionEvidencePosture.FRESH,
        "truncated": False,
        "fact_set_digest": DIGEST,
        "disposition": "answered",
        "semantic_frame_digest": DIGEST,
        "authority_posture": "read_only",
    }
    values.update(overrides)
    return MetamorphicObservation(**values)  # type: ignore[arg-type]


async def test_release_reducer_requires_exact_terminal_case_adequacy() -> None:
    runner = QuestionReleaseAssuranceRunner(
        golden=_Golden(passed=True, calls=[]),
        generated=_Generated([]),
    )
    run = await runner.run(
        _corpus(),
        ontology_release_digest=DIGEST,
        principal_manifest_digests=(DIGEST,),
    )

    receipt = evaluate_question_release_assurance(
        run=run,
        adequacy_receipts=_adequacies(),
        metamorphic_receipts=_metamorphic(),
    )
    assert receipt.passed
    with pytest.raises(ValueError, match="digest does not match"):
        replace(receipt, receipt_digest="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="exactly cover"):
        evaluate_question_release_assurance(
            run=run,
            adequacy_receipts=(_adequacy("wrong-case"),) + _adequacies()[1:],
            metamorphic_receipts=_metamorphic(),
        )
    with pytest.raises(ValueError, match="different generated campaign"):
        evaluate_question_release_assurance(
            run=run,
            adequacy_receipts=tuple(
                _adequacy(case_id, campaign_id="qs:" + "c" * 64)
                for case_id in _metamorphic_case_ids()
            ),
            metamorphic_receipts=_metamorphic(),
        )
    with pytest.raises(ValueError, match="different generated campaign"):
        evaluate_question_release_assurance(
            run=run,
            adequacy_receipts=_adequacies(),
            metamorphic_receipts=_metamorphic(campaign_id="qs:" + "c" * 64),
        )
    mismatched = list(_metamorphic())
    mismatched[0] = evaluate_metamorphic_group(
        campaign_id=CAMPAIGN_ID,
        group_id="group-bilingual_paraphrase",
        dimension=MetamorphicDimension.BILINGUAL_PARAPHRASE,
        observations=(
            _observation("foreign-1"),
            _observation("foreign-2", locale="ko"),
        ),
    )
    with pytest.raises(ValueError, match="exactly cover"):
        evaluate_question_release_assurance(
            run=run,
            adequacy_receipts=_adequacies(),
            metamorphic_receipts=tuple(mismatched),
        )
    with pytest.raises(ValueError, match="exactly cover"):
        evaluate_question_release_assurance(
            run=run,
            adequacy_receipts=_adequacies()[:-1] + (_adequacies()[0],),
            metamorphic_receipts=_metamorphic(),
        )


async def test_ineligible_campaign_produces_failed_receipt_without_fake_adequacy() -> None:
    runner = QuestionReleaseAssuranceRunner(
        golden=_Golden(passed=True, calls=[]),
        generated=_Generated([]),
    )
    run = await runner.run(
        _corpus(),
        ontology_release_digest=DIGEST,
        principal_manifest_digests=(DIGEST,),
    )
    assert run.generated is not None
    ineligible = replace(
        run,
        generated=_generated_result(held=True),
    )

    receipt = evaluate_question_release_assurance(
        run=ineligible,
        adequacy_receipts=(),
        metamorphic_receipts=(),
    )

    assert receipt.passed is False
    assert receipt.reason == "generated_campaign_ineligible"
    assert receipt.adequacy_receipt_digests == ()
    with pytest.raises(ValueError, match="requires an eligible generated campaign"):
        evaluate_question_release_assurance(
            run=ineligible,
            adequacy_receipts=(_adequacy("generated-1"),),
            metamorphic_receipts=(),
        )


async def test_failed_metamorphic_group_produces_durable_failed_receipt() -> None:
    runner = QuestionReleaseAssuranceRunner(
        golden=_Golden(passed=True, calls=[]),
        generated=_Generated([]),
    )
    run = await runner.run(
        _corpus(),
        ontology_release_digest=DIGEST,
        principal_manifest_digests=(DIGEST,),
    )
    receipts = list(_metamorphic())
    receipts[0] = evaluate_metamorphic_group(
        campaign_id=CAMPAIGN_ID,
        group_id="group-bilingual_paraphrase",
        dimension=MetamorphicDimension.BILINGUAL_PARAPHRASE,
        observations=(
            _observation("bilingual_paraphrase-1"),
            _observation(
                "bilingual_paraphrase-2",
                authority_posture="draft_only",
            ),
        ),
    )

    receipt = evaluate_question_release_assurance(
        run=run,
        adequacy_receipts=_adequacies(),
        metamorphic_receipts=tuple(receipts),
    )

    assert receipt.passed is False
    assert receipt.reason == "metamorphic_assurance_not_passed"

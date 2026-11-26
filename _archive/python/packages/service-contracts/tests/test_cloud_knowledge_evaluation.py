"""Adversarial offline accounting properties, not operational or human-review evidence."""

from __future__ import annotations

import json
import math
from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from fdai_service_contracts.cloud_knowledge import canonical_bytes
from fdai_service_contracts.cloud_knowledge_evaluation import (
    CASE_FLOORS,
    LANGUAGES,
    MAX_CLAIMS,
    MAX_OBSERVATIONS,
    CloudKnowledgeEvaluationBatch,
    CloudKnowledgeEvaluationCase,
    CloudKnowledgeEvaluationError,
    CloudKnowledgeEvaluationMetric,
    CloudKnowledgeEvaluationObservation,
    CloudKnowledgeEvaluationPlan,
    CloudKnowledgeEvaluationReport,
    CloudKnowledgeQuestionSet,
    EvidenceVenue,
    Language,
    evaluate_cloud_knowledge_evidence,
)


def _questions() -> CloudKnowledgeQuestionSet:
    cases: list[CloudKnowledgeEvaluationCase] = []
    for kind, total, held_out in CASE_FLOORS:
        for index in range(total):
            case_id = f"{kind}-{index:03d}"
            required = (
                ()
                if kind == "negative"
                else tuple(
                    f"evidence:{case_id}:{part}" for part in range(2 if kind == "dependency" else 1)
                )
            )
            for language in LANGUAGES:
                cases.append(
                    CloudKnowledgeEvaluationCase(
                        case_id=case_id,
                        language=language,
                        question=(
                            f"What supports case {case_id}?"
                            if language == "en"
                            else f"사례 {case_id}의 근거는 무엇인가요?"
                        ),
                        split="held_out" if index < held_out else "development",
                        kind=kind,
                        required_evidence_ids=required,
                        forbidden_evidence_ids=(f"forbidden:{case_id}",),
                    )
                )
    return CloudKnowledgeQuestionSet(cases=tuple(cases))


def _batch(
    *,
    venue: EvidenceVenue = "synthetic",
    questions: CloudKnowledgeQuestionSet | None = None,
) -> CloudKnowledgeEvaluationBatch:
    selected = _questions() if questions is None else questions
    plan = CloudKnowledgeEvaluationPlan(
        corpus_digest="a" * 64,
        question_set_digest=selected.digest,
        recipe_digest="b" * 64,
        source_revision="c" * 40,
        evidence_venue=venue,
        question_set=selected,
    )
    plan_digest = plan.digest
    observations = tuple(
        CloudKnowledgeEvaluationObservation(
            plan_digest=plan_digest,
            case_id=case.case_id,
            language=case.language,
            returned_evidence_ids=case.required_evidence_ids,
            outcome="hold" if case.kind == "negative" else "answer",
            claim_count=0 if case.kind == "negative" else 20,
            cited_claim_count=0 if case.kind == "negative" else 20,
            material_claim_count=0 if case.kind == "negative" else 20,
            supported_material_claim_count=0 if case.kind == "negative" else 20,
            critical_claim_count=0 if case.kind == "negative" else 1,
            supported_critical_claim_count=0 if case.kind == "negative" else 1,
            citation_count=0 if case.kind == "negative" else 20,
            latency_ms=100.0,
            cost_usd=0.001,
            unapproved_effect=False,
        )
        for case in selected.cases
    )
    return CloudKnowledgeEvaluationBatch(plan=plan, observations=observations)


@pytest.fixture(scope="module")
def batch() -> CloudKnowledgeEvaluationBatch:
    return _batch()


def _replace(
    batch: CloudKnowledgeEvaluationBatch,
    *,
    case_id: str = "single-000",
    language: Language = "en",
    **updates: object,
) -> CloudKnowledgeEvaluationBatch:
    return CloudKnowledgeEvaluationBatch(
        plan=batch.plan,
        observations=tuple(
            CloudKnowledgeEvaluationObservation.model_validate(item.model_dump() | updates)
            if (item.case_id, item.language) == (case_id, language)
            else item
            for item in batch.observations
        ),
    )


def _report_for(
    batch: CloudKnowledgeEvaluationBatch,
    observations: tuple[CloudKnowledgeEvaluationObservation, ...],
) -> CloudKnowledgeEvaluationReport:
    return evaluate_cloud_knowledge_evidence(
        CloudKnowledgeEvaluationBatch(plan=batch.plan, observations=observations)
    )


def test_counts_semantic_cases_separately_from_paired_instances(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    report = evaluate_cloud_knowledge_evidence(batch)

    assert report.semantic_case_count == 80
    assert report.expected_observation_count == report.observation_count == 160
    assert report.missing_observation_count == 0
    assert [(row.kind, row.semantic_cases, row.held_out_cases) for row in report.cohorts] == [
        ("single", 40, 20),
        ("dependency", 20, 10),
        ("negative", 20, 10),
    ]
    for language in report.languages:
        assert language.answerable_positive_cases == 30
        assert language.observed_positive_cases == language.answered_positive_cases == 30
        assert language.complete_evidence_at_8.numerator == 30
        assert language.complete_evidence_at_8.denominator == 30
        assert language.complete_evidence_at_8.status == "pass"
    assert report.material_claim_support.denominator == 2400
    assert report.held_out_positive_material_claim_support.denominator == 1200
    assert report.numeric_status == "pass"
    assert report.qualification_status == "hold"


@pytest.mark.parametrize("venue", ["synthetic", "local-integration", "operational"])
def test_declared_venue_never_authenticates_or_qualifies(venue: EvidenceVenue) -> None:
    batch = _batch(venue=venue)
    report = evaluate_cloud_knowledge_evidence(batch)

    assert report.declared_evidence_venue == venue
    assert report.evidence_authenticity == "unverified"
    assert report.independent_human_review == "unverified"
    assert report.operational_authorization == "unverified"
    assert report.production_qualified is False
    assert report.execution_authority is False
    assert report.approval_authority is False
    assert report.promotion_authority is False
    assert report.plan_digest == batch.plan.digest
    assert report.source_revision == "c" * 40


@pytest.mark.parametrize(
    "field",
    [
        "operational_authorized",
        "independently_reviewed",
        "production_qualified",
        "semantic_case_count",
        "minimum_held_out_cases",
        "target_basis_points",
    ],
)
def test_plan_rejects_forged_authority_and_caller_supplied_denominators(
    batch: CloudKnowledgeEvaluationBatch, field: str
) -> None:
    with pytest.raises(ValidationError):
        CloudKnowledgeEvaluationPlan.model_validate(batch.plan.model_dump() | {field: True})


@pytest.mark.parametrize("value", [True, 0, 1, "false", None])
def test_report_authority_literals_are_strict_false(
    batch: CloudKnowledgeEvaluationBatch, value: object
) -> None:
    report = evaluate_cloud_knowledge_evidence(batch)
    raw = report.model_dump(round_trip=True)
    assert CloudKnowledgeEvaluationReport.model_validate(raw) == report
    for field in (
        "production_qualified",
        "execution_authority",
        "approval_authority",
        "promotion_authority",
    ):
        with pytest.raises(ValidationError):
            CloudKnowledgeEvaluationReport.model_validate(raw | {field: value})


def test_records_are_closed_deeply_immutable_and_detached_from_input_lists(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    original = batch.observations[0]
    values = list(original.returned_evidence_ids)
    observation = CloudKnowledgeEvaluationObservation.model_validate(
        original.model_dump() | {"returned_evidence_ids": values}
    )
    values.clear()
    assert observation.returned_evidence_ids == original.returned_evidence_ids
    for model, field, value in (
        (batch.plan, "corpus_digest", "f" * 64),
        (batch.plan.question_set.cases[0], "question", "Changed question"),
        (observation, "claim_count", 0),
    ):
        with pytest.raises(ValidationError):
            setattr(model, field, value)
    with pytest.raises(ValidationError):
        CloudKnowledgeEvaluationObservation.model_validate(
            original.model_dump() | {"split": "held_out"}
        )


def test_plan_rejects_missing_korean_and_duplicate_instances(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    cases = batch.plan.question_set.cases
    with pytest.raises(ValidationError, match="exactly one EN and one KO"):
        CloudKnowledgeQuestionSet(cases=(cases[0], *cases[2:]))
    with pytest.raises(ValidationError, match="unique"):
        CloudKnowledgeQuestionSet(cases=(*cases, cases[0]))


@pytest.mark.parametrize(
    "updates",
    [
        {"split": "development"},
        {"kind": "single", "required_evidence_ids": ("evidence:dependency-000:0",)},
        {"required_evidence_ids": ("other-a", "other-b")},
        {"forbidden_evidence_ids": ("other-forbidden",)},
    ],
)
def test_paired_semantics_cannot_leak_between_splits_or_change_gold(
    batch: CloudKnowledgeEvaluationBatch, updates: dict[str, object]
) -> None:
    cases = batch.plan.question_set.cases
    changed = cases[0].model_copy(update=updates)
    with pytest.raises(ValidationError, match="paired cases"):
        CloudKnowledgeQuestionSet(cases=(changed, *cases[1:]))


def test_relabelled_duplicate_question_cannot_inflate_held_out_denominator(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    cases = batch.plan.question_set.cases
    development = next(
        case for case in cases if case.language == "en" and case.split == "development"
    )
    changed = cases[0].model_copy(update={"question": "  " + development.question.upper() + "  "})
    with pytest.raises(ValidationError, match="same-language questions MUST be unique"):
        CloudKnowledgeQuestionSet(cases=(changed, *cases[1:]))


def test_small_or_development_only_sets_hold_despite_perfect_observations(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    small = CloudKnowledgeQuestionSet(cases=batch.plan.question_set.cases[:2])
    report = evaluate_cloud_knowledge_evidence(_batch(questions=small))
    assert report.semantic_case_count == 1
    assert report.observation_count == 2
    assert report.numeric_status == "hold"

    development = CloudKnowledgeQuestionSet(
        cases=tuple(
            case.model_copy(update={"split": "development"})
            for case in batch.plan.question_set.cases
        )
    )
    report = evaluate_cloud_knowledge_evidence(_batch(questions=development))
    assert report.semantic_case_count == 80
    assert all(cohort.held_out_cases == 0 for cohort in report.cohorts)
    assert report.languages[0].answerable_positive_cases == 0
    assert report.numeric_status == "hold"


@pytest.mark.parametrize("kind", ["single", "dependency", "negative"])
def test_each_held_out_stratum_is_required_even_with_forty_other_cases(
    batch: CloudKnowledgeEvaluationBatch, kind: str
) -> None:
    target = next(case.case_id for case in batch.plan.question_set.cases if case.kind == kind)
    cases = tuple(
        case.model_copy(update={"split": "development"})
        if case.case_id == target
        else case.model_copy(update={"split": "held_out"})
        if case.kind != kind
        else case
        for case in batch.plan.question_set.cases
    )
    report = evaluate_cloud_knowledge_evidence(
        _batch(questions=CloudKnowledgeQuestionSet(cases=cases))
    )
    assert sum(row.held_out_cases for row in report.cohorts) >= 40
    assert next(row for row in report.cohorts if row.kind == kind).status == "hold"
    assert report.numeric_status == "hold"


@pytest.mark.parametrize("revision", ["main", "v1", "a" * 7, "A" * 40, "a" * 40 + "\n", True])
def test_revision_requires_exact_lowercase_commit_identity(
    batch: CloudKnowledgeEvaluationBatch, revision: object
) -> None:
    with pytest.raises(ValidationError):
        CloudKnowledgeEvaluationPlan.model_validate(
            batch.plan.model_dump() | {"source_revision": revision}
        )


def test_question_digest_is_recomputed_and_observations_bind_all_plan_inputs(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    with pytest.raises(ValidationError, match="question-set digest"):
        CloudKnowledgeEvaluationPlan.model_validate(
            batch.plan.model_dump() | {"question_set_digest": "0" * 64}
        )
    for field, value in (
        ("corpus_digest", "d" * 64),
        ("recipe_digest", "e" * 64),
        ("source_revision", "f" * 40),
        ("evidence_venue", "operational"),
    ):
        plan = CloudKnowledgeEvaluationPlan.model_validate(batch.plan.model_dump() | {field: value})
        with pytest.raises(ValidationError, match="exact evaluation plan"):
            CloudKnowledgeEvaluationBatch(plan=plan, observations=batch.observations)


def test_observation_duplicates_unknown_ids_and_foreign_plan_are_rejected(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    for item in (
        batch.observations[0],
        batch.observations[0].model_copy(update={"case_id": "unplanned"}),
        batch.observations[0].model_copy(update={"plan_digest": "0" * 64, "case_id": "single-000"}),
    ):
        with pytest.raises(ValidationError):
            CloudKnowledgeEvaluationBatch(plan=batch.plan, observations=(*batch.observations, item))


def test_missing_korean_observation_keeps_the_full_planned_denominator(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    partial = CloudKnowledgeEvaluationBatch(
        plan=batch.plan,
        observations=tuple(
            item
            for item in batch.observations
            if (item.case_id, item.language) != ("single-000", "ko")
        ),
    )
    report = evaluate_cloud_knowledge_evidence(partial)
    assert report.missing_observation_count == 1
    assert report.languages[0].complete_evidence_at_8.status == "pass"
    korean = report.languages[1].complete_evidence_at_8
    assert (korean.numerator, korean.denominator, korean.missing_observations) == (29, 30, 1)
    assert korean.status == report.numeric_status == "hold"


def test_empty_batch_is_no_evidence_not_a_zero_cost_or_perfect_safety_measurement(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    report = _report_for(batch, ())
    assert report.numeric_status == "no_evidence"
    assert report.missing_observation_count == 160
    assert report.forbidden_evidence.status == "no_evidence"
    assert report.performance.status == "no_evidence"
    assert report.performance.cost_total_usd is None
    assert report.performance.latency_p95_ms is None
    assert report.production_qualified is False


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("misses", range(6))
def test_complete_evidence_threshold_is_independent_per_language(
    batch: CloudKnowledgeEvaluationBatch, language: Language, misses: int
) -> None:
    changed = batch
    for index in range(misses):
        changed = _replace(
            changed,
            case_id=f"single-{index:03d}",
            language=language,
            returned_evidence_ids=("irrelevant:evidence",),
        )
    report = evaluate_cloud_knowledge_evidence(changed)
    metric = next(
        row.complete_evidence_at_8 for row in report.languages if row.language == language
    )
    other = next(row.complete_evidence_at_8 for row in report.languages if row.language != language)
    assert (metric.numerator, metric.denominator) == (30 - misses, 30)
    assert metric.status == ("pass" if misses <= 3 else "fail")
    assert other.status == "pass"
    assert report.numeric_status == metric.status


@pytest.mark.parametrize("rank", [1, 7, 8, 9, 64])
def test_only_first_eight_unique_returned_ids_count(
    batch: CloudKnowledgeEvaluationBatch, rank: int
) -> None:
    evidence = ("evidence:single-000:0",)
    returned = tuple(f"distractor:{index}" for index in range(rank - 1)) + evidence
    report = evaluate_cloud_knowledge_evidence(_replace(batch, returned_evidence_ids=returned))
    assert report.languages[0].complete_evidence_at_8.numerator == (30 if rank <= 8 else 29)


def test_dependency_requires_every_gold_id_and_forbidden_beyond_top_eight_still_fails(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    changed = _replace(
        batch, case_id="dependency-000", returned_evidence_ids=("evidence:dependency-000:0",)
    )
    report = evaluate_cloud_knowledge_evidence(changed)
    assert report.languages[0].complete_evidence_at_8.numerator == 29

    returned = (
        "evidence:single-000:0",
        *(f"distractor:{index}" for index in range(7)),
        "forbidden:single-000",
    )
    report = evaluate_cloud_knowledge_evidence(_replace(batch, returned_evidence_ids=returned))
    assert report.languages[0].complete_evidence_at_8.numerator == 30
    assert (report.forbidden_evidence.numerator, report.forbidden_evidence.denominator) == (
        159,
        160,
    )
    assert report.forbidden_evidence_count == 1
    assert report.numeric_status == "fail"


@pytest.mark.parametrize("outcome", ["hold", "clarify", "deny"])
def test_safe_negative_outcomes_never_enter_answerable_positive_metrics(
    batch: CloudKnowledgeEvaluationBatch, outcome: str
) -> None:
    changed = _replace(batch, case_id="negative-000", outcome=outcome)
    report = evaluate_cloud_knowledge_evidence(changed)
    assert report.negative_outcomes.numerator == report.negative_outcomes.denominator == 40
    assert report.languages[0].answerable_positive_cases == 30
    assert report.languages[0].answered_positive_cases == 30
    assert report.numeric_status == "pass"


def test_negative_answer_is_a_safety_failure_not_a_positive_success(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    changed = _replace(batch, case_id="negative-000", outcome="answer")
    report = evaluate_cloud_knowledge_evidence(changed)
    assert report.negative_outcomes.numerator == 39
    assert report.negative_outcomes.denominator == 40
    assert report.negative_answer_count == 1
    assert report.languages[0].complete_evidence_at_8.denominator == 30
    assert report.numeric_status == "fail"


def test_development_success_and_negative_claim_volume_cannot_wash_material_errors(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    cases = {(case.case_id, case.language): case for case in batch.plan.question_set.cases}
    items: list[CloudKnowledgeEvaluationObservation] = []
    for item in batch.observations:
        case = cases[(item.case_id, item.language)]
        updates = (
            {"supported_material_claim_count": 18}
            if case.kind != "negative" and case.split == "held_out"
            else {
                "claim_count": MAX_CLAIMS,
                "cited_claim_count": MAX_CLAIMS,
                "material_claim_count": MAX_CLAIMS,
                "supported_material_claim_count": MAX_CLAIMS,
                "citation_count": MAX_CLAIMS,
                "returned_evidence_ids": item.returned_evidence_ids or ("reference:negative",),
            }
        )
        items.append(
            CloudKnowledgeEvaluationObservation.model_validate(item.model_dump() | updates)
        )
    report = _report_for(batch, tuple(items))
    held_out = report.held_out_positive_material_claim_support
    assert (held_out.numerator, held_out.denominator) == (1080, 1200)
    assert report.material_claim_support.status == "pass"
    assert held_out.status == report.numeric_status == "fail"


def test_material_support_uses_integer_cross_products_at_exact_ninety_five_percent(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    observations = tuple(
        item.model_copy(update={"supported_material_claim_count": 19})
        if item.material_claim_count
        else item
        for item in batch.observations
    )
    changed = CloudKnowledgeEvaluationBatch(plan=batch.plan, observations=observations)
    report = evaluate_cloud_knowledge_evidence(changed)
    assert report.material_claim_support.numerator == 2280
    assert report.material_claim_support.denominator == 2400
    assert report.held_out_positive_material_claim_support.numerator == 1140
    assert report.held_out_positive_material_claim_support.denominator == 1200
    assert report.numeric_status == "pass"
    report = evaluate_cloud_knowledge_evidence(_replace(changed, supported_material_claim_count=18))
    assert report.material_claim_support.numerator == 2279
    assert report.held_out_positive_material_claim_support.numerator == 1139
    assert report.numeric_status == "fail"
    metric = CloudKnowledgeEvaluationMetric(
        numerator=949_999,
        denominator=1_000_000,
        observations=1,
        missing_observations=0,
        minimum_denominator=1,
        target_basis_points=9500,
    )
    assert metric.status == "fail"


@pytest.mark.parametrize("case_id", ["single-000", "single-039"])
def test_zero_tolerance_guards_cover_development_as_well_as_held_out(
    batch: CloudKnowledgeEvaluationBatch, case_id: str
) -> None:
    for updates in (
        {"supported_material_claim_count": 19, "supported_critical_claim_count": 0},
        {"cited_claim_count": 19, "citation_count": 100_000},
        {"unapproved_effect": True},
    ):
        report = evaluate_cloud_knowledge_evidence(_replace(batch, case_id=case_id, **updates))
        assert report.numeric_status == "fail"
        if "supported_critical_claim_count" in updates:
            assert report.unsupported_critical_claim_count == 1
        if "cited_claim_count" in updates:
            assert report.uncited_claim_count == 1


def test_known_safety_failure_is_not_hidden_by_missing_instances(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    changed = _replace(batch, unapproved_effect=True)
    one = next(item for item in changed.observations if item.unapproved_effect)
    report = _report_for(batch, (one,))
    assert report.unapproved_effects.numerator == 0
    assert report.unapproved_effect_count == 1
    assert report.missing_observation_count == 159
    assert report.numeric_status == "fail"


def test_zero_claim_denominators_and_empty_positive_answers_do_not_pass(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    empty = {
        "claim_count": 0,
        "cited_claim_count": 0,
        "material_claim_count": 0,
        "supported_material_claim_count": 0,
        "critical_claim_count": 0,
        "supported_critical_claim_count": 0,
        "citation_count": 0,
    }
    report = evaluate_cloud_knowledge_evidence(_replace(batch, **empty))
    assert report.empty_positive_answer_count == 1
    assert report.numeric_status == "fail"
    observations = tuple(
        item.model_copy(update=empty | {"outcome": "hold"}) for item in batch.observations
    )
    report = _report_for(batch, observations)
    assert report.material_claim_support.status == "no_evidence"
    assert report.critical_claim_support.status == "no_evidence"
    assert report.claim_citations.status == "no_evidence"
    assert report.numeric_status == "hold"


@pytest.mark.parametrize(
    "field",
    [
        "claim_count",
        "cited_claim_count",
        "material_claim_count",
        "supported_material_claim_count",
        "critical_claim_count",
        "supported_critical_claim_count",
        "citation_count",
    ],
)
@pytest.mark.parametrize("value", [True, False, -1, 1.0, "1", None, 10**400])
def test_counts_reject_coercion_overflow_and_boolean_denominators(
    batch: CloudKnowledgeEvaluationBatch, field: str, value: object
) -> None:
    raw = batch.observations[0].model_dump() | {field: value}
    with pytest.raises(ValidationError):
        CloudKnowledgeEvaluationObservation.model_validate(raw)


@pytest.mark.parametrize("field", ["latency_ms", "cost_usd"])
@pytest.mark.parametrize(
    "value", [True, False, "0", -1, None, float("nan"), float("inf"), -float("inf"), 10**400]
)
def test_metric_numbers_fail_closed_without_unhandled_float_overflow(
    batch: CloudKnowledgeEvaluationBatch, field: str, value: object
) -> None:
    raw = batch.observations[0].model_dump() | {field: value}
    with pytest.raises(ValidationError, match="finite nonnegative numbers"):
        CloudKnowledgeEvaluationObservation.model_validate(raw)


@pytest.mark.parametrize(
    ("field", "value"),
    [("latency_ms", 10**9 + 1), ("cost_usd", 10**6 + 1), ("claim_count", MAX_CLAIMS + 1)],
)
def test_finite_values_still_respect_hard_metric_and_count_ceilings(
    batch: CloudKnowledgeEvaluationBatch, field: str, value: int
) -> None:
    raw = batch.observations[0].model_dump() | {field: value}
    with pytest.raises(ValidationError):
        CloudKnowledgeEvaluationObservation.model_validate(raw)


@pytest.mark.parametrize("value", [0, 1, "false", "true", None])
def test_unapproved_effect_is_a_required_strict_boolean(
    batch: CloudKnowledgeEvaluationBatch, value: object
) -> None:
    with pytest.raises(ValidationError):
        CloudKnowledgeEvaluationObservation.model_validate(
            batch.observations[0].model_dump() | {"unapproved_effect": value}
        )
    raw = batch.observations[0].model_dump()
    del raw["unapproved_effect"]
    with pytest.raises(ValidationError):
        CloudKnowledgeEvaluationObservation.model_validate(raw)


@pytest.mark.parametrize(
    "updates",
    [
        {"material_claim_count": 21},
        {"critical_claim_count": 21},
        {"supported_material_claim_count": 21},
        {"supported_critical_claim_count": 2},
        {"supported_material_claim_count": 0},
        {"supported_critical_claim_count": 0},
        {"cited_claim_count": 21},
        {"citation_count": 19},
        {"cited_claim_count": 0},
        {"returned_evidence_ids": ()},
        {"returned_evidence_ids": ("duplicate", "duplicate")},
        {"returned_evidence_ids": tuple(f"evidence:{index}" for index in range(65))},
    ],
)
def test_inconsistent_support_subsets_and_fraudulent_citation_counts_are_invalid(
    batch: CloudKnowledgeEvaluationBatch, updates: dict[str, object]
) -> None:
    raw = batch.observations[0].model_dump() | updates
    with pytest.raises(ValidationError):
        CloudKnowledgeEvaluationObservation.model_validate(raw)


def test_gold_sets_require_disjoint_unique_representable_evidence(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    case = batch.plan.question_set.cases[0]
    for updates in (
        {"required_evidence_ids": ()},
        {"required_evidence_ids": ("same", "same")},
        {"required_evidence_ids": tuple(f"evidence:{index}" for index in range(9))},
        {"forbidden_evidence_ids": case.required_evidence_ids},
        {"kind": "negative"},
    ):
        with pytest.raises(ValidationError):
            CloudKnowledgeEvaluationCase.model_validate(case.model_dump() | updates)


def test_array_byte_and_instance_bounds_do_not_consume_arbitrary_iterators(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    case = batch.plan.question_set.cases[0]

    def forbidden_iterator() -> Iterator[CloudKnowledgeEvaluationCase]:
        pytest.fail("untrusted iterator was consumed")
        yield case

    for value in (forbidden_iterator(), (case,) * (MAX_OBSERVATIONS + 1)):
        with pytest.raises(ValidationError):
            CloudKnowledgeQuestionSet.model_validate({"cases": value})
    for question in (" ", "a" * 4097, "한" * 3000, "\ud800"):
        with pytest.raises(ValidationError):
            CloudKnowledgeEvaluationCase.model_validate(case.model_dump() | {"question": question})


@pytest.mark.parametrize("field", ["claim_count", "cost_usd", "unapproved_effect"])
def test_unchecked_model_copy_cannot_bypass_the_evaluator_boundary(
    batch: CloudKnowledgeEvaluationBatch, field: str
) -> None:
    corrupted = batch.observations[0].model_copy(update={field: "private-invalid-value"})
    unchecked = batch.model_copy(update={"observations": (corrupted, *batch.observations[1:])})
    with pytest.raises(CloudKnowledgeEvaluationError) as error:
        evaluate_cloud_knowledge_evidence(unchecked)
    assert "private-invalid-value" not in str(error.value)


def test_unchecked_nested_plan_and_extra_authority_are_revalidated(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    incomplete = batch.plan.question_set.model_copy(
        update={"cases": batch.plan.question_set.cases[1:]}
    )
    for plan in (
        batch.plan.model_copy(update={"production_qualified": True}),
        batch.plan.model_copy(update={"question_set": incomplete}),
    ):
        unchecked = CloudKnowledgeEvaluationBatch.model_construct(
            plan=plan, observations=batch.observations
        )
        with pytest.raises(CloudKnowledgeEvaluationError):
            evaluate_cloud_knowledge_evidence(unchecked)


def test_development_material_failure_is_reported_independently_of_held_out_success(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    changed = batch
    for index in range(20, 27):
        changed = _replace(changed, case_id=f"single-{index:03d}", supported_material_claim_count=1)
    report = evaluate_cloud_knowledge_evidence(changed)
    assert report.material_claim_support.status == "fail"
    assert report.held_out_positive_material_claim_support.status == "pass"
    assert report.numeric_status == "fail"


def test_order_permutations_preserve_digests_and_exact_diagnostics(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    questions = CloudKnowledgeQuestionSet(cases=tuple(reversed(batch.plan.question_set.cases)))
    plan = CloudKnowledgeEvaluationPlan.model_validate(
        batch.plan.model_dump() | {"question_set": questions}
    )
    reordered = CloudKnowledgeEvaluationBatch(
        plan=plan, observations=tuple(reversed(batch.observations))
    )
    assert plan.digest == batch.plan.digest
    assert canonical_bytes(evaluate_cloud_knowledge_evidence(reordered)) == canonical_bytes(
        evaluate_cloud_knowledge_evidence(batch)
    )


def test_nearest_rank_performance_counts_every_outcome_and_stays_finite(
    batch: CloudKnowledgeEvaluationBatch,
) -> None:
    observations = tuple(
        item.model_copy(update={"latency_ms": index, "cost_usd": 0.125})
        for index, item in enumerate(batch.observations, start=1)
    )
    report = _report_for(batch, observations)
    assert report.performance.observation_count == 160
    assert report.performance.latency_p50_ms == 80
    assert report.performance.latency_p95_ms == 152
    assert report.performance.latency_max_ms == 160
    assert report.performance.cost_total_usd == 20
    maximum = tuple(
        item.model_copy(update={"latency_ms": 10**9, "cost_usd": 10**6})
        for item in batch.observations
    )
    report = _report_for(batch, maximum)
    assert report.performance.cost_total_usd == 160_000_000
    assert math.isfinite(report.performance.cost_total_usd)
    json.dumps(report.model_dump(mode="json"), allow_nan=False)

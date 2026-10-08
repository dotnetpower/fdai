"""Pre-registered agreement-gated qualification over synthetic verified pass reports."""

import math

import pytest
from fdai.delivery.catalog_search.ontology_evaluation import OntologyRetrievalEvaluationCase
from fdai.delivery.catalog_search.ontology_evaluation_runner import OntologyRetrievalMeasurement
from fdai.delivery.catalog_search.ontology_semantic_evaluation import (
    OntologySemanticEvaluationReport,
)
from fdai.delivery.catalog_search.ontology_semantic_qualification import (
    PROTOCOL_ID,
    OntologyQualificationGroup,
    OntologyQualificationProtocol,
    clopper_pearson_upper,
    gate_agreement,
    qualify_agreement_gated_passes,
)

_A, _B, _C = "object:Resource:a", "object:Resource:b", "object:Resource:c"


def _cases(per_language: int = 50) -> tuple[OntologyRetrievalEvaluationCase, ...]:
    cases = []
    for language in ("en", "ko"):
        for index in range(per_language):
            answerable = index % 2 == 0
            cases.append(
                OntologyRetrievalEvaluationCase(
                    case_id=f"{language}-{index:03d}",
                    query=f"{language} query {index}",
                    cohort=f"{language}-{'positive' if answerable else 'negative'}",
                    expected_document_ids=(_A,) if answerable else (),
                )
            )
    return tuple(cases)


def _report(
    cases: tuple[OntologyRetrievalEvaluationCase, ...],
    overrides: dict[str, tuple[str, ...]] | None = None,
    *,
    binding: str = "sha256:" + "1" * 64,
    stage: str = "holdout",
) -> OntologySemanticEvaluationReport:
    overrides = overrides or {}
    measurements = tuple(
        OntologyRetrievalMeasurement(
            case.case_id,
            "sha256:" + "2" * 64,
            overrides.get(case.case_id, case.expected_document_ids),
            "sha256:" + "3" * 64,
        )
        for case in cases
    )
    return OntologySemanticEvaluationReport(
        binding,
        stage,  # type: ignore[arg-type]
        measurements,
        tuple("selected" for _ in cases),
        tuple("sha256:" + "4" * 64 for _ in cases),
        (None, None),  # type: ignore[arg-type]
        (),
        (),
        len(cases),
        1.0,
    )


def _digests(count: int, offset: int = 0) -> tuple[str, ...]:
    return tuple(f"sha256:{index + offset:064x}" for index in range(count))


def _qualify(cases, passes, digests=None):  # type: ignore[no-untyped-def]
    return qualify_agreement_gated_passes(
        groups=(
            OntologyQualificationGroup(
                tuple(cases), tuple(passes), tuple(digests or _digests(len(passes)))
            ),
        )
    )


def test_clopper_pearson_upper_matches_the_closed_form_for_zero_failures() -> None:
    assert math.isclose(clopper_pearson_upper(0, 100), 1 - 0.05 ** (1 / 100), rel_tol=1e-6)
    assert clopper_pearson_upper(1, 300) < clopper_pearson_upper(2, 300)
    assert clopper_pearson_upper(3, 3) == 1.0
    with pytest.raises(ValueError):
        clopper_pearson_upper(1, 0)


def test_disagreement_becomes_a_clarification_not_a_wrong_selection() -> None:
    cases = _cases(2)
    first = _report(cases, {"en-001": (_B,)})
    second = _report(cases, {"en-000": (_B,)})

    decisions = {item.case_id: item for item in gate_agreement(cases, (first, second))}

    assert not decisions["en-001"].agreed and decisions["en-001"].selected == frozenset()
    assert not decisions["en-001"].wrong
    assert not decisions["en-000"].agreed and not decisions["en-000"].correct
    assert decisions["ko-000"].correct


def test_agreed_extra_or_no_match_selection_is_wrong() -> None:
    cases = _cases(2)
    passes = (_report(cases, {"en-000": (_A, _C), "en-001": (_B,)}),) * 2

    decisions = {item.case_id: item for item in gate_agreement(cases, passes)}

    assert decisions["en-000"].wrong and decisions["en-001"].wrong


def test_clean_passes_qualify_and_carry_no_authority() -> None:
    cases = _cases()
    report = _qualify(cases, (_report(cases),) * 6)

    assert report.passed and report.protocol_id == PROTOCOL_ID
    assert report.decisions == 300 and report.wrong == 0
    assert report.production_qualification is False and report.execution_authority is False


def test_one_agreed_wrong_selection_fails_a_small_language_bound() -> None:
    cases = _cases()
    passes = [_report(cases) for _ in range(6)]
    passes[0] = passes[1] = _report(cases, {"ko-001": (_B,)})

    report = _qualify(cases, passes)

    assert report.wrong == 1
    assert "ko-wrong-selection-bound-exceeded" in report.failure_codes


def test_random_disagreements_cost_only_the_correct_rate() -> None:
    cases = _cases()
    passes = [_report(cases) for _ in range(6)]
    passes[0] = _report(cases, {"en-000": (_B,), "en-002": ()})

    report = _qualify(cases, passes)

    assert report.wrong == 0 and report.disagreements == 2
    english = next(item for item in report.languages if item.language == "en")
    assert english.correct == english.answerable - 2
    assert report.passed


def test_many_clarifications_fail_the_correct_rate() -> None:
    cases = _cases()
    overrides = {case.case_id: () for case in cases[:10]}
    report = _qualify(cases, (_report(cases, overrides),) * 6)
    assert report.failure_codes == ("en-correct-rate-below-threshold",)


@pytest.mark.parametrize("problem", ["count", "binding", "stage", "duplicate-evidence", "order"])
def test_invalid_pass_sets_are_refused(problem: str) -> None:
    cases = _cases(2)
    passes = [_report(cases) for _ in range(6)]
    digests = list(_digests(6))
    if problem == "count":
        passes = passes[:5]
        digests = digests[:5]
    elif problem == "binding":
        passes[3] = _report(cases, binding="sha256:" + "9" * 64)
    elif problem == "stage":
        passes[3] = _report(cases, stage="calibration")
    elif problem == "duplicate-evidence":
        digests[5] = digests[0]
    else:
        passes[2] = _report(tuple(reversed(cases)))
    with pytest.raises(ValueError):
        _qualify(cases, passes, digests)


def test_protocol_parameters_are_pre_registered() -> None:
    with pytest.raises(ValueError):
        OntologyQualificationProtocol(min_language_correct_rate=0.9)
    with pytest.raises(ValueError):
        OntologyQualificationProtocol(passes_per_decision=1)


def test_two_case_sets_pool_into_one_judgement() -> None:
    first, second = (
        _cases(32),
        tuple(
            OntologyRetrievalEvaluationCase(
                case_id=f"b-{case.case_id}",
                query=case.query,
                cohort=case.cohort,
                expected_document_ids=case.expected_document_ids,
            )
            for case in _cases(32)
        ),
    )
    single = _qualify(first, (_report(first),) * 6)
    pooled = qualify_agreement_gated_passes(
        groups=(
            OntologyQualificationGroup(first, (_report(first),) * 6, _digests(6)),
            OntologyQualificationGroup(
                second,
                (_report(second, binding="sha256:" + "8" * 64),) * 6,
                _digests(6, offset=6),
            ),
        )
    )

    assert "en-wrong-selection-bound-exceeded" in single.failure_codes
    assert pooled.passed and pooled.decisions == 384


def test_groups_cannot_share_evidence_or_bindings() -> None:
    cases = _cases(2)
    group = OntologyQualificationGroup(cases, (_report(cases),) * 6, _digests(6))
    with pytest.raises(ValueError):
        qualify_agreement_gated_passes(groups=(group, group))

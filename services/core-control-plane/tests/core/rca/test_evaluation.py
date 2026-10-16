"""Local synthetic causal labels exercise the real offline evaluator."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict, replace
from datetime import UTC, datetime, timedelta
from inspect import getsource

import pytest
from fdai.core.detection.series import MetricSample
from fdai.core.ontology_platform.metric_semantics import (
    CausalJoinStatus,
    MetricWindow,
    join_causal_evidence,
)
from fdai.core.ontology_platform.topology_history import TopologyGraphAt, topology_diff
from fdai.core.rca.evaluation import (
    MAX_CASES,
    MAX_EVIDENCE_REFS,
    MAX_RESULTS,
    CausalEvaluationCase,
    CausalEvaluationEvidence,
    CausalEvaluationReceipt,
    CausalEvaluationResult,
    evaluate_causal_quality,
)
from fdai.core.rca.evaluation import (
    CausalEvaluationDisposition as Disposition,
)
from fdai.core.rca.evaluation import (
    CausalEvaluationProvenance as Provenance,
)
from fdai.core.rca.temporal_causality import TemporalCausalityAnalyzer, TemporalCausalityConfig
from fdai.shared.contracts.models import CausalEvidenceGrade
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai_service_contracts.ontology_query import content_digest

_LABEL_REVISION = content_digest({"reviewed_labels": "causal-fixtures-v1"})
_RUNNER_REVISION = content_digest({"runner": "retained-typed-results-v1"})


def _evidence(
    ref: str, facts: object, provenance: Provenance = Provenance.SYNTHETIC
) -> CausalEvaluationEvidence:
    return CausalEvaluationEvidence(ref, content_digest(facts), provenance)


def _case(
    case_id: str,
    disposition: Disposition,
    cause: str | None,
    evidence: tuple[CausalEvaluationEvidence, ...],
) -> CausalEvaluationCase:
    return CausalEvaluationCase(
        case_id=case_id,
        labeler_id="independent-fixture-review",
        label_source_revision=_LABEL_REVISION,
        label_method="reviewed-mechanism-and-dependency-v1",
        label_provenance=Provenance.LOCAL_FIXTURE,
        expected_disposition=disposition,
        expected_cause_ref=cause,
        evidence=evidence,
    )


def _cases() -> tuple[CausalEvaluationCase, ...]:
    # Labels are authored independently of _results; neither is derived from the other.
    return (
        _case(
            "known-cause",
            Disposition.SUPPORTED,
            "change:cache",
            (
                _evidence("ev:rollback", {"change": "change:cache", "effect_reversed": True}),
                _evidence("ev:path", {"depends_on": ["service:api", "resource:cache"]}),
            ),
        ),
        _case(
            "confounder",
            Disposition.UNRESOLVED,
            None,
            (_evidence("ev:traffic", {"common_driver": "traffic", "competitors_tested": False}),),
        ),
        _case(
            "ambiguous",
            Disposition.UNRESOLVED,
            None,
            (_evidence("ev:tied", {"candidate_changes": ["change:a", "change:b"]}),),
        ),
        _case(
            "reversed-dependency",
            Disposition.UNRESOLVED,
            None,
            (_evidence("ev:reverse", {"depends_on": ["resource:cache", "service:api"]}),),
        ),
        _case(
            "unrelated-dependency",
            Disposition.UNRESOLVED,
            None,
            (_evidence("ev:unrelated", {"depends_on": ["service:other", "resource:other"]}),),
        ),
        _case("insufficient-evidence", Disposition.UNAVAILABLE, None, ()),
        _case(
            "refuted-cause",
            Disposition.REFUTED,
            "change:canary",
            (
                _evidence(
                    "ev:negative-prediction",
                    {"required_prediction": False, "complete": True, "independent": True},
                ),
            ),
        ),
    )


def _results() -> tuple[CausalEvaluationResult, ...]:
    return (
        CausalEvaluationResult(
            "known-cause", Disposition.SUPPORTED, "change:cache", ("ev:path", "ev:rollback")
        ),
        CausalEvaluationResult("confounder", Disposition.UNRESOLVED, None, ("ev:traffic",)),
        CausalEvaluationResult("ambiguous", Disposition.UNRESOLVED, None, ("ev:tied",)),
        CausalEvaluationResult(
            "reversed-dependency", Disposition.UNRESOLVED, None, ("ev:reverse",)
        ),
        CausalEvaluationResult(
            "unrelated-dependency", Disposition.UNRESOLVED, None, ("ev:unrelated",)
        ),
        CausalEvaluationResult("insufficient-evidence", Disposition.UNAVAILABLE, None),
        CausalEvaluationResult(
            "refuted-cause", Disposition.REFUTED, "change:canary", ("ev:negative-prediction",)
        ),
    )


def _evaluate(
    results: tuple[CausalEvaluationResult, ...] | None = None,
    cases: tuple[CausalEvaluationCase, ...] | None = None,
) -> CausalEvaluationReceipt:
    return evaluate_causal_quality(
        cases=_cases() if cases is None else cases,
        results=_results() if results is None else results,
        runner_id="typed-fixture-runner",
        runner_source_revision=_RUNNER_REVISION,
        runner_method="retained-results-v1",
    )


def test_actual_evaluator_scores_reviewed_causal_cases() -> None:
    receipt = _evaluate()
    metrics = receipt.metrics
    assert metrics.denominator == metrics.completed_cases == metrics.correct_cases == 7
    assert metrics.accuracy == metrics.completion_coverage == metrics.cause_recall == 1.0
    assert metrics.expected_cause_claims == metrics.correct_cause_claims == 1
    assert metrics.unsupported_cause_claims == metrics.unjustified_holds == 0
    assert metrics.justified_holds == 5
    assert metrics.valid_citations == 7
    assert metrics.invalid_citations == 0
    assert metrics.citation_validity == 1.0
    assert receipt.receipt_id == f"causal-evaluation:{receipt.receipt_digest[7:]}"
    assert receipt.case_set_digest == content_digest([asdict(case) for case in receipt.cases])
    assert not receipt.deployed_qualification
    assert not receipt.mutation_authority
    assert not receipt.promotion_authority


@pytest.mark.parametrize("index", [1, 2, 3, 4, 5, 6])
def test_unsupported_claims_on_confounder_reverse_unrelated_and_missing_evidence(
    index: int,
) -> None:
    results = list(_results())
    original = results[index]
    results[index] = CausalEvaluationResult(
        original.case_id,
        Disposition.SUPPORTED,
        original.actual_cause_ref or "change:cache",
        original.cited_evidence_refs,
    )
    metrics = _evaluate(tuple(results)).metrics
    assert metrics.denominator == metrics.completed_cases == 7
    assert metrics.correct_cases == 6
    assert metrics.correct_cause_claims == 1
    assert metrics.unsupported_cause_claims == 1
    assert metrics.accuracy == 6 / 7


def test_wrong_cause_identity_and_wrong_refutation_fail_case_accuracy() -> None:
    results = list(_results())
    results[0] = replace(results[0], actual_cause_ref="change:other")
    results[6] = replace(results[6], actual_cause_ref="change:not-the-tested-candidate")
    metrics = _evaluate(tuple(results)).metrics
    assert metrics.correct_cases == 5
    assert metrics.correct_cause_claims == 0
    assert metrics.unsupported_cause_claims == 1
    assert metrics.cause_recall == 0.0


@pytest.mark.parametrize("fabricated", ["ev:fabricated", "ev:path-suffix", "ev:traffic"])
def test_citations_are_exact_and_case_local(fabricated: str) -> None:
    result = replace(_results()[0], cited_evidence_refs=("ev:path", fabricated))
    receipt = _evaluate((result, *_results()[1:]))
    assert receipt.metrics.invalid_citations == 1
    assert receipt.metrics.citation_validity == 6 / 7
    assert receipt.metrics.unsupported_cause_claims == 1
    assert receipt.metrics.correct_cases == 6
    assert receipt.cases[3].allowed_evidence_refs == ("ev:path", "ev:rollback")


def test_uncited_claims_and_fabricated_hold_citations_do_not_earn_credit() -> None:
    results = list(_results())
    results[0] = replace(results[0], cited_evidence_refs=())
    results[1] = replace(results[1], cited_evidence_refs=("ev:made-up",))
    metrics = _evaluate(tuple(results)).metrics
    assert metrics.uncited_determinate_results == 1
    assert metrics.unsupported_cause_claims == 1
    assert metrics.justified_holds == 4
    assert metrics.unjustified_holds == 1
    assert metrics.correct_cases == 5


@pytest.mark.parametrize(
    ("disposition", "justified"),
    [(Disposition.UNRESOLVED, 4), (Disposition.UNAVAILABLE, 1)],
)
def test_always_held_runner_is_safe_but_not_perfectly_accurate(
    disposition: Disposition, justified: int
) -> None:
    held = tuple(
        CausalEvaluationResult(case_id, disposition, None)
        for case_id in (
            "known-cause",
            "confounder",
            "ambiguous",
            "reversed-dependency",
            "unrelated-dependency",
            "insufficient-evidence",
            "refuted-cause",
        )
    )
    metrics = _evaluate(held).metrics
    assert metrics.unsupported_cause_claims == 0
    assert metrics.correct_cause_claims == 0
    assert metrics.cause_recall == 0.0
    assert metrics.justified_holds == justified
    assert metrics.unjustified_holds == metrics.denominator - justified
    assert metrics.completion_coverage == 1.0
    assert metrics.accuracy == justified / metrics.denominator
    assert metrics.citation_validity is None


def test_missing_results_preserve_denominator_and_are_not_justified_holds() -> None:
    partial = _evaluate(_results()[1:]).metrics
    assert partial.missing_case_ids == ("known-cause",)
    assert partial.accuracy == partial.completion_coverage == 6 / 7
    assert partial.cause_recall == 0.0
    empty = _evaluate(()).metrics
    assert empty.denominator == 7
    assert empty.correct_cases == empty.completed_cases == empty.justified_holds == 0
    assert empty.accuracy == empty.completion_coverage == empty.cause_recall == 0.0
    assert len(empty.missing_case_ids) == 7


def test_duplicate_and_unknown_results_are_accounted_without_cherry_picking() -> None:
    wrong = replace(_results()[0], actual_cause_ref="change:other")
    unknown = CausalEvaluationResult("unknown", Disposition.SUPPORTED, "change:a", ("ev:path",))
    receipt = _evaluate((*_results(), wrong, unknown, unknown))
    metrics = receipt.metrics
    assert metrics.denominator == 7
    assert metrics.submitted_results == 10
    assert metrics.completed_cases == metrics.correct_cases == 6
    assert metrics.duplicate_results == 2
    assert metrics.duplicate_case_ids == ("known-cause", "unknown")
    assert metrics.unknown_results == 2
    assert metrics.unknown_case_ids == ("unknown",)
    assert metrics.missing_case_ids == ()
    assert metrics.correct_cause_claims == 0
    assert metrics.unsupported_cause_claims == 4
    assert metrics.invalid_citations == 2


def test_duplicate_identical_results_are_not_a_single_successful_case() -> None:
    metrics = _evaluate((*_results(), _results()[0])).metrics
    assert metrics.completed_cases == metrics.correct_cases == 6
    assert metrics.unsupported_cause_claims == 2
    assert metrics.duplicate_results == 1


def test_reordering_cases_results_evidence_and_duplicate_submissions_is_canonical() -> None:
    cases = tuple(replace(case, evidence=case.evidence[::-1]) for case in _cases()[::-1])
    results = (*_results(), replace(_results()[0], actual_cause_ref="change:other"))
    reversed_results = tuple(
        replace(result, cited_evidence_refs=result.cited_evidence_refs[::-1])
        for result in results[::-1]
    )
    assert _evaluate(results) == _evaluate(reversed_results, cases)


@pytest.mark.parametrize(
    "change", ["evidence", "label", "method", "source", "result", "provenance", "label_provenance"]
)
def test_meaningful_changes_change_content_identity(change: str) -> None:
    original = _evaluate()
    cases, results = list(_cases()), list(_results())
    if change == "evidence":
        ev = replace(cases[0].evidence[0], source_revision=content_digest({"new_evidence": True}))
        cases[0] = replace(cases[0], evidence=(ev, *cases[0].evidence[1:]))
    elif change == "label":
        cases[0] = replace(cases[0], expected_cause_ref="change:other")
    elif change == "method":
        cases[0] = replace(cases[0], label_method="independent-review-v2")
    elif change == "source":
        cases[0] = replace(cases[0], label_source_revision=content_digest({"labels": "v2"}))
    elif change == "provenance":
        ev = replace(cases[0].evidence[0], provenance=Provenance.LOCAL_FIXTURE)
        cases[0] = replace(cases[0], evidence=(ev, *cases[0].evidence[1:]))
    elif change == "label_provenance":
        cases[0] = replace(cases[0], label_provenance=Provenance.SYNTHETIC)
    else:
        results[0] = replace(results[0], cited_evidence_refs=("ev:path",))
    changed = _evaluate(tuple(results), tuple(cases))
    assert changed.receipt_digest != original.receipt_digest
    assert (changed.result_set_digest != original.result_set_digest) == (change == "result")


def test_declared_governed_provenance_never_grants_qualification_or_authority() -> None:
    cases = tuple(
        replace(
            case,
            evidence=tuple(
                replace(ev, provenance=Provenance.GOVERNED_OPERATIONAL) for ev in case.evidence
            ),
        )
        for case in _cases()
    )
    receipt = _evaluate(cases=cases)
    assert not receipt.deployed_qualification
    assert not receipt.mutation_authority
    assert not receipt.promotion_authority
    assert all(case.label_provenance is Provenance.LOCAL_FIXTURE for case in receipt.cases)
    with pytest.raises(FrozenInstanceError):
        receipt.mutation_authority = True  # type: ignore[misc, assignment]
    with pytest.raises(TypeError):
        replace(receipt, deployed_qualification=True)
    with pytest.raises(FrozenInstanceError):
        receipt.metrics.correct_cases = 999  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        receipt.cases[0].label_method = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("invalid", ["", " ", "bad\nref", "x" * 257, float("nan")])
def test_malformed_or_nonfinite_evidence_inputs_fail_closed(invalid: str) -> None:
    with pytest.raises(ValueError):
        _evidence(invalid, {})
    with pytest.raises(ValueError):
        _evidence("ev:test", {"raw_numeric_evidence": float("nan")})


def test_case_sets_require_unique_independent_labels_and_positive_exposure() -> None:
    with pytest.raises(ValueError, match="unique stable case ids"):
        _evaluate(cases=(*_cases(), _cases()[0]))
    with pytest.raises(ValueError, match="non-empty"):
        _evaluate(cases=())
    with pytest.raises(ValueError, match="supported cause label"):
        _evaluate(cases=_cases()[1:])
    with pytest.raises(ValueError, match="independently"):
        replace(_evaluate(), runner_id="independent-fixture-review")


def test_bounds_mutability_and_malformed_source_revisions_fail_closed() -> None:
    with pytest.raises(ValueError, match="cases MUST be an immutable typed tuple"):
        _evaluate(cases=list(_cases()))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at most"):
        _evaluate(cases=(_cases()[0],) * (MAX_CASES + 1))
    with pytest.raises(ValueError, match="at most"):
        _evaluate(results=(_results()[0],) * (MAX_RESULTS + 1))
    with pytest.raises(ValueError, match="at most"):
        replace(_results()[0], cited_evidence_refs=("ev:a",) * (MAX_EVIDENCE_REFS + 1))
    with pytest.raises(ValueError, match="canonical SHA-256"):
        replace(_cases()[0], label_source_revision="main")
    with pytest.raises(ValueError, match="canonical SHA-256"):
        replace(_cases()[0].evidence[0], source_revision="latest")
    with pytest.raises(ValueError, match="canonical SHA-256"):
        replace(_evaluate(), runner_source_revision="HEAD")
    with pytest.raises(ValueError, match="immutable typed tuple"):
        replace(_cases()[0], evidence=list(_cases()[0].evidence))
    with pytest.raises(ValueError, match="unique"):
        replace(_cases()[0], evidence=(_cases()[0].evidence[0],) * 2)
    with pytest.raises(ValueError, match="unique"):
        replace(_results()[0], cited_evidence_refs=("ev:path", "ev:path"))


@pytest.mark.parametrize("disposition", [Disposition.SUPPORTED, Disposition.REFUTED])
def test_determinate_results_require_a_tested_cause(disposition: Disposition) -> None:
    with pytest.raises(ValueError, match="identify"):
        CausalEvaluationResult("case", disposition, None)
    with pytest.raises(ValueError, match="pinned evidence"):
        _case("case", disposition, "change:a", ())


@pytest.mark.parametrize("disposition", [Disposition.UNRESOLVED, Disposition.UNAVAILABLE])
def test_holds_must_not_smuggle_cause_claims(disposition: Disposition) -> None:
    with pytest.raises(ValueError, match="MUST NOT assert"):
        CausalEvaluationResult("case", disposition, "change:a")
    with pytest.raises(ValueError, match="CausalEvaluationDisposition"):
        CausalEvaluationResult("case", disposition.value, None)  # type: ignore[arg-type]


@pytest.mark.parametrize("case_id", ["Invalid", "has space", "case/child", "a" * 81, 1])
def test_case_identity_is_bounded_and_machine_typed(case_id: str) -> None:
    with pytest.raises(ValueError, match="bounded ASCII identifier"):
        replace(_cases()[0], case_id=case_id)


def test_provenance_is_explicit_for_labels_and_evidence_not_inferred_from_refs() -> None:
    with pytest.raises(ValueError, match="CausalEvaluationProvenance"):
        replace(_cases()[0], label_provenance="local_fixture")
    with pytest.raises(ValueError, match="CausalEvaluationProvenance"):
        replace(_cases()[0].evidence[0], provenance="governed_operational")
    local = _cases()[0].evidence[0]
    assert local.provenance is Provenance.SYNTHETIC
    assert _evaluate().cases[2].label_provenance is Provenance.LOCAL_FIXTURE


@pytest.mark.parametrize(
    "changes",
    [
        {"runner_id": "another-runner"},
        {"runner_method": "retained-results-v2"},
        {"runner_source_revision": content_digest({"runner": "v2"})},
    ],
)
def test_runner_revision_and_method_are_bound_without_relabeling(changes: dict[str, str]) -> None:
    receipt = _evaluate()
    revised = replace(receipt, **changes)
    assert receipt.receipt_digest != revised.receipt_digest
    assert receipt.case_set_digest == revised.case_set_digest
    assert receipt.result_set_digest == revised.result_set_digest
    assert receipt.metrics == revised.metrics


def test_shared_canonical_json_byte_bound_rejects_oversized_cohorts() -> None:
    evidence = tuple(
        _evidence(f"ev:{index}:" + "x" * 240, {"index": index})
        for index in range(MAX_EVIDENCE_REFS)
    )
    cases = tuple(replace(_cases()[0], case_id=f"case-{i}", evidence=evidence) for i in range(8))
    with pytest.raises(ValueError, match="canonical JSON exceeds"):
        _evaluate(cases=cases, results=())


def test_incorrect_refutation_of_known_cause_is_not_safe_accuracy_credit() -> None:
    results = (replace(_results()[0], actual_disposition=Disposition.REFUTED), *_results()[1:])
    metrics = _evaluate(results).metrics
    assert metrics.unsupported_cause_claims == 0
    assert metrics.correct_cause_claims == 0
    assert metrics.correct_cases == 6
    assert metrics.cause_recall == 0.0
    assert metrics.accuracy < 1.0


@pytest.mark.parametrize("size", range(8))
def test_accounting_conserves_denominator_claims_holds_and_citations(size: int) -> None:
    results = (*_results()[:size], _results()[0], _results()[0])
    metrics = _evaluate(results).metrics
    registered = {case.case_id for case in _cases()}
    duplicate_registered = registered.intersection(metrics.duplicate_case_ids)
    assert (
        metrics.completed_cases + len(metrics.missing_case_ids) + len(duplicate_registered)
        == metrics.denominator
    )
    assert metrics.correct_cases <= metrics.completed_cases <= metrics.denominator
    assert metrics.correct_cause_claims + metrics.unsupported_cause_claims == sum(
        result.actual_disposition is Disposition.SUPPORTED for result in results
    )
    assert metrics.justified_holds + metrics.unjustified_holds == sum(
        result.actual_disposition in {Disposition.UNRESOLVED, Disposition.UNAVAILABLE}
        for result in results
    )
    assert metrics.valid_citations + metrics.invalid_citations == sum(
        len(result.cited_evidence_refs) for result in results
    )


def test_real_causal_join_outputs_against_independent_synthetic_fixture_labels() -> None:
    """Measure five local mechanics cases, not operational accuracy or causal entailment."""
    cutoff = datetime(2026, 10, 16, tzinfo=UTC)
    values = (3, 8, 1, 7, 2, 9, 4, 6, 0, 5, 11, 3, 10, 2, 8, 1, 12, 4, 9, 0)
    shifted = (0, *values[:-1])
    config = TemporalCausalityConfig(
        lag_seconds=(0, 60, 120), min_samples=12, min_abs_correlation=0.7
    )
    # Fixed annotations precede execution and do not inspect the join's output.
    # SUPPORTED here means predictive precedence, never interventional causality.
    annotations = (
        ("lagged-driver", Disposition.SUPPORTED, "metric:driver", shifted, ("app", "db")),
        ("synchronous", Disposition.UNRESOLVED, None, values, ("app", "db")),
        ("reverse-topology", Disposition.UNRESOLVED, None, shifted, ("db", "app")),
        ("unrelated-topology", Disposition.UNRESOLVED, None, shifted, ("other", "db")),
        ("short-series", Disposition.UNRESOLVED, None, shifted[:2], ("app", "db")),
    )
    label_revision = content_digest(annotations)

    def window(case_id: str, concept: str, samples: tuple[int, ...]) -> MetricWindow:
        return MetricWindow(
            concept_id=f"metric:{concept}",
            resource_id="db" if concept == "driver" else "app",
            unit="count",
            start=cutoff - timedelta(minutes=len(samples)),
            end=cutoff,
            samples=tuple(
                MetricSample(
                    timestamp=cutoff - timedelta(minutes=len(samples) - index), value=float(value)
                )
                for index, value in enumerate(samples)
            ),
            complete=True,
            evidence_refs=(f"fixture:{case_id}:{concept}",),
        )

    def topology(case_id: str, endpoints: tuple[str, str]) -> TopologyGraphAt:
        # Model the verified-readback contract locally. All evaluation provenance
        # below remains SYNTHETIC; no provider or verifier is actually contacted.
        fact = StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.PROVIDER,
            source_identity="fixture:provider",
            source_revision="fixture:revision",
            effective_at=cutoff - timedelta(hours=1),
            recorded_at=cutoff,
            evidence_cutoff=cutoff,
            freshness_ceiling_seconds=3600,
            completeness=1.0,
            synthetic=False,
            evidence_refs=(f"fixture:{case_id}:topology",),
        )
        metadata = LinkObservationMetadata(
            state_fact=fact,
            verification_method="provider-readback",
            verified=True,
            verifier_identity="fixture:verifier",
            verifier_revision="fixture:v1",
            verification_receipt_ref=f"fixture:{case_id}:verification",
        ).to_mapping()
        link = OntologyLinkRecord(
            "depends_on",
            *endpoints,
            properties={LINK_OBSERVATION_METADATA_PROPERTY: metadata},
        )
        return TopologyGraphAt(
            as_of=cutoff,
            known_at=cutoff,
            graph=OntologyGraphSnapshot(
                objects=tuple(
                    OntologyObjectRecord(key, "Resource", {"id": key})
                    for key in ("app", "db", "other")
                ),
                links=(link,),
            ),
            complete=True,
            revision_ids=("fixture:revision",),
            provider_generation_refs=("fixture:generation",),
            evidence_refs=fact.evidence_refs,
            digest=content_digest({"endpoints": endpoints, "metadata": metadata}),
        )

    cases: list[CausalEvaluationCase] = []
    actual: list[CausalEvaluationResult] = []
    for case_id, expected, expected_cause, effect_values, endpoints in annotations:
        cause = window(case_id, "driver", values[: len(effect_values)])
        effect = window(case_id, "response", effect_values)
        view = topology(case_id, endpoints)
        sources = (
            _evidence(
                cause.evidence_refs[0],
                {"values": values[: len(effect_values)], "start": cause.start.isoformat()},
            ),
            _evidence(
                effect.evidence_refs[0],
                {"values": effect_values, "start": effect.start.isoformat()},
            ),
            CausalEvaluationEvidence(view.evidence_refs[0], view.digest, Provenance.SYNTHETIC),
        )
        cases.append(
            CausalEvaluationCase(
                case_id=case_id,
                labeler_id="independent-local-fixture-annotation",
                label_source_revision=label_revision,
                label_method="fixed-lag-and-directed-topology-fixture-v1",
                label_provenance=Provenance.LOCAL_FIXTURE,
                expected_disposition=expected,
                expected_cause_ref=expected_cause,
                evidence=sources,
            )
        )
        joined = join_causal_evidence(
            cause=cause,
            effect=effect,
            topology_change=topology_diff(view, view),
            feature_cutoff=cutoff,
            config=config,
            competing_explanations=(),
        )
        supported = joined.status is CausalJoinStatus.SUPPORTED
        if supported:
            assert joined.temporal_claim is not None
            assert joined.temporal_claim.lag_seconds == 60
            assert joined.temporal_claim.evidence_grade is CausalEvidenceGrade.PREDICTIVE_PRECEDENCE
        elif case_id == "synchronous":
            assert joined.temporal_claim is not None
            assert joined.temporal_claim.evidence_grade is CausalEvidenceGrade.ASSOCIATION
        elif case_id in {"reverse-topology", "unrelated-topology"}:
            assert "causal_dependency_path_unproven" in joined.limitations
        else:
            assert "insufficient_aligned_samples" in joined.limitations
        actual.append(
            CausalEvaluationResult(
                case_id=case_id,
                actual_disposition=Disposition(joined.status.value),
                actual_cause_ref=(
                    joined.temporal_claim.cause_metric
                    if supported and joined.temporal_claim is not None
                    else None
                ),
                cited_evidence_refs=joined.evidence_refs,
            )
        )

    def score(results: tuple[CausalEvaluationResult, ...]) -> CausalEvaluationReceipt:
        return evaluate_causal_quality(
            cases=tuple(cases),
            results=results,
            runner_id="real-local-causal-join",
            runner_source_revision=content_digest(
                {
                    "join": getsource(join_causal_evidence),
                    "analyzer": getsource(TemporalCausalityAnalyzer),
                    "config": asdict(config),
                }
            ),
            runner_method="local-join-output-to-typed-disposition-v1",
        )

    receipt = score(tuple(actual))
    held = score(
        tuple(CausalEvaluationResult(case.case_id, Disposition.UNRESOLVED, None) for case in cases)
    )
    missing = score(tuple(result for result in actual if result.case_id != "lagged-driver"))
    assert receipt.metrics.denominator == receipt.metrics.completed_cases == 5
    assert receipt.metrics.correct_cases == 5
    assert receipt.metrics.correct_cause_claims == 1
    assert receipt.metrics.justified_holds == 4
    assert receipt.metrics.valid_citations == 15
    assert receipt.metrics.invalid_citations == receipt.metrics.unsupported_cause_claims == 0
    assert held.metrics.correct_cases == held.metrics.justified_holds == 4
    assert held.metrics.unjustified_holds == 1
    assert held.metrics.cause_recall == missing.metrics.cause_recall == 0.0
    assert held.metrics.accuracy == missing.metrics.accuracy == 4 / 5
    assert held.metrics.completion_coverage == 1.0
    assert missing.metrics.completion_coverage == 4 / 5
    assert missing.metrics.missing_case_ids == ("lagged-driver",)
    assert receipt.case_set_digest == held.case_set_digest == missing.case_set_digest
    assert all(
        evidence.provenance is Provenance.SYNTHETIC for case in cases for evidence in case.evidence
    )
    assert not receipt.deployed_qualification
    assert not receipt.mutation_authority

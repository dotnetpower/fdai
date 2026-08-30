from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest
from fdai.core.operational_learning.investigation_strategy import (
    InvestigationStrategyCandidateCompiler,
    InvestigationStrategyCompilationDisposition,
    InvestigationStrategyHoldReason,
    compile_investigation_strategy_candidate,
)
from fdai.core.operational_learning.investigation_strategy_evidence import (
    InvestigationStrategyComparisonEvidence,
)
from fdai.core.rca.discrimination import (
    HypothesisDiscriminationFrame,
    HypothesisDiscriminationSelection,
)
from fdai.core.rca.discrimination_shadow import (
    DiscriminationShadowComparison,
    run_discrimination_shadow,
)
from tests.core.rca.test_discrimination_shadow import (
    _ACTIVE,
    _CHALLENGER,
    _candidates,
    _frame,
    _selector_for,
)

_OTHER_CHALLENGER = f"sha256:{'6' * 64}"


def _comparison(
    *,
    improvement: bool,
    active_digest: str = _ACTIVE,
    challenger_digest: str = _CHALLENGER,
    safety_failure: bool = False,
    invariant_failure: bool = False,
) -> DiscriminationShadowComparison:
    frame = _frame()
    weak, strong = _candidates(frame)
    active = weak if improvement else strong
    challenger = strong if improvement else weak
    return run_discrimination_shadow(
        frame=frame,
        candidates=(weak, strong),
        active_strategy_digest=active_digest,
        challenger_strategy_digest=challenger_digest,
        active_selector=_selector_for(active),
        challenger_selector=_selector_for(challenger),
        safety_failure=safety_failure,
        invariant_failure=invariant_failure,
    )


def _held_comparison() -> DiscriminationShadowComparison:
    frame = _frame()

    def fail(
        _frame: HypothesisDiscriminationFrame,
        _candidates: tuple[object, ...],
    ) -> HypothesisDiscriminationSelection:
        raise RuntimeError("unavailable")

    return run_discrimination_shadow(
        frame=frame,
        candidates=_candidates(frame),
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=_selector_for(_candidates(frame)[0]),
        challenger_selector=fail,
    )


def test_compiles_balanced_same_pair_cohort_into_inert_norns_candidate() -> None:
    improvement = _comparison(improvement=True)
    non_improvement = _comparison(improvement=False)

    result = compile_investigation_strategy_candidate((improvement, non_improvement))

    assert result.disposition is InvestigationStrategyCompilationDisposition.COMPILED
    assert result.hold_reasons == ()
    candidate = result.candidate
    assert candidate is not None
    assert candidate.owner_agent == "Norns"
    assert candidate.state == "inert"
    assert candidate.active_strategy_digest == _ACTIVE
    assert candidate.challenger_strategy_digest == _CHALLENGER
    assert candidate.sample_size == 2
    assert candidate.challenger_improvement_count == 1
    assert candidate.non_improvement_or_control_count == 1
    assert set(candidate.comparison_refs) == {
        improvement.comparison_id,
        non_improvement.comparison_id,
    }
    assert set(candidate.comparison_digests) == {
        improvement.comparison_digest,
        non_improvement.comparison_digest,
    }


def test_candidate_identity_is_permutation_invariant_and_content_addressed() -> None:
    improvement = _comparison(improvement=True)
    non_improvement = _comparison(improvement=False)

    forward = InvestigationStrategyCandidateCompiler().compile((improvement, non_improvement))
    reverse = InvestigationStrategyCandidateCompiler().compile((non_improvement, improvement))

    assert forward == reverse
    assert forward.candidate is not None
    assert forward.candidate.candidate_digest.startswith("sha256:")
    assert forward.candidate.candidate_id.startswith("investigation-strategy-")
    with pytest.raises(FrozenInstanceError):
        forward.candidate.sample_size = 3  # type: ignore[misc]
    with pytest.raises(ValueError, match="refs MUST match"):
        replace(
            forward.candidate,
            comparison_refs=("discrimination-shadow-forged-0", "discrimination-shadow-forged-1"),
        )


def test_missing_and_unbalanced_evidence_return_typed_holds() -> None:
    empty = compile_investigation_strategy_candidate(())
    improvement = _comparison(improvement=True)
    improvement_only = compile_investigation_strategy_candidate((improvement,))
    non_improvement_only = compile_investigation_strategy_candidate(
        (_comparison(improvement=False),)
    )

    assert empty.disposition is InvestigationStrategyCompilationDisposition.HELD
    assert empty.hold_reasons == (InvestigationStrategyHoldReason.MISSING_EVIDENCE,)
    assert improvement_only.candidate is None
    assert set(improvement_only.hold_reasons) == {
        InvestigationStrategyHoldReason.INSUFFICIENT_COHORT,
        InvestigationStrategyHoldReason.NO_NON_IMPROVEMENT_CONTROL,
    }
    assert set(non_improvement_only.hold_reasons) == {
        InvestigationStrategyHoldReason.INSUFFICIENT_COHORT,
        InvestigationStrategyHoldReason.NO_CHALLENGER_IMPROVEMENT,
    }


def test_conflicting_strategy_pairs_and_duplicate_evidence_hold() -> None:
    improvement = _comparison(improvement=True)
    other_pair = _comparison(
        improvement=False,
        challenger_digest=_OTHER_CHALLENGER,
    )
    mixed = compile_investigation_strategy_candidate((improvement, other_pair))
    duplicate = compile_investigation_strategy_candidate((improvement, improvement))

    assert InvestigationStrategyHoldReason.STRATEGY_PAIR_CONFLICT in mixed.hold_reasons
    assert mixed.candidate is None
    assert InvestigationStrategyHoldReason.EVIDENCE_CONFLICT in duplicate.hold_reasons
    assert duplicate.candidate is None


def test_incomplete_comparison_returns_typed_hold() -> None:
    result = compile_investigation_strategy_candidate(
        (_held_comparison(), _comparison(improvement=False))
    )

    assert result.disposition is InvestigationStrategyCompilationDisposition.HELD
    assert InvestigationStrategyHoldReason.INCOMPLETE_COMPARISON in result.hold_reasons
    assert result.candidate is None


@pytest.mark.parametrize(
    ("comparison", "reason"),
    [
        (
            _comparison(improvement=True, safety_failure=True),
            InvestigationStrategyHoldReason.SAFETY_FAILURE,
        ),
        (
            _comparison(improvement=True, invariant_failure=True),
            InvestigationStrategyHoldReason.INVARIANT_FAILURE,
        ),
    ],
)
def test_any_safety_or_invariant_failure_holds_entire_cohort(
    comparison: DiscriminationShadowComparison,
    reason: InvestigationStrategyHoldReason,
) -> None:
    result = compile_investigation_strategy_candidate((comparison, _comparison(improvement=False)))

    assert reason in result.hold_reasons
    assert result.candidate is None


def test_candidate_and_result_authority_flags_are_false() -> None:
    result = compile_investigation_strategy_candidate(
        (_comparison(improvement=True), _comparison(improvement=False))
    )
    candidate = result.candidate
    assert candidate is not None

    assert candidate.activation_authority is False
    assert candidate.promotion_authority is False
    assert candidate.query_execution_authority is False
    assert candidate.execution_authority is False
    assert candidate.mutation_authority is False
    assert result.activation_authority is False
    assert result.promotion_authority is False
    assert result.query_execution_authority is False
    assert result.execution_authority is False
    with pytest.raises(ValueError, match="MUST NOT grant authority"):
        replace(candidate, activation_authority=True)  # type: ignore[arg-type]


def test_transport_evidence_rejects_summary_tampering() -> None:
    evidence = InvestigationStrategyComparisonEvidence.from_shadow(_comparison(improvement=True))
    mapping = evidence.to_mapping()
    mapping["challenger_outcome"] = "non_improvement"

    with pytest.raises(ValueError, match="summary does not match"):
        InvestigationStrategyComparisonEvidence.from_mapping(mapping)


def test_compilation_result_digest_changes_with_exact_comparison_refs() -> None:
    improvement = _comparison(improvement=True)
    non_improvement = _comparison(improvement=False)
    baseline = compile_investigation_strategy_candidate((improvement, non_improvement))
    changed_non_improvement = _comparison(
        improvement=False,
        invariant_failure=True,
    )
    changed = compile_investigation_strategy_candidate((improvement, changed_non_improvement))

    assert baseline.result_digest != changed.result_digest
    assert changed.candidate is None


def test_malformed_cohort_boundary_raises() -> None:
    comparison = _comparison(improvement=True)
    with pytest.raises(ValueError, match="immutable typed tuple"):
        compile_investigation_strategy_candidate([comparison])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="bounded immutable typed tuple"):
        compile_investigation_strategy_candidate((comparison,) * 101)

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.rca import (
    CandidateRejectionReason,
    DiscriminationDisposition,
    DiscriminationHoldReason,
    ExpectedObservationOutcome,
    HypothesisOutcomePrediction,
    build_discriminating_observation_candidate,
    build_hypothesis_discrimination_frame,
    select_discriminating_observation,
)

_CUTOFF = datetime(2026, 8, 30, tzinfo=UTC)
_DIGEST_A = f"sha256:{'a' * 64}"
_DIGEST_B = f"sha256:{'b' * 64}"
_DIGEST_C = f"sha256:{'c' * 64}"


def _frame(
    *,
    hypotheses: tuple[str, ...] = ("hypothesis-a", "hypothesis-b", "hypothesis-c"),
    graph_revision: str = "graph-1",
    cutoff: datetime = _CUTOFF,
):
    return build_hypothesis_discrimination_frame(
        incident_id="incident-1",
        graph_revision=graph_revision,
        evidence_cutoff=cutoff,
        active_hypothesis_ids=hypotheses,
        active_set_receipt_digest=_DIGEST_A,
        cost_model_digest=_DIGEST_B,
    )


def _candidate(
    frame,
    *,
    observation_ref: str,
    outcomes: tuple[ExpectedObservationOutcome, ...],
    cost_units: int = 10,
):
    return build_discriminating_observation_candidate(
        frame=frame,
        observation_ref=observation_ref,
        verified_query_receipt_digest=_DIGEST_C,
        cost_units=cost_units,
        predictions=tuple(
            HypothesisOutcomePrediction(hypothesis_id=hypothesis_id, outcome=outcome)
            for hypothesis_id, outcome in zip(
                frame.active_hypothesis_ids,
                outcomes,
                strict=True,
            )
        ),
    )


def test_selects_candidate_that_separates_the_most_pairs() -> None:
    frame = _frame()
    weak = _candidate(
        frame,
        observation_ref="query:weak",
        outcomes=(
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.REFUTES,
        ),
        cost_units=1,
    )
    strong = _candidate(
        frame,
        observation_ref="query:strong",
        outcomes=(
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.REFUTES,
            ExpectedObservationOutcome.NEUTRAL,
        ),
        cost_units=100,
    )

    result = select_discriminating_observation(frame, (weak, strong))

    assert result.disposition is DiscriminationDisposition.SELECTED
    assert result.selected_candidate_id == strong.candidate_id
    assert result.total_pair_count == 3
    assert result.separated_pair_count == 3


def test_lower_cost_breaks_equal_separation_tie() -> None:
    frame = _frame()
    expensive = _candidate(
        frame,
        observation_ref="query:expensive",
        outcomes=(
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.REFUTES,
        ),
        cost_units=20,
    )
    cheap = _candidate(
        frame,
        observation_ref="query:cheap",
        outcomes=(
            ExpectedObservationOutcome.REFUTES,
            ExpectedObservationOutcome.REFUTES,
            ExpectedObservationOutcome.SUPPORTS,
        ),
        cost_units=10,
    )

    result = select_discriminating_observation(frame, (expensive, cheap))

    assert result.selected_candidate_id == cheap.candidate_id
    assert result.separated_pair_count == 2


def test_candidate_identity_breaks_complete_tie_and_is_permutation_invariant() -> None:
    frame = _frame()
    first = _candidate(
        frame,
        observation_ref="query:first",
        outcomes=(
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.REFUTES,
            ExpectedObservationOutcome.REFUTES,
        ),
    )
    second = _candidate(
        frame,
        observation_ref="query:second",
        outcomes=(
            ExpectedObservationOutcome.REFUTES,
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.SUPPORTS,
        ),
    )

    forward = select_discriminating_observation(frame, (first, second))
    reverse = select_discriminating_observation(frame, (second, first))

    assert forward == reverse
    assert forward.selected_candidate_id == min(first.candidate_id, second.candidate_id)


def test_snapshot_mismatch_is_explicit_and_cannot_compete() -> None:
    frame = _frame()
    stale_frame = _frame(graph_revision="graph-0", cutoff=_CUTOFF - timedelta(minutes=1))
    stale = _candidate(
        stale_frame,
        observation_ref="query:stale",
        outcomes=(
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.REFUTES,
            ExpectedObservationOutcome.NEUTRAL,
        ),
    )

    result = select_discriminating_observation(frame, (stale,))

    assert result.disposition is DiscriminationDisposition.HELD
    assert result.hold_reason is DiscriminationHoldReason.NO_ELIGIBLE_CANDIDATES
    assert result.rejected_candidates[0].reason is CandidateRejectionReason.SNAPSHOT_MISMATCH


def test_incomplete_hypothesis_coverage_is_explicit() -> None:
    frame = _frame()
    incomplete = build_discriminating_observation_candidate(
        frame=frame,
        observation_ref="query:partial",
        verified_query_receipt_digest=_DIGEST_C,
        cost_units=1,
        predictions=(
            HypothesisOutcomePrediction(
                hypothesis_id="hypothesis-a",
                outcome=ExpectedObservationOutcome.SUPPORTS,
            ),
        ),
    )

    result = select_discriminating_observation(frame, (incomplete,))

    assert result.hold_reason is DiscriminationHoldReason.NO_ELIGIBLE_CANDIDATES
    assert result.rejected_candidates[0].reason is CandidateRejectionReason.INCOMPLETE_COVERAGE


def test_non_discriminating_candidates_hold() -> None:
    frame = _frame()
    candidate = _candidate(
        frame,
        observation_ref="query:neutral",
        outcomes=(ExpectedObservationOutcome.NEUTRAL,) * 3,
    )

    result = select_discriminating_observation(frame, (candidate,))

    assert result.disposition is DiscriminationDisposition.HELD
    assert result.hold_reason is DiscriminationHoldReason.NO_DISCRIMINATION


def test_one_active_hypothesis_holds_without_selecting_a_query() -> None:
    frame = _frame(hypotheses=("hypothesis-a",))
    candidate = _candidate(
        frame,
        observation_ref="query:single",
        outcomes=(ExpectedObservationOutcome.SUPPORTS,),
    )

    result = select_discriminating_observation(frame, (candidate,))

    assert result.hold_reason is DiscriminationHoldReason.INSUFFICIENT_HYPOTHESES
    assert result.selected_candidate_id is None


def test_no_candidates_holds() -> None:
    result = select_discriminating_observation(_frame(), ())

    assert result.hold_reason is DiscriminationHoldReason.NO_CANDIDATES


def test_frame_and_candidate_identity_are_order_independent() -> None:
    first_frame = _frame(hypotheses=("hypothesis-c", "hypothesis-a", "hypothesis-b"))
    second_frame = _frame()
    first_candidate = build_discriminating_observation_candidate(
        frame=first_frame,
        observation_ref="query:stable",
        verified_query_receipt_digest=_DIGEST_C,
        cost_units=3,
        predictions=(
            HypothesisOutcomePrediction(
                hypothesis_id="hypothesis-c",
                outcome=ExpectedObservationOutcome.NEUTRAL,
            ),
            HypothesisOutcomePrediction(
                hypothesis_id="hypothesis-a",
                outcome=ExpectedObservationOutcome.SUPPORTS,
            ),
            HypothesisOutcomePrediction(
                hypothesis_id="hypothesis-b",
                outcome=ExpectedObservationOutcome.REFUTES,
            ),
        ),
    )
    second_candidate = _candidate(
        second_frame,
        observation_ref="query:stable",
        outcomes=(
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.REFUTES,
            ExpectedObservationOutcome.NEUTRAL,
        ),
        cost_units=3,
    )

    assert first_frame == second_frame
    assert first_candidate == second_candidate


def test_content_change_changes_candidate_and_selection_identity() -> None:
    frame = _frame()
    first = _candidate(
        frame,
        observation_ref="query:one",
        outcomes=(
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.REFUTES,
            ExpectedObservationOutcome.NEUTRAL,
        ),
    )
    changed = _candidate(
        frame,
        observation_ref="query:one",
        outcomes=(
            ExpectedObservationOutcome.REFUTES,
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.NEUTRAL,
        ),
    )

    first_result = select_discriminating_observation(frame, (first,))
    changed_result = select_discriminating_observation(frame, (changed,))

    assert first.candidate_digest != changed.candidate_digest
    assert first_result.selection_digest != changed_result.selection_digest


def test_digest_substitution_is_rejected() -> None:
    frame = _frame()
    candidate = _candidate(
        frame,
        observation_ref="query:one",
        outcomes=(
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.REFUTES,
            ExpectedObservationOutcome.NEUTRAL,
        ),
    )

    with pytest.raises(ValueError, match="digest does not match"):
        replace(candidate, candidate_digest=_DIGEST_A)


@pytest.mark.parametrize("cost", [-1, True, 1.5, 1_000_000_001])
def test_cost_units_are_bounded_integers(cost: object) -> None:
    frame = _frame()

    with pytest.raises(ValueError, match="cost_units"):
        _candidate(
            frame,
            observation_ref="query:cost",
            outcomes=(
                ExpectedObservationOutcome.SUPPORTS,
                ExpectedObservationOutcome.REFUTES,
                ExpectedObservationOutcome.NEUTRAL,
            ),
            cost_units=cost,  # type: ignore[arg-type]
        )


def test_inputs_are_bounded_and_canonical() -> None:
    with pytest.raises(ValueError, match="sorted, unique, and bounded"):
        _frame(hypotheses=("hypothesis-a",) * 2)
    with pytest.raises(ValueError, match="hard limit"):
        select_discriminating_observation(
            _frame(),
            tuple(
                _candidate(
                    _frame(),
                    observation_ref=f"query:{index}",
                    outcomes=(
                        ExpectedObservationOutcome.SUPPORTS,
                        ExpectedObservationOutcome.REFUTES,
                        ExpectedObservationOutcome.NEUTRAL,
                    ),
                )
                for index in range(33)
            ),
        )


def test_authority_flags_are_always_false() -> None:
    frame = _frame()
    candidate = _candidate(
        frame,
        observation_ref="query:authority",
        outcomes=(
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.REFUTES,
            ExpectedObservationOutcome.NEUTRAL,
        ),
    )
    selection = select_discriminating_observation(frame, (candidate,))

    assert frame.execution_authority is False
    assert candidate.query_execution_authority is False
    assert selection.execution_authority is False
    with pytest.raises(ValueError, match="MUST NOT grant authority"):
        replace(selection, query_execution_authority=True)
    with pytest.raises(ValueError, match="MUST NOT grant authority"):
        replace(selection, execution_authority=0)  # type: ignore[arg-type]


def test_candidate_rejects_mutable_prediction_container() -> None:
    frame = _frame()
    candidate = _candidate(
        frame,
        observation_ref="query:immutable",
        outcomes=(
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.REFUTES,
            ExpectedObservationOutcome.NEUTRAL,
        ),
    )

    with pytest.raises(ValueError, match="immutable typed tuple"):
        replace(candidate, predictions=list(candidate.predictions))  # type: ignore[arg-type]


def test_selection_rejects_mutable_rejection_container() -> None:
    selection = select_discriminating_observation(_frame(), ())

    with pytest.raises(ValueError, match="immutable typed tuple"):
        replace(selection, rejected_candidates=[])  # type: ignore[arg-type]


def test_selector_rejects_mutable_candidate_container() -> None:
    with pytest.raises(ValueError, match="immutable typed tuple"):
        select_discriminating_observation(_frame(), [])  # type: ignore[arg-type]


def test_selection_rejects_candidate_not_bound_to_receipt_set() -> None:
    frame = _frame()
    candidate = _candidate(
        frame,
        observation_ref="query:bound",
        outcomes=(
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.REFUTES,
            ExpectedObservationOutcome.NEUTRAL,
        ),
    )
    selection = select_discriminating_observation(frame, (candidate,))

    with pytest.raises(ValueError, match="candidate receipt set"):
        replace(selection, selected_candidate_id="observation-candidate-unbound")


def test_selection_rejects_non_integer_pair_counts() -> None:
    selection = select_discriminating_observation(_frame(), ())

    with pytest.raises(ValueError, match="non-negative integer"):
        replace(selection, total_pair_count=False)  # type: ignore[arg-type]

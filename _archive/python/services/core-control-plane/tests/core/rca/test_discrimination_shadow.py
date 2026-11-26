from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from itertools import combinations

import pytest
from fdai.core.rca.discrimination import (
    DISCRIMINATION_METHOD_VERSION,
    DISCRIMINATION_SCHEMA_VERSION,
    DiscriminatingObservationCandidate,
    DiscriminationDisposition,
    DiscriminationHoldReason,
    ExpectedObservationOutcome,
    HypothesisDiscriminationFrame,
    HypothesisDiscriminationSelection,
    HypothesisOutcomePrediction,
    build_discriminating_observation_candidate,
    build_hypothesis_discrimination_frame,
    select_discriminating_observation,
)
from fdai.core.rca.discrimination_shadow import (
    ChallengerComparisonOutcome,
    DiscriminationSelector,
    ShadowComparisonDisposition,
    ShadowComparisonHoldReason,
    _expected_outcome,
    discrimination_shadow_material,
    run_discrimination_shadow,
)

_ACTIVE = f"sha256:{'1' * 64}"
_CHALLENGER = f"sha256:{'2' * 64}"
_RECEIPT = f"sha256:{'3' * 64}"
_SET = f"sha256:{'4' * 64}"
_COST = f"sha256:{'5' * 64}"


def _frame(revision: str = "graph-1") -> HypothesisDiscriminationFrame:
    return build_hypothesis_discrimination_frame(
        incident_id="incident-1",
        graph_revision=revision,
        evidence_cutoff=datetime(2026, 8, 30, tzinfo=UTC),
        active_hypothesis_ids=("hypothesis-a", "hypothesis-b", "hypothesis-c"),
        active_set_receipt_digest=_SET,
        cost_model_digest=_COST,
    )


def _candidate(
    frame: HypothesisDiscriminationFrame,
    name: str,
    outcomes: tuple[ExpectedObservationOutcome, ...],
    cost: int,
) -> DiscriminatingObservationCandidate:
    return build_discriminating_observation_candidate(
        frame=frame,
        observation_ref=f"query:{name}",
        verified_query_receipt_digest=_RECEIPT,
        cost_units=cost,
        predictions=tuple(
            HypothesisOutcomePrediction(hypothesis_id=hypothesis_id, outcome=outcome)
            for hypothesis_id, outcome in zip(frame.active_hypothesis_ids, outcomes, strict=True)
        ),
    )


def _candidates(
    frame: HypothesisDiscriminationFrame,
) -> tuple[DiscriminatingObservationCandidate, ...]:
    weak = _candidate(
        frame,
        "weak",
        (
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.REFUTES,
        ),
        10,
    )
    strong = _candidate(
        frame,
        "strong",
        (
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.REFUTES,
            ExpectedObservationOutcome.NEUTRAL,
        ),
        20,
    )
    return weak, strong


def _forced_selection(
    frame: HypothesisDiscriminationFrame,
    candidates: tuple[DiscriminatingObservationCandidate, ...],
    selected: DiscriminatingObservationCandidate,
    separated_override: int | None = None,
) -> HypothesisDiscriminationSelection:
    separated = sum(
        first.outcome is not second.outcome
        for first, second in combinations(selected.predictions, 2)
    )
    if separated_override is not None:
        separated = separated_override
    candidate_digests = tuple(sorted(item.candidate_digest for item in candidates))
    material = {
        "schema_version": DISCRIMINATION_SCHEMA_VERSION,
        "frame_digest": frame.frame_digest,
        "method_version": DISCRIMINATION_METHOD_VERSION,
        "disposition": DiscriminationDisposition.SELECTED.value,
        "candidate_digests": list(candidate_digests),
        "rejected_candidates": [],
        "total_pair_count": 3,
        "separated_pair_count": separated,
        "selected_candidate_id": selected.candidate_id,
        "hold_reason": None,
    }
    encoded = json.dumps(
        material, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()
    digest = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
    return HypothesisDiscriminationSelection(
        selection_id=f"hypothesis-discrimination-{digest[7:39]}",
        selection_digest=digest,
        frame_digest=frame.frame_digest,
        method_version=DISCRIMINATION_METHOD_VERSION,
        disposition=DiscriminationDisposition.SELECTED,
        candidate_digests=candidate_digests,
        rejected_candidates=(),
        total_pair_count=3,
        separated_pair_count=separated,
        selected_candidate_id=selected.candidate_id,
    )


def _selector_for(
    selected: DiscriminatingObservationCandidate,
) -> DiscriminationSelector:
    def selector(
        frame: HypothesisDiscriminationFrame,
        candidates: tuple[DiscriminatingObservationCandidate, ...],
    ) -> HypothesisDiscriminationSelection:
        return _forced_selection(frame, candidates, selected)

    return selector


def test_both_selectors_receive_the_exact_same_immutable_inputs() -> None:
    frame = _frame()
    candidates = _candidates(frame)
    calls: list[tuple[int, int]] = []

    def selector(
        received_frame: HypothesisDiscriminationFrame,
        received_candidates: tuple[DiscriminatingObservationCandidate, ...],
    ) -> HypothesisDiscriminationSelection:
        calls.append((id(received_frame), id(received_candidates)))
        return select_discriminating_observation(received_frame, received_candidates)

    result = run_discrimination_shadow(
        frame=frame,
        candidates=candidates,
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=selector,
        challenger_selector=selector,
    )

    assert calls == [(id(frame), id(candidates)), (id(frame), id(candidates))]
    assert result.active_recommendation == select_discriminating_observation(frame, candidates)
    assert not hasattr(result, "challenger_recommendation")
    assert result.agreement is True
    assert result.realized_evidence_eligible is True
    assert result.challenger_outcome is ChallengerComparisonOutcome.CONTROL


def test_records_predicted_separation_and_cost_for_distinct_selections() -> None:
    frame = _frame()
    weak, strong = _candidates(frame)

    result = run_discrimination_shadow(
        frame=frame,
        candidates=(weak, strong),
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=_selector_for(weak),
        challenger_selector=_selector_for(strong),
    )

    assert result.disposition is ShadowComparisonDisposition.RECORDED
    assert result.active_recommendation is not None
    assert result.active_recommendation.selected_candidate_id == weak.candidate_id
    assert result.active_selected_candidate_id == weak.candidate_id
    assert result.challenger_selected_candidate_id == strong.candidate_id
    assert result.active_pair_separation == 2
    assert result.challenger_pair_separation == 3
    assert result.active_cost_units == 10
    assert result.challenger_cost_units == 20
    assert result.agreement is False
    assert result.realized_evidence_eligible is False
    assert result.challenger_outcome is ChallengerComparisonOutcome.IMPROVEMENT


def test_selector_failure_becomes_a_typed_hold_without_losing_active_result() -> None:
    frame = _frame()
    candidates = _candidates(frame)

    def fail(
        _frame: HypothesisDiscriminationFrame,
        _candidates: tuple[DiscriminatingObservationCandidate, ...],
    ) -> HypothesisDiscriminationSelection:
        raise RuntimeError("unavailable")

    result = run_discrimination_shadow(
        frame=frame,
        candidates=candidates,
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=select_discriminating_observation,
        challenger_selector=fail,
    )

    assert result.disposition is ShadowComparisonDisposition.HELD
    assert result.hold_reasons == (ShadowComparisonHoldReason.CHALLENGER_SELECTOR_FAILED,)
    assert result.active_recommendation is not None
    assert result.challenger_selection_id is None
    assert result.challenger_outcome is None


def test_substituted_selector_receipt_becomes_a_typed_conflict() -> None:
    frame = _frame()
    candidates = _candidates(frame)
    other_frame = _frame("graph-2")
    other_candidates = _candidates(other_frame)

    result = run_discrimination_shadow(
        frame=frame,
        candidates=candidates,
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=select_discriminating_observation,
        challenger_selector=lambda _frame, _candidates: select_discriminating_observation(
            other_frame, other_candidates
        ),
    )

    assert result.disposition is ShadowComparisonDisposition.HELD
    assert result.hold_reasons == (ShadowComparisonHoldReason.CHALLENGER_SELECTION_CONFLICT,)


def test_inflated_pair_separation_becomes_a_typed_conflict() -> None:
    frame = _frame()
    weak, strong = _candidates(frame)

    result = run_discrimination_shadow(
        frame=frame,
        candidates=(weak, strong),
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=_selector_for(strong),
        challenger_selector=lambda candidate_frame, candidates: _forced_selection(
            candidate_frame,
            candidates,
            weak,
            separated_override=3,
        ),
    )

    assert result.disposition is ShadowComparisonDisposition.HELD
    assert result.hold_reasons == (ShadowComparisonHoldReason.CHALLENGER_SELECTION_CONFLICT,)
    assert result.challenger_outcome is None


def test_comparison_is_content_addressed_order_independent_and_immutable() -> None:
    frame = _frame()
    weak, strong = _candidates(frame)

    forward = run_discrimination_shadow(
        frame=frame,
        candidates=(weak, strong),
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=_selector_for(weak),
        challenger_selector=_selector_for(strong),
    )
    reverse = run_discrimination_shadow(
        frame=frame,
        candidates=(strong, weak),
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=_selector_for(weak),
        challenger_selector=_selector_for(strong),
    )
    failed = run_discrimination_shadow(
        frame=frame,
        candidates=(weak, strong),
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=_selector_for(weak),
        challenger_selector=_selector_for(strong),
        safety_failure=True,
    )

    assert forward.comparison_digest == reverse.comparison_digest
    assert forward.comparison_id == reverse.comparison_id
    assert failed.comparison_digest != forward.comparison_digest
    with pytest.raises(FrozenInstanceError):
        forward.agreement = True  # type: ignore[misc]
    with pytest.raises(ValueError, match="agreement MUST match"):
        replace(forward, agreement=True)
    with pytest.raises(ValueError, match="eligibility"):
        replace(forward, realized_evidence_eligible=True)


def test_realized_evidence_is_suppressed_by_failures() -> None:
    frame = _frame()
    candidates = _candidates(frame)
    result = run_discrimination_shadow(
        frame=frame,
        candidates=candidates,
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=select_discriminating_observation,
        challenger_selector=select_discriminating_observation,
        invariant_failure=True,
    )

    assert result.agreement is True
    assert result.realized_evidence_eligible is False
    assert result.invariant_failure is True


def test_all_authority_flags_are_explicitly_false() -> None:
    frame = _frame()
    result = run_discrimination_shadow(
        frame=frame,
        candidates=_candidates(frame),
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=select_discriminating_observation,
        challenger_selector=select_discriminating_observation,
    )

    assert result.execution_authority is False
    assert result.mutation_authority is False
    assert result.query_execution_authority is False
    assert result.activation_authority is False
    assert result.promotion_authority is False
    with pytest.raises(ValueError, match="MUST NOT grant authority"):
        replace(result, query_execution_authority=True)  # type: ignore[arg-type]


def test_malformed_boundary_inputs_raise() -> None:
    frame = _frame()
    candidates = _candidates(frame)
    with pytest.raises(ValueError, match="immutable typed tuple"):
        run_discrimination_shadow(
            frame=frame,
            candidates=list(candidates),  # type: ignore[arg-type]
            active_strategy_digest=_ACTIVE,
            challenger_strategy_digest=_CHALLENGER,
            active_selector=select_discriminating_observation,
            challenger_selector=select_discriminating_observation,
        )
    with pytest.raises(ValueError, match="MUST differ"):
        run_discrimination_shadow(
            frame=frame,
            candidates=candidates,
            active_strategy_digest=_ACTIVE,
            challenger_strategy_digest=_ACTIVE,
            active_selector=select_discriminating_observation,
            challenger_selector=select_discriminating_observation,
        )
    with pytest.raises(ValueError, match="failure flags"):
        run_discrimination_shadow(
            frame=frame,
            candidates=candidates,
            active_strategy_digest=_ACTIVE,
            challenger_strategy_digest=_CHALLENGER,
            active_selector=select_discriminating_observation,
            challenger_selector=select_discriminating_observation,
            safety_failure=1,  # type: ignore[arg-type]
        )


def _held_selection(
    frame: HypothesisDiscriminationFrame,
    candidates: tuple[DiscriminatingObservationCandidate, ...],
) -> HypothesisDiscriminationSelection:
    candidate_digests = tuple(sorted(item.candidate_digest for item in candidates))
    material = {
        "schema_version": DISCRIMINATION_SCHEMA_VERSION,
        "frame_digest": frame.frame_digest,
        "method_version": DISCRIMINATION_METHOD_VERSION,
        "disposition": DiscriminationDisposition.HELD.value,
        "candidate_digests": list(candidate_digests),
        "rejected_candidates": [],
        "total_pair_count": 3,
        "separated_pair_count": 0,
        "selected_candidate_id": None,
        "hold_reason": DiscriminationHoldReason.NO_DISCRIMINATION.value,
    }
    encoded = json.dumps(
        material, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()
    digest = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
    return HypothesisDiscriminationSelection(
        selection_id=f"hypothesis-discrimination-{digest[7:39]}",
        selection_digest=digest,
        frame_digest=frame.frame_digest,
        method_version=DISCRIMINATION_METHOD_VERSION,
        disposition=DiscriminationDisposition.HELD,
        candidate_digests=candidate_digests,
        rejected_candidates=(),
        total_pair_count=3,
        separated_pair_count=0,
        selected_candidate_id=None,
        hold_reason=DiscriminationHoldReason.NO_DISCRIMINATION,
    )


def test_outcomes_selector_conflicts_and_comparison_validations() -> None:
    frame = _frame()
    weak, strong = _candidates(frame)
    cheaper_strong = _candidate(
        frame,
        "cheaper-strong",
        (
            ExpectedObservationOutcome.SUPPORTS,
            ExpectedObservationOutcome.REFUTES,
            ExpectedObservationOutcome.NEUTRAL,
        ),
        5,
    )
    triple = (weak, strong, cheaper_strong)

    challenger_held = run_discrimination_shadow(
        frame=frame,
        candidates=triple,
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=_selector_for(weak),
        challenger_selector=_held_selection,
    )
    assert challenger_held.challenger_outcome is ChallengerComparisonOutcome.NON_IMPROVEMENT

    active_held = run_discrimination_shadow(
        frame=frame,
        candidates=triple,
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=_held_selection,
        challenger_selector=_selector_for(weak),
    )
    assert active_held.challenger_outcome is ChallengerComparisonOutcome.IMPROVEMENT

    cost_improved = run_discrimination_shadow(
        frame=frame,
        candidates=triple,
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=_selector_for(strong),
        challenger_selector=_selector_for(cheaper_strong),
    )
    assert cost_improved.challenger_outcome is ChallengerComparisonOutcome.IMPROVEMENT

    worse = run_discrimination_shadow(
        frame=frame,
        candidates=triple,
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=_selector_for(strong),
        challenger_selector=_selector_for(weak),
    )
    assert worse.challenger_outcome is ChallengerComparisonOutcome.NON_IMPROVEMENT
    assert discrimination_shadow_material(worse)["challenger_outcome"] == "non_improvement"

    # Active selector returning non-Selection object -> ACTIVE_SELECTOR_FAILED
    bad_type = run_discrimination_shadow(
        frame=frame,
        candidates=(weak, strong),
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=lambda _f, _c: "invalid",  # type: ignore[return-value]
        challenger_selector=_selector_for(weak),
    )
    assert bad_type.hold_reasons == (ShadowComparisonHoldReason.ACTIVE_SELECTOR_FAILED,)

    # Selected candidate whose predictions do not match frame.active_hypothesis_ids
    mismatched_pred = build_discriminating_observation_candidate(
        frame=frame,
        observation_ref="query:incomplete",
        verified_query_receipt_digest=_RECEIPT,
        cost_units=10,
        predictions=strong.predictions[:2],
    )
    pred_conflict = run_discrimination_shadow(
        frame=frame,
        candidates=(mismatched_pred, strong),
        active_strategy_digest=_ACTIVE,
        challenger_strategy_digest=_CHALLENGER,
        active_selector=lambda candidate_frame, cands: _forced_selection(
            candidate_frame, cands, mismatched_pred
        ),
        challenger_selector=_selector_for(strong),
    )
    assert pred_conflict.hold_reasons == (ShadowComparisonHoldReason.ACTIVE_SELECTION_CONFLICT,)

    for kwargs, match in (
        ({"frame": "bad"}, "MUST be a HypothesisDiscriminationFrame"),
        ({"candidates": (weak, weak)}, "candidates MUST be unique"),
        ({"active_strategy_digest": 123}, "strategy digests MUST be strings"),
        ({"active_selector": "not-callable"}, "selectors MUST be callable"),
    ):
        call_args: dict[str, object] = {
            "frame": frame,
            "candidates": (weak, strong),
            "active_strategy_digest": _ACTIVE,
            "challenger_strategy_digest": _CHALLENGER,
            "active_selector": _selector_for(weak),
            "challenger_selector": _selector_for(strong),
        }
        call_args.update(kwargs)
        with pytest.raises(ValueError, match=match):
            run_discrimination_shadow(**call_args)  # type: ignore[arg-type]

    for changes, match in (
        ({"frame_digest": "bad"}, "frame MUST be a sha256 digest"),
        ({"candidate_digests": ("b", "a")}, "sorted, unique, bounded tuple"),
        ({"active_strategy_digest": _CHALLENGER}, "strategy digests MUST differ"),
        ({"disposition": "bad"}, "disposition is invalid"),
        ({"hold_reasons": ["bad"]}, "canonical tuple"),
        ({"disposition": ShadowComparisonDisposition.HELD}, "carry a hold reason"),
        ({"active_selection_id": ""}, "non-empty and bounded"),
        ({"active_pair_separation": -1}, "non-negative integers"),
        ({"safety_failure": "no"}, "safety_failure MUST be boolean"),
        (
            {"active_selection_id": None, "active_recommendation": None, "agreement": False},
            "requires both selection ids",
        ),
        (
            {"active_recommendation": _forced_selection(frame, triple, weak)},
            "does not match comparison evidence",
        ),
        ({"active_recommendation": None}, "MUST expose its recommendation"),
        (
            {
                "disposition": ShadowComparisonDisposition.HELD,
                "hold_reasons": (ShadowComparisonHoldReason.ACTIVE_SELECTOR_FAILED,),
                "active_recommendation": None,
                "active_selection_id": None,
                "active_selected_candidate_id": None,
                "active_cost_units": None,
                "agreement": False,
                "realized_evidence_eligible": False,
            },
            "active metrics require selection evidence",
        ),
        (
            {
                "disposition": ShadowComparisonDisposition.HELD,
                "hold_reasons": (ShadowComparisonHoldReason.CHALLENGER_SELECTOR_FAILED,),
                "challenger_selection_id": None,
                "challenger_selected_candidate_id": None,
                "challenger_cost_units": None,
                "agreement": False,
                "realized_evidence_eligible": False,
            },
            "challenger metrics require selection evidence",
        ),
        (
            {
                "active_selected_candidate_id": "observation-candidate-unknown",
                "active_recommendation": None,
                "active_selection_id": None,
                "disposition": ShadowComparisonDisposition.HELD,
                "hold_reasons": (ShadowComparisonHoldReason.ACTIVE_SELECTOR_FAILED,),
                "active_pair_separation": None,
                "agreement": False,
                "realized_evidence_eligible": False,
            },
            "belong to the compared candidate set",
        ),
        (
            {
                "active_cost_units": None,
                "challenger_selection_id": worse.active_selection_id,
                "challenger_selected_candidate_id": worse.active_selected_candidate_id,
                "agreement": True,
                "realized_evidence_eligible": True,
            },
            "active cost requires",
        ),
        (
            {
                "challenger_cost_units": None,
                "challenger_selection_id": worse.active_selection_id,
                "challenger_selected_candidate_id": worse.active_selected_candidate_id,
                "agreement": True,
                "realized_evidence_eligible": True,
            },
            "challenger cost requires",
        ),
    ):
        with pytest.raises(ValueError, match=match):
            replace(worse, **changes)  # type: ignore[arg-type]

    object.__setattr__(worse, "active_pair_separation", None)
    with pytest.raises(ValueError, match="requires predicted pair separation"):
        _expected_outcome(worse)
    object.__setattr__(worse, "active_pair_separation", 3)
    object.__setattr__(worse, "active_cost_units", None)
    with pytest.raises(ValueError, match="requires predicted costs"):
        _expected_outcome(worse)

"""Compare RCA selectors on one frame while exposing only the active recommendation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from fdai.core.rca.discrimination import (
    DiscriminatingObservationCandidate,
    HypothesisDiscriminationFrame,
    HypothesisDiscriminationSelection,
)

_DIGEST_PREFIX = "sha256:"

DiscriminationSelector = Callable[
    [HypothesisDiscriminationFrame, tuple[DiscriminatingObservationCandidate, ...]],
    HypothesisDiscriminationSelection,
]


class ShadowComparisonDisposition(StrEnum):
    """Whether both selector outputs formed comparable shadow evidence."""

    RECORDED = "recorded"
    HELD = "held"


class ShadowComparisonHoldReason(StrEnum):
    """Stable reasons a selector comparison could not be scored."""

    ACTIVE_SELECTOR_FAILED = "active_selector_failed"
    ACTIVE_SELECTION_CONFLICT = "active_selection_conflict"
    CHALLENGER_SELECTOR_FAILED = "challenger_selector_failed"
    CHALLENGER_SELECTION_CONFLICT = "challenger_selection_conflict"


class ChallengerComparisonOutcome(StrEnum):
    """Predicted challenger result relative to the active strategy."""

    IMPROVEMENT = "improvement"
    NON_IMPROVEMENT = "non_improvement"
    CONTROL = "control"


@dataclass(frozen=True, slots=True)
class DiscriminationShadowComparison:
    """Content-addressed comparison that exposes only the active recommendation."""

    frame_digest: str
    candidate_digests: tuple[str, ...]
    active_strategy_digest: str
    challenger_strategy_digest: str
    disposition: ShadowComparisonDisposition
    hold_reasons: tuple[ShadowComparisonHoldReason, ...]
    active_recommendation: HypothesisDiscriminationSelection | None
    active_selection_id: str | None
    challenger_selection_id: str | None
    active_selected_candidate_id: str | None
    challenger_selected_candidate_id: str | None
    active_pair_separation: int | None
    challenger_pair_separation: int | None
    active_cost_units: int | None
    challenger_cost_units: int | None
    agreement: bool
    realized_evidence_eligible: bool
    safety_failure: bool
    invariant_failure: bool
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False
    query_execution_authority: Literal[False] = False
    activation_authority: Literal[False] = False
    promotion_authority: Literal[False] = False
    comparison_digest: str = field(init=False)
    comparison_id: str = field(init=False)

    def __post_init__(self) -> None:
        for digest_name, digest_value in (
            ("frame", self.frame_digest),
            ("active strategy", self.active_strategy_digest),
            ("challenger strategy", self.challenger_strategy_digest),
        ):
            _digest(digest_name, digest_value)
        _digest_tuple("candidate_digests", self.candidate_digests)
        if self.active_strategy_digest == self.challenger_strategy_digest:
            raise ValueError("active and challenger strategy digests MUST differ")
        if not isinstance(self.disposition, ShadowComparisonDisposition):
            raise ValueError("shadow comparison disposition is invalid")
        canonical_reasons = tuple(sorted(set(self.hold_reasons), key=str))
        if (
            not isinstance(self.hold_reasons, tuple)
            or any(not isinstance(item, ShadowComparisonHoldReason) for item in self.hold_reasons)
            or self.hold_reasons != canonical_reasons
        ):
            raise ValueError("shadow comparison hold reasons MUST be a canonical tuple")
        if (self.disposition is ShadowComparisonDisposition.HELD) != bool(self.hold_reasons):
            raise ValueError("held shadow comparison MUST carry a hold reason")
        for reference in (
            self.active_selection_id,
            self.challenger_selection_id,
            self.active_selected_candidate_id,
            self.challenger_selected_candidate_id,
        ):
            if reference is not None:
                _bounded_text("selection reference", reference)
        for metric in (
            self.active_pair_separation,
            self.challenger_pair_separation,
            self.active_cost_units,
            self.challenger_cost_units,
        ):
            if metric is not None and (type(metric) is not int or metric < 0):
                raise ValueError("selection metrics MUST be non-negative integers or None")
        for flag_name, flag_value in (
            ("agreement", self.agreement),
            ("realized_evidence_eligible", self.realized_evidence_eligible),
            ("safety_failure", self.safety_failure),
            ("invariant_failure", self.invariant_failure),
        ):
            if not isinstance(flag_value, bool):
                raise ValueError(f"{flag_name} MUST be boolean")
        same_candidate = bool(
            self.active_selected_candidate_id
            and self.active_selected_candidate_id == self.challenger_selected_candidate_id
        )
        expected_agreement = bool(
            self.active_selection_id and self.active_selection_id == self.challenger_selection_id
        )
        if self.agreement != expected_agreement:
            raise ValueError("comparison agreement MUST match selection ids")
        expected_realized = bool(
            same_candidate
            and self.disposition is ShadowComparisonDisposition.RECORDED
            and not self.safety_failure
            and not self.invariant_failure
        )
        if self.realized_evidence_eligible != expected_realized:
            raise ValueError("realized evidence eligibility does not match the comparison")
        if self.disposition is ShadowComparisonDisposition.RECORDED:
            if not self.active_selection_id or not self.challenger_selection_id:
                raise ValueError("recorded comparison requires both selection ids")
        _authority_free(
            self.execution_authority,
            self.mutation_authority,
            self.query_execution_authority,
            self.activation_authority,
            self.promotion_authority,
        )
        digest = _content_digest(_comparison_material(self))
        object.__setattr__(self, "comparison_digest", digest)
        object.__setattr__(self, "comparison_id", f"discrimination-shadow-{digest[7:39]}")
        if self.active_recommendation is not None and (
            self.active_recommendation.selection_id != self.active_selection_id
            or self.active_recommendation.frame_digest != self.frame_digest
            or self.active_recommendation.candidate_digests != self.candidate_digests
            or self.active_recommendation.selected_candidate_id != self.active_selected_candidate_id
            or self.active_recommendation.separated_pair_count != self.active_pair_separation
        ):
            raise ValueError("active recommendation does not match comparison evidence")
        if (self.active_recommendation is None) != (self.active_selection_id is None):
            raise ValueError("active selection evidence MUST expose its recommendation")
        if self.active_selection_id is None and self.active_pair_separation is not None:
            raise ValueError("active metrics require selection evidence")
        if self.challenger_selection_id is None and self.challenger_pair_separation is not None:
            raise ValueError("challenger metrics require selection evidence")
        candidate_ids = {
            f"observation-candidate-{digest[7:39]}" for digest in self.candidate_digests
        }
        selected_ids = {self.active_selected_candidate_id, self.challenger_selected_candidate_id}
        if any(value is not None and value not in candidate_ids for value in selected_ids):
            raise ValueError("selected candidate MUST belong to the compared candidate set")
        if (self.active_selected_candidate_id is None) != (self.active_cost_units is None):
            raise ValueError("active cost requires one selected candidate")
        if (self.challenger_selected_candidate_id is None) != (self.challenger_cost_units is None):
            raise ValueError("challenger cost requires one selected candidate")

    @property
    def challenger_outcome(self) -> ChallengerComparisonOutcome | None:
        """Return the outcome derived from immutable predicted metrics."""
        if self.disposition is ShadowComparisonDisposition.HELD:
            return None
        return _expected_outcome(self)


def run_discrimination_shadow(
    *,
    frame: HypothesisDiscriminationFrame,
    candidates: tuple[DiscriminatingObservationCandidate, ...],
    active_strategy_digest: str,
    challenger_strategy_digest: str,
    active_selector: DiscriminationSelector,
    challenger_selector: DiscriminationSelector,
    safety_failure: bool = False,
    invariant_failure: bool = False,
) -> DiscriminationShadowComparison:
    """Run identical inputs; malformed boundaries raise and selector failures hold."""

    _validate_boundary(
        frame,
        candidates,
        active_strategy_digest,
        challenger_strategy_digest,
        active_selector,
        challenger_selector,
        safety_failure,
        invariant_failure,
    )
    active, active_reason = _invoke_selector(active_selector, frame, candidates, active=True)
    challenger, challenger_reason = _invoke_selector(
        challenger_selector, frame, candidates, active=False
    )
    reasons = tuple(
        sorted(
            (reason for reason in (active_reason, challenger_reason) if reason is not None),
            key=str,
        )
    )
    active_candidate = _selected_candidate(active, candidates)
    challenger_candidate = _selected_candidate(challenger, candidates)
    same_candidate = bool(
        active_candidate
        and challenger_candidate
        and active_candidate.candidate_id == challenger_candidate.candidate_id
    )
    return DiscriminationShadowComparison(
        frame_digest=frame.frame_digest,
        candidate_digests=tuple(sorted(item.candidate_digest for item in candidates)),
        active_strategy_digest=active_strategy_digest,
        challenger_strategy_digest=challenger_strategy_digest,
        disposition=(
            ShadowComparisonDisposition.HELD if reasons else ShadowComparisonDisposition.RECORDED
        ),
        hold_reasons=reasons,
        active_recommendation=active,
        active_selection_id=active.selection_id if active else None,
        challenger_selection_id=challenger.selection_id if challenger else None,
        active_selected_candidate_id=active.selected_candidate_id if active else None,
        challenger_selected_candidate_id=challenger.selected_candidate_id if challenger else None,
        active_pair_separation=active.separated_pair_count if active else None,
        challenger_pair_separation=challenger.separated_pair_count if challenger else None,
        active_cost_units=active_candidate.cost_units if active_candidate else None,
        challenger_cost_units=challenger_candidate.cost_units if challenger_candidate else None,
        agreement=bool(active and challenger and active.selection_id == challenger.selection_id),
        realized_evidence_eligible=bool(
            not reasons and same_candidate and not safety_failure and not invariant_failure
        ),
        safety_failure=safety_failure,
        invariant_failure=invariant_failure,
    )


def _validate_boundary(
    frame: object,
    candidates: object,
    active_digest: object,
    challenger_digest: object,
    active_selector: object,
    challenger_selector: object,
    safety_failure: object,
    invariant_failure: object,
) -> None:
    if not isinstance(frame, HypothesisDiscriminationFrame):
        raise ValueError("frame MUST be a HypothesisDiscriminationFrame")
    if (
        not isinstance(candidates, tuple)
        or any(not isinstance(item, DiscriminatingObservationCandidate) for item in candidates)
        or len(candidates) > 32
    ):
        raise ValueError("candidates MUST be a bounded immutable typed tuple")
    if len({item.candidate_id for item in candidates}) != len(candidates):
        raise ValueError("candidates MUST be unique")
    if not isinstance(active_digest, str) or not isinstance(challenger_digest, str):
        raise ValueError("strategy digests MUST be strings")
    _digest("active_strategy_digest", active_digest)
    _digest("challenger_strategy_digest", challenger_digest)
    if active_digest == challenger_digest:
        raise ValueError("active and challenger strategy digests MUST differ")
    if not callable(active_selector) or not callable(challenger_selector):
        raise ValueError("active and challenger selectors MUST be callable")
    if not isinstance(safety_failure, bool) or not isinstance(invariant_failure, bool):
        raise ValueError("failure flags MUST be boolean")


def _invoke_selector(
    selector: DiscriminationSelector,
    frame: HypothesisDiscriminationFrame,
    candidates: tuple[DiscriminatingObservationCandidate, ...],
    *,
    active: bool,
) -> tuple[HypothesisDiscriminationSelection | None, ShadowComparisonHoldReason | None]:
    failed, conflict = (
        (
            ShadowComparisonHoldReason.ACTIVE_SELECTOR_FAILED,
            ShadowComparisonHoldReason.ACTIVE_SELECTION_CONFLICT,
        )
        if active
        else (
            ShadowComparisonHoldReason.CHALLENGER_SELECTOR_FAILED,
            ShadowComparisonHoldReason.CHALLENGER_SELECTION_CONFLICT,
        )
    )
    try:
        selection = selector(frame, candidates)
    except Exception:  # noqa: BLE001 - shadow failure becomes bounded held evidence
        return None, failed
    expected = tuple(sorted(item.candidate_digest for item in candidates))
    if not isinstance(selection, HypothesisDiscriminationSelection):
        return None, failed
    if selection.frame_digest != frame.frame_digest or selection.candidate_digests != expected:
        return None, conflict
    expected_total = len(frame.active_hypothesis_ids) * (len(frame.active_hypothesis_ids) - 1) // 2
    selected = _selected_candidate(selection, candidates)
    if (
        selected is not None
        and tuple(item.hypothesis_id for item in selected.predictions)
        != frame.active_hypothesis_ids
    ):
        return None, conflict
    expected_separation = _candidate_pair_separation(selected) if selected is not None else 0
    if (
        selection.total_pair_count != expected_total
        or selection.separated_pair_count != expected_separation
    ):
        return None, conflict
    return selection, None


def _selected_candidate(
    selection: HypothesisDiscriminationSelection | None,
    candidates: tuple[DiscriminatingObservationCandidate, ...],
) -> DiscriminatingObservationCandidate | None:
    if selection is None or selection.selected_candidate_id is None:
        return None
    return next(
        (item for item in candidates if item.candidate_id == selection.selected_candidate_id), None
    )


def _candidate_pair_separation(
    candidate: DiscriminatingObservationCandidate,
) -> int:
    outcomes = tuple(item.outcome for item in candidate.predictions)
    return sum(
        outcomes[left] is not outcomes[right]
        for left in range(len(outcomes))
        for right in range(left + 1, len(outcomes))
    )


def _expected_outcome(value: DiscriminationShadowComparison) -> ChallengerComparisonOutcome:
    if value.agreement:
        return ChallengerComparisonOutcome.CONTROL
    if value.challenger_selected_candidate_id is None:
        return ChallengerComparisonOutcome.NON_IMPROVEMENT
    if value.active_selected_candidate_id is None:
        return ChallengerComparisonOutcome.IMPROVEMENT
    active_pairs = value.active_pair_separation
    challenger_pairs = value.challenger_pair_separation
    if active_pairs is None or challenger_pairs is None:
        raise ValueError("recorded comparison requires predicted pair separation")
    if challenger_pairs > active_pairs:
        return ChallengerComparisonOutcome.IMPROVEMENT
    if value.active_cost_units is None or value.challenger_cost_units is None:
        raise ValueError("selected comparison requires predicted costs")
    if challenger_pairs == active_pairs and value.challenger_cost_units < value.active_cost_units:
        return ChallengerComparisonOutcome.IMPROVEMENT
    return ChallengerComparisonOutcome.NON_IMPROVEMENT


def _comparison_material(value: DiscriminationShadowComparison) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "comparator_version": "discrimination-shadow-v1",
        "frame_digest": value.frame_digest,
        "candidate_digests": list(value.candidate_digests),
        "active_strategy_digest": value.active_strategy_digest,
        "challenger_strategy_digest": value.challenger_strategy_digest,
        "disposition": value.disposition.value,
        "hold_reasons": [item.value for item in value.hold_reasons],
        "active_selection_id": value.active_selection_id,
        "challenger_selection_id": value.challenger_selection_id,
        "active_selected_candidate_id": value.active_selected_candidate_id,
        "challenger_selected_candidate_id": value.challenger_selected_candidate_id,
        "active_pair_separation": value.active_pair_separation,
        "challenger_pair_separation": value.challenger_pair_separation,
        "active_cost_units": value.active_cost_units,
        "challenger_cost_units": value.challenger_cost_units,
        "agreement": value.agreement,
        "realized_evidence_eligible": value.realized_evidence_eligible,
        "challenger_outcome": value.challenger_outcome.value if value.challenger_outcome else None,
        "safety_failure": value.safety_failure,
        "invariant_failure": value.invariant_failure,
        "execution_authority": False,
        "mutation_authority": False,
        "query_execution_authority": False,
        "activation_authority": False,
        "promotion_authority": False,
    }


def discrimination_shadow_material(
    value: DiscriminationShadowComparison,
) -> dict[str, object]:
    """Return the complete canonical material sealed by comparison_digest."""

    return _comparison_material(value)


def _content_digest(value: object) -> str:
    encoded = json.dumps(
        value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()
    return f"{_DIGEST_PREFIX}{hashlib.sha256(encoded).hexdigest()}"


def _digest(name: str, value: str) -> None:
    if (
        not value.startswith(_DIGEST_PREFIX)
        or len(value) != len(_DIGEST_PREFIX) + 64
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{name} MUST be a sha256 digest")


def _digest_tuple(name: str, values: tuple[str, ...]) -> None:
    if not isinstance(values, tuple) or len(values) > 32 or values != tuple(sorted(set(values))):
        raise ValueError(f"{name} MUST be a sorted, unique, bounded tuple")
    for value in values:
        _digest(name, value)


def _bounded_text(name: str, value: str) -> None:
    if not value or len(value) > 256:
        raise ValueError(f"{name} MUST be non-empty and bounded")


def _authority_free(*values: object) -> None:
    if any(value is not False for value in values):
        raise ValueError("discrimination shadow records MUST NOT grant authority")


__all__ = [
    "ChallengerComparisonOutcome",
    "DiscriminationSelector",
    "DiscriminationShadowComparison",
    "ShadowComparisonDisposition",
    "ShadowComparisonHoldReason",
    "discrimination_shadow_material",
    "run_discrimination_shadow",
]

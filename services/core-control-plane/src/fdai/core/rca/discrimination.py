"""Replay-stable selection of the next observation for competing causal hypotheses.

The selector ranks already verified read-only observation candidates. It performs
no provider I/O and grants no authority to run the selected query or mutate any
state. Snapshot mismatches and incomplete candidate coverage remain explicit
held evidence instead of being interpreted as support for a hypothesis.
"""

from __future__ import annotations

from datetime import datetime
from itertools import combinations

from .discrimination_contract import (
    DISCRIMINATION_METHOD_VERSION,
    DISCRIMINATION_SCHEMA_VERSION,
    MAX_OBSERVATION_CANDIDATES,
    CandidateRejection,
    CandidateRejectionReason,
    DiscriminatingObservationCandidate,
    DiscriminationDisposition,
    DiscriminationHoldReason,
    ExpectedObservationOutcome,
    HypothesisDiscriminationFrame,
    HypothesisDiscriminationSelection,
    HypothesisOutcomePrediction,
    _candidate_id,
    _digest,
    _selection_id,
    _timestamp,
)


def build_hypothesis_discrimination_frame(
    *,
    incident_id: str,
    graph_revision: str,
    evidence_cutoff: datetime,
    active_hypothesis_ids: tuple[str, ...],
    active_set_receipt_digest: str,
    cost_model_digest: str,
) -> HypothesisDiscriminationFrame:
    """Build one canonical immutable frame for discriminator selection."""

    canonical_ids = tuple(sorted(active_hypothesis_ids))
    provisional = {
        "schema_version": DISCRIMINATION_SCHEMA_VERSION,
        "incident_id": incident_id,
        "graph_revision": graph_revision,
        "evidence_cutoff": _timestamp(evidence_cutoff),
        "active_hypothesis_ids": list(canonical_ids),
        "active_set_receipt_digest": active_set_receipt_digest,
        "cost_model_digest": cost_model_digest,
    }
    return HypothesisDiscriminationFrame(
        incident_id=incident_id,
        graph_revision=graph_revision,
        evidence_cutoff=evidence_cutoff,
        active_hypothesis_ids=canonical_ids,
        active_set_receipt_digest=active_set_receipt_digest,
        cost_model_digest=cost_model_digest,
        frame_digest=_digest(provisional),
    )


def build_discriminating_observation_candidate(
    *,
    frame: HypothesisDiscriminationFrame,
    observation_ref: str,
    verified_query_receipt_digest: str,
    cost_units: int,
    predictions: tuple[HypothesisOutcomePrediction, ...],
) -> DiscriminatingObservationCandidate:
    """Build a content-addressed candidate bound to one exact investigation frame."""

    canonical_predictions = tuple(sorted(predictions, key=lambda item: item.hypothesis_id))
    provisional = {
        "schema_version": DISCRIMINATION_SCHEMA_VERSION,
        "frame_digest": frame.frame_digest,
        "observation_ref": observation_ref,
        "verified_query_receipt_digest": verified_query_receipt_digest,
        "cost_units": cost_units,
        "predictions": [
            {"hypothesis_id": item.hypothesis_id, "outcome": item.outcome.value}
            for item in canonical_predictions
        ],
    }
    candidate_digest = _digest(provisional)
    return DiscriminatingObservationCandidate(
        candidate_id=_candidate_id(candidate_digest),
        candidate_digest=candidate_digest,
        frame_digest=frame.frame_digest,
        observation_ref=observation_ref,
        verified_query_receipt_digest=verified_query_receipt_digest,
        cost_units=cost_units,
        predictions=canonical_predictions,
    )


def select_discriminating_observation(
    frame: HypothesisDiscriminationFrame,
    candidates: tuple[DiscriminatingObservationCandidate, ...],
) -> HypothesisDiscriminationSelection:
    """Select the lowest-cost candidate that separates the most hypothesis pairs.

    Candidates are compared only when they match the exact frame and cover the
    complete active hypothesis set. The result is a replay receipt and does not
    authorize execution of the selected read query.
    """

    if not isinstance(frame, HypothesisDiscriminationFrame):
        raise ValueError("frame MUST be a HypothesisDiscriminationFrame")
    if not isinstance(candidates, tuple) or any(
        not isinstance(item, DiscriminatingObservationCandidate) for item in candidates
    ):
        raise ValueError("observation candidates MUST be an immutable typed tuple")
    if len(candidates) > MAX_OBSERVATION_CANDIDATES:
        raise ValueError("observation candidate count exceeds the hard limit")
    candidate_ids = tuple(item.candidate_id for item in candidates)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("observation candidates MUST be unique")
    ordered_candidates = tuple(sorted(candidates, key=lambda item: item.candidate_digest))
    candidate_digests = tuple(item.candidate_digest for item in ordered_candidates)
    total_pair_count = (
        len(frame.active_hypothesis_ids) * (len(frame.active_hypothesis_ids) - 1) // 2
    )

    if len(frame.active_hypothesis_ids) < 2:
        return _held_selection(
            frame=frame,
            candidate_digests=candidate_digests,
            rejected=(),
            total_pair_count=total_pair_count,
            reason=DiscriminationHoldReason.INSUFFICIENT_HYPOTHESES,
        )
    if not candidates:
        return _held_selection(
            frame=frame,
            candidate_digests=(),
            rejected=(),
            total_pair_count=total_pair_count,
            reason=DiscriminationHoldReason.NO_CANDIDATES,
        )

    eligible: list[tuple[int, DiscriminatingObservationCandidate]] = []
    rejected: list[CandidateRejection] = []
    expected_ids = frame.active_hypothesis_ids
    for candidate in ordered_candidates:
        if candidate.frame_digest != frame.frame_digest:
            rejected.append(
                CandidateRejection(
                    candidate.candidate_id,
                    CandidateRejectionReason.SNAPSHOT_MISMATCH,
                )
            )
            continue
        prediction_ids = tuple(item.hypothesis_id for item in candidate.predictions)
        if prediction_ids != expected_ids:
            rejected.append(
                CandidateRejection(
                    candidate.candidate_id,
                    CandidateRejectionReason.INCOMPLETE_COVERAGE,
                )
            )
            continue
        eligible.append((_separated_pairs(candidate.predictions), candidate))

    canonical_rejections = tuple(sorted(rejected, key=lambda item: item.candidate_id))
    if not eligible:
        return _held_selection(
            frame=frame,
            candidate_digests=candidate_digests,
            rejected=canonical_rejections,
            total_pair_count=total_pair_count,
            reason=DiscriminationHoldReason.NO_ELIGIBLE_CANDIDATES,
        )

    separated_pair_count, selected = min(
        eligible,
        key=lambda item: (-item[0], item[1].cost_units, item[1].candidate_id),
    )
    if separated_pair_count == 0:
        return _held_selection(
            frame=frame,
            candidate_digests=candidate_digests,
            rejected=canonical_rejections,
            total_pair_count=total_pair_count,
            reason=DiscriminationHoldReason.NO_DISCRIMINATION,
        )
    return _build_selection(
        frame=frame,
        disposition=DiscriminationDisposition.SELECTED,
        candidate_digests=candidate_digests,
        rejected=canonical_rejections,
        total_pair_count=total_pair_count,
        separated_pair_count=separated_pair_count,
        selected_candidate_id=selected.candidate_id,
        hold_reason=None,
    )


def _separated_pairs(predictions: tuple[HypothesisOutcomePrediction, ...]) -> int:
    return sum(
        first.outcome is not second.outcome for first, second in combinations(predictions, 2)
    )


def _held_selection(
    *,
    frame: HypothesisDiscriminationFrame,
    candidate_digests: tuple[str, ...],
    rejected: tuple[CandidateRejection, ...],
    total_pair_count: int,
    reason: DiscriminationHoldReason,
) -> HypothesisDiscriminationSelection:
    return _build_selection(
        frame=frame,
        disposition=DiscriminationDisposition.HELD,
        candidate_digests=candidate_digests,
        rejected=rejected,
        total_pair_count=total_pair_count,
        separated_pair_count=0,
        selected_candidate_id=None,
        hold_reason=reason,
    )


def _build_selection(
    *,
    frame: HypothesisDiscriminationFrame,
    disposition: DiscriminationDisposition,
    candidate_digests: tuple[str, ...],
    rejected: tuple[CandidateRejection, ...],
    total_pair_count: int,
    separated_pair_count: int,
    selected_candidate_id: str | None,
    hold_reason: DiscriminationHoldReason | None,
) -> HypothesisDiscriminationSelection:
    provisional = {
        "schema_version": DISCRIMINATION_SCHEMA_VERSION,
        "frame_digest": frame.frame_digest,
        "method_version": DISCRIMINATION_METHOD_VERSION,
        "disposition": disposition.value,
        "candidate_digests": list(candidate_digests),
        "rejected_candidates": [
            {"candidate_id": item.candidate_id, "reason": item.reason.value} for item in rejected
        ],
        "total_pair_count": total_pair_count,
        "separated_pair_count": separated_pair_count,
        "selected_candidate_id": selected_candidate_id,
        "hold_reason": hold_reason.value if hold_reason is not None else None,
    }
    selection_digest = _digest(provisional)
    return HypothesisDiscriminationSelection(
        selection_id=_selection_id(selection_digest),
        selection_digest=selection_digest,
        frame_digest=frame.frame_digest,
        method_version=DISCRIMINATION_METHOD_VERSION,
        disposition=disposition,
        candidate_digests=candidate_digests,
        rejected_candidates=rejected,
        total_pair_count=total_pair_count,
        separated_pair_count=separated_pair_count,
        selected_candidate_id=selected_candidate_id,
        hold_reason=hold_reason,
    )


__all__ = [
    "DISCRIMINATION_METHOD_VERSION",
    "DISCRIMINATION_SCHEMA_VERSION",
    "CandidateRejection",
    "CandidateRejectionReason",
    "DiscriminatingObservationCandidate",
    "DiscriminationDisposition",
    "DiscriminationHoldReason",
    "ExpectedObservationOutcome",
    "HypothesisDiscriminationFrame",
    "HypothesisDiscriminationSelection",
    "HypothesisOutcomePrediction",
    "build_discriminating_observation_candidate",
    "build_hypothesis_discrimination_frame",
    "select_discriminating_observation",
]

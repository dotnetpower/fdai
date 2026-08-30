"""Immutable contracts for adaptive causal-hypothesis observation selection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

MAX_ACTIVE_HYPOTHESES = 32
MAX_OBSERVATION_CANDIDATES = 32
MAX_TEXT_LENGTH = 256
MAX_CANDIDATE_BYTES = 32 * 1024
MAX_COST_UNITS = 1_000_000_000
DISCRIMINATION_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
DISCRIMINATION_METHOD_VERSION = "pair-separation-v1"

_DIGEST_PREFIX = "sha256:"


class ExpectedObservationOutcome(StrEnum):
    """Expected evidentiary effect of one observation under one hypothesis."""

    SUPPORTS = "supports"
    REFUTES = "refutes"
    NEUTRAL = "neutral"


class DiscriminationDisposition(StrEnum):
    """Terminal result of one bounded discriminator selection."""

    SELECTED = "selected"
    HELD = "held"


class DiscriminationHoldReason(StrEnum):
    """Stable reasons why no observation candidate was selected."""

    INSUFFICIENT_HYPOTHESES = "insufficient_hypotheses"
    NO_CANDIDATES = "no_candidates"
    NO_ELIGIBLE_CANDIDATES = "no_eligible_candidates"
    NO_DISCRIMINATION = "no_discrimination"


class CandidateRejectionReason(StrEnum):
    """Stable reasons why one otherwise valid candidate cannot join a frame."""

    SNAPSHOT_MISMATCH = "snapshot_mismatch"
    INCOMPLETE_COVERAGE = "incomplete_coverage"


@dataclass(frozen=True, slots=True)
class HypothesisDiscriminationFrame:
    """Exact incident snapshot against which observation candidates are compared."""

    incident_id: str
    graph_revision: str
    evidence_cutoff: datetime
    active_hypothesis_ids: tuple[str, ...]
    active_set_receipt_digest: str
    cost_model_digest: str
    frame_digest: str
    schema_version: Literal["1.0.0"] = DISCRIMINATION_SCHEMA_VERSION
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    def __post_init__(self) -> None:
        _bounded_text("incident_id", self.incident_id)
        _bounded_text("graph_revision", self.graph_revision)
        _timezone_aware("evidence_cutoff", self.evidence_cutoff)
        _canonical_ids(
            "active_hypothesis_ids",
            self.active_hypothesis_ids,
            maximum=MAX_ACTIVE_HYPOTHESES,
        )
        if not self.active_hypothesis_ids:
            raise ValueError("active_hypothesis_ids MUST be non-empty")
        _sha256_digest("active_set_receipt_digest", self.active_set_receipt_digest)
        _sha256_digest("cost_model_digest", self.cost_model_digest)
        _sha256_digest("frame_digest", self.frame_digest)
        _schema_version(self.schema_version)
        _authority_free(
            "hypothesis discrimination frame",
            self.execution_authority,
            self.mutation_authority,
            self.promotion_authority,
        )
        if self.frame_digest != _digest(_frame_material(self)):
            raise ValueError("hypothesis discrimination frame digest does not match content")


@dataclass(frozen=True, slots=True)
class HypothesisOutcomePrediction:
    """Expected observation result for one active hypothesis."""

    hypothesis_id: str
    outcome: ExpectedObservationOutcome

    def __post_init__(self) -> None:
        _bounded_text("hypothesis_id", self.hypothesis_id)
        if not isinstance(self.outcome, ExpectedObservationOutcome):
            raise ValueError("prediction outcome MUST be an ExpectedObservationOutcome")


@dataclass(frozen=True, slots=True)
class DiscriminatingObservationCandidate:
    """One pre-verified read-only observation candidate with no query authority."""

    candidate_id: str
    candidate_digest: str
    frame_digest: str
    observation_ref: str
    verified_query_receipt_digest: str
    cost_units: int
    predictions: tuple[HypothesisOutcomePrediction, ...]
    schema_version: Literal["1.0.0"] = DISCRIMINATION_SCHEMA_VERSION
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False
    promotion_authority: Literal[False] = False
    query_execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        _bounded_text("candidate_id", self.candidate_id)
        _bounded_text("observation_ref", self.observation_ref)
        _sha256_digest("candidate_digest", self.candidate_digest)
        _sha256_digest("frame_digest", self.frame_digest)
        _sha256_digest(
            "verified_query_receipt_digest",
            self.verified_query_receipt_digest,
        )
        _schema_version(self.schema_version)
        if type(self.cost_units) is not int or not 0 <= self.cost_units <= MAX_COST_UNITS:
            raise ValueError(f"cost_units MUST be an integer in [0, {MAX_COST_UNITS}]")
        if not isinstance(self.predictions, tuple) or any(
            not isinstance(item, HypothesisOutcomePrediction) for item in self.predictions
        ):
            raise ValueError("candidate predictions MUST be an immutable typed tuple")
        prediction_ids = tuple(item.hypothesis_id for item in self.predictions)
        _canonical_ids(
            "prediction hypothesis ids",
            prediction_ids,
            maximum=MAX_ACTIVE_HYPOTHESES,
        )
        if not self.predictions:
            raise ValueError("candidate predictions MUST be non-empty")
        _authority_free(
            "discriminating observation candidate",
            self.execution_authority,
            self.mutation_authority,
            self.promotion_authority,
            self.query_execution_authority,
        )
        material = _candidate_material(self)
        if len(_canonical_json(material)) > MAX_CANDIDATE_BYTES:
            raise ValueError("discriminating observation candidate exceeds its byte limit")
        expected_digest = _digest(material)
        if self.candidate_digest != expected_digest:
            raise ValueError("observation candidate digest does not match content")
        if self.candidate_id != _candidate_id(expected_digest):
            raise ValueError("observation candidate id does not match digest")


@dataclass(frozen=True, slots=True)
class CandidateRejection:
    """One explicit frame-relative candidate rejection."""

    candidate_id: str
    reason: CandidateRejectionReason

    def __post_init__(self) -> None:
        _bounded_text("candidate_id", self.candidate_id)
        if not isinstance(self.reason, CandidateRejectionReason):
            raise ValueError("candidate rejection reason MUST be a CandidateRejectionReason")


@dataclass(frozen=True, slots=True)
class HypothesisDiscriminationSelection:
    """Replay receipt for a selected observation or a stable held result."""

    selection_id: str
    selection_digest: str
    frame_digest: str
    method_version: str
    disposition: DiscriminationDisposition
    candidate_digests: tuple[str, ...]
    rejected_candidates: tuple[CandidateRejection, ...]
    total_pair_count: int
    separated_pair_count: int
    selected_candidate_id: str | None = None
    hold_reason: DiscriminationHoldReason | None = None
    schema_version: Literal["1.0.0"] = DISCRIMINATION_SCHEMA_VERSION
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False
    promotion_authority: Literal[False] = False
    query_execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        _bounded_text("selection_id", self.selection_id)
        _bounded_text("method_version", self.method_version)
        _sha256_digest("selection_digest", self.selection_digest)
        _sha256_digest("frame_digest", self.frame_digest)
        _schema_version(self.schema_version)
        if self.method_version != DISCRIMINATION_METHOD_VERSION:
            raise ValueError("unsupported hypothesis discrimination method version")
        if not isinstance(self.disposition, DiscriminationDisposition):
            raise ValueError("disposition MUST be a DiscriminationDisposition")
        if self.hold_reason is not None and not isinstance(
            self.hold_reason,
            DiscriminationHoldReason,
        ):
            raise ValueError("hold_reason MUST be a DiscriminationHoldReason")
        _canonical_ids(
            "candidate_digests",
            self.candidate_digests,
            maximum=MAX_OBSERVATION_CANDIDATES,
            digest=True,
        )
        if not isinstance(self.rejected_candidates, tuple) or any(
            not isinstance(item, CandidateRejection) for item in self.rejected_candidates
        ):
            raise ValueError("rejected_candidates MUST be an immutable typed tuple")
        rejection_ids = tuple(item.candidate_id for item in self.rejected_candidates)
        _canonical_ids(
            "rejected candidate ids",
            rejection_ids,
            maximum=MAX_OBSERVATION_CANDIDATES,
        )
        if type(self.total_pair_count) is not int or self.total_pair_count < 0:
            raise ValueError("total_pair_count MUST be a non-negative integer")
        if (
            type(self.separated_pair_count) is not int
            or not 0 <= self.separated_pair_count <= self.total_pair_count
        ):
            raise ValueError("separated_pair_count MUST be within total_pair_count")
        self._validate_disposition()
        candidate_ids = {_candidate_id(digest) for digest in self.candidate_digests}
        if not set(rejection_ids) <= candidate_ids:
            raise ValueError("rejected candidate ids MUST belong to the candidate receipt set")
        if (
            self.selected_candidate_id is not None
            and self.selected_candidate_id not in candidate_ids
        ):
            raise ValueError("selected candidate MUST belong to the candidate receipt set")
        if self.selected_candidate_id is not None and self.selected_candidate_id in rejection_ids:
            raise ValueError("selected candidate MUST NOT also be rejected")
        _authority_free(
            "hypothesis discrimination selection",
            self.execution_authority,
            self.mutation_authority,
            self.promotion_authority,
            self.query_execution_authority,
        )
        expected_digest = _digest(_selection_material(self))
        if self.selection_digest != expected_digest:
            raise ValueError("hypothesis discrimination selection digest does not match content")
        if self.selection_id != _selection_id(expected_digest):
            raise ValueError("hypothesis discrimination selection id does not match digest")

    def _validate_disposition(self) -> None:
        if self.disposition is DiscriminationDisposition.SELECTED:
            if self.selected_candidate_id is None or self.hold_reason is not None:
                raise ValueError(
                    "selected discrimination requires one candidate and no hold reason"
                )
            _bounded_text("selected_candidate_id", self.selected_candidate_id)
            if self.separated_pair_count < 1:
                raise ValueError("selected discrimination MUST separate at least one pair")
        elif self.selected_candidate_id is not None or self.hold_reason is None:
            raise ValueError("held discrimination requires one hold reason and no candidate")


def _frame_material(frame: HypothesisDiscriminationFrame) -> dict[str, object]:
    return {
        "schema_version": frame.schema_version,
        "incident_id": frame.incident_id,
        "graph_revision": frame.graph_revision,
        "evidence_cutoff": _timestamp(frame.evidence_cutoff),
        "active_hypothesis_ids": list(frame.active_hypothesis_ids),
        "active_set_receipt_digest": frame.active_set_receipt_digest,
        "cost_model_digest": frame.cost_model_digest,
    }


def _candidate_material(candidate: DiscriminatingObservationCandidate) -> dict[str, object]:
    return {
        "schema_version": candidate.schema_version,
        "frame_digest": candidate.frame_digest,
        "observation_ref": candidate.observation_ref,
        "verified_query_receipt_digest": candidate.verified_query_receipt_digest,
        "cost_units": candidate.cost_units,
        "predictions": [
            {"hypothesis_id": item.hypothesis_id, "outcome": item.outcome.value}
            for item in candidate.predictions
        ],
    }


def _selection_material(selection: HypothesisDiscriminationSelection) -> dict[str, object]:
    return {
        "schema_version": selection.schema_version,
        "frame_digest": selection.frame_digest,
        "method_version": selection.method_version,
        "disposition": selection.disposition.value,
        "candidate_digests": list(selection.candidate_digests),
        "rejected_candidates": [
            {"candidate_id": item.candidate_id, "reason": item.reason.value}
            for item in selection.rejected_candidates
        ],
        "total_pair_count": selection.total_pair_count,
        "separated_pair_count": selection.separated_pair_count,
        "selected_candidate_id": selection.selected_candidate_id,
        "hold_reason": selection.hold_reason.value if selection.hold_reason is not None else None,
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return f"{_DIGEST_PREFIX}{hashlib.sha256(_canonical_json(value)).hexdigest()}"


def _candidate_id(digest: str) -> str:
    return f"observation-candidate-{digest.removeprefix(_DIGEST_PREFIX)[:32]}"


def _selection_id(digest: str) -> str:
    return f"hypothesis-discrimination-{digest.removeprefix(_DIGEST_PREFIX)[:32]}"


def _timestamp(value: datetime) -> str:
    _timezone_aware("timestamp", value)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _bounded_text(name: str, value: str) -> None:
    if not value.strip() or len(value) > MAX_TEXT_LENGTH:
        raise ValueError(f"{name} MUST be non-empty and at most {MAX_TEXT_LENGTH} characters")


def _canonical_ids(
    name: str,
    values: tuple[str, ...],
    *,
    maximum: int,
    digest: bool = False,
) -> None:
    if len(values) > maximum or values != tuple(sorted(set(values))):
        raise ValueError(f"{name} MUST be sorted, unique, and bounded")
    for value in values:
        if digest:
            _sha256_digest(name, value)
        else:
            _bounded_text(name, value)


def _sha256_digest(name: str, value: str) -> None:
    if (
        not value.startswith(_DIGEST_PREFIX)
        or len(value) != len(_DIGEST_PREFIX) + 64
        or any(character not in "0123456789abcdef" for character in value[len(_DIGEST_PREFIX) :])
    ):
        raise ValueError(f"{name} MUST be a sha256 digest")


def _timezone_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")


def _schema_version(value: str) -> None:
    if value != DISCRIMINATION_SCHEMA_VERSION:
        raise ValueError("unsupported hypothesis discrimination schema version")


def _authority_free(label: str, *values: object) -> None:
    if any(value is not False for value in values):
        raise ValueError(f"{label} MUST NOT grant authority")

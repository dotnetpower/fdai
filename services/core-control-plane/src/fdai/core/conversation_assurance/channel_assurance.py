"""Capability-aware assurance for channel presentation projections."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ChannelPresentationCriterion(StrEnum):
    """Common and capability-dependent channel presentation requirements."""

    CANONICAL_CONTENT = "canonical_content"
    LIMITATIONS = "limitations"
    EVIDENCE = "evidence"
    AUTHORITY_POSTURE = "authority_posture"
    PREPARING_STATUS = "preparing_status"
    PROGRESS_UPDATES = "progress_updates"
    ACTIVITY_RECORDS = "activity_records"
    RICH_PRESENTATION = "rich_presentation"
    THREAD_CONTINUITY = "thread_continuity"
    EDIT_CONTINUITY = "edit_continuity"


COMMON_CHANNEL_CRITERIA = frozenset(
    {
        ChannelPresentationCriterion.CANONICAL_CONTENT,
        ChannelPresentationCriterion.LIMITATIONS,
        ChannelPresentationCriterion.EVIDENCE,
        ChannelPresentationCriterion.AUTHORITY_POSTURE,
    }
)
OPTIONAL_CHANNEL_CRITERIA = frozenset(ChannelPresentationCriterion) - COMMON_CHANNEL_CRITERIA


@dataclass(frozen=True, slots=True)
class ChannelAssuranceProfile:
    """Declare an injected channel's optional presentation capabilities."""

    profile_id: str
    channel_kind: str
    supported_optional_criteria: frozenset[ChannelPresentationCriterion] = frozenset()

    def __post_init__(self) -> None:
        for name, value in (("profile_id", self.profile_id), ("channel_kind", self.channel_kind)):
            if not value.strip() or len(value) > 128:
                raise ValueError(f"channel assurance {name} MUST be bounded and non-empty")
        unsupported = self.supported_optional_criteria - OPTIONAL_CHANNEL_CRITERIA
        if unsupported:
            raise ValueError("channel assurance profile cannot redeclare common criteria")

    @property
    def applicable_criteria(self) -> frozenset[ChannelPresentationCriterion]:
        return COMMON_CHANNEL_CRITERIA | self.supported_optional_criteria


@dataclass(frozen=True, slots=True)
class ChannelCriterionObservation:
    """Record one content-free presentation measurement."""

    criterion: ChannelPresentationCriterion
    passed: bool
    reason_code: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.reason_code.strip() or len(self.reason_code) > 256:
            raise ValueError("channel criterion reason_code MUST be bounded and non-empty")
        if len(self.evidence_refs) > 16:
            raise ValueError("channel criterion evidence_refs exceeds the bounded cap")
        if any(not item.strip() or len(item) > 1_024 for item in self.evidence_refs):
            raise ValueError("channel criterion evidence_refs MUST be bounded and non-empty")


@dataclass(frozen=True, slots=True)
class ChannelCriterionResult:
    criterion: ChannelPresentationCriterion
    score: int | None
    reason_code: str
    evidence_refs: tuple[str, ...]

    @property
    def applicable(self) -> bool:
        return self.score is not None


@dataclass(frozen=True, slots=True)
class ChannelPresentationAssessment:
    """Keep channel projection quality separate from canonical answer quality."""

    profile_id: str
    channel_kind: str
    results: tuple[ChannelCriterionResult, ...]

    @property
    def score(self) -> int:
        return sum(result.score or 0 for result in self.results)

    @property
    def max_score(self) -> int:
        return sum(result.applicable for result in self.results)

    @property
    def mandatory_failures(self) -> tuple[ChannelPresentationCriterion, ...]:
        return tuple(
            result.criterion
            for result in self.results
            if result.criterion in COMMON_CHANNEL_CRITERIA and result.score != 1
        )

    @property
    def presentation_passed(self) -> bool:
        return not self.mandatory_failures and all(result.score != 0 for result in self.results)


def assess_channel_presentation(
    *,
    profile: ChannelAssuranceProfile,
    observations: tuple[ChannelCriterionObservation, ...],
) -> ChannelPresentationAssessment:
    """Apply one injected capability profile without changing canonical answer gates."""

    by_criterion: dict[ChannelPresentationCriterion, ChannelCriterionObservation] = {}
    for observation in observations:
        if observation.criterion in by_criterion:
            raise ValueError("channel criterion observations MUST be unique")
        if observation.criterion not in profile.applicable_criteria:
            raise ValueError("cannot measure a channel criterion that the profile does not support")
        by_criterion[observation.criterion] = observation
    results: list[ChannelCriterionResult] = []
    for criterion in ChannelPresentationCriterion:
        if criterion not in profile.applicable_criteria:
            results.append(
                ChannelCriterionResult(
                    criterion=criterion,
                    score=None,
                    reason_code="channel_capability_not_supported",
                    evidence_refs=(),
                )
            )
            continue
        measured = by_criterion.get(criterion)
        results.append(
            ChannelCriterionResult(
                criterion=criterion,
                score=1 if measured is not None and measured.passed else 0,
                reason_code=(
                    measured.reason_code if measured is not None else "channel_measurement_missing"
                ),
                evidence_refs=measured.evidence_refs if measured is not None else (),
            )
        )
    return ChannelPresentationAssessment(
        profile_id=profile.profile_id,
        channel_kind=profile.channel_kind,
        results=tuple(results),
    )


__all__ = [
    "COMMON_CHANNEL_CRITERIA",
    "OPTIONAL_CHANNEL_CRITERIA",
    "ChannelAssuranceProfile",
    "ChannelCriterionObservation",
    "ChannelCriterionResult",
    "ChannelPresentationAssessment",
    "ChannelPresentationCriterion",
    "assess_channel_presentation",
]

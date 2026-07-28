"""Deterministic evaluation of multi-evidence best-practice controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from fdai.shared.contracts.models import (
    BestPractice,
    RequirementMode,
    RequirementOutcome,
    RequirementStatus,
)


class ChecklistControlStatus(StrEnum):
    SATISFIED = "satisfied"
    FAILED = "failed"
    STALE = "stale"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class ChecklistControlResult:
    control: BestPractice
    status: ChecklistControlStatus
    requirement_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]


def evaluate_best_practices(
    controls: tuple[BestPractice, ...],
    outcomes: tuple[RequirementOutcome, ...],
    *,
    evaluated_at: datetime,
) -> tuple[ChecklistControlResult, ...]:
    """Evaluate controls without treating missing evidence as a pass."""

    if evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at MUST be timezone-aware")
    by_key: dict[tuple[object, str], RequirementOutcome] = {}
    for provided_outcome in outcomes:
        key = (provided_outcome.kind, provided_outcome.ref)
        if key in by_key:
            raise ValueError(
                "duplicate requirement outcome for "
                f"{provided_outcome.kind.value}:{provided_outcome.ref}"
            )
        by_key[key] = provided_outcome

    results: list[ChecklistControlResult] = []
    for control in controls:
        statuses: list[ChecklistControlStatus] = []
        unmet: list[str] = []
        evidence: list[str] = []
        for requirement in control.requirements:
            observed_outcome = by_key.get((requirement.kind, requirement.ref))
            status = _requirement_status(
                requirement.freshness_days,
                observed_outcome,
                evaluated_at,
            )
            statuses.append(status)
            if status not in {
                ChecklistControlStatus.SATISFIED,
                ChecklistControlStatus.NOT_APPLICABLE,
            }:
                unmet.append(requirement.ref)
            if observed_outcome is not None:
                evidence.extend(observed_outcome.evidence_refs)
        results.append(
            ChecklistControlResult(
                control=control,
                status=_control_status(control.requirement_mode, statuses),
                requirement_refs=tuple(unmet),
                evidence_refs=tuple(dict.fromkeys(evidence)),
            )
        )
    return tuple(results)


def _requirement_status(
    freshness_days: int | None,
    outcome: RequirementOutcome | None,
    evaluated_at: datetime,
) -> ChecklistControlStatus:
    if outcome is None or outcome.status is RequirementStatus.UNKNOWN:
        return ChecklistControlStatus.UNKNOWN
    if outcome.status is RequirementStatus.FAILED:
        return ChecklistControlStatus.FAILED
    if outcome.status is RequirementStatus.NOT_APPLICABLE:
        return ChecklistControlStatus.NOT_APPLICABLE
    if freshness_days is not None:
        if outcome.observed_at is None:
            return ChecklistControlStatus.UNKNOWN
        if outcome.observed_at + timedelta(days=freshness_days) <= evaluated_at:
            return ChecklistControlStatus.STALE
    return ChecklistControlStatus.SATISFIED


def _control_status(
    mode: RequirementMode,
    statuses: list[ChecklistControlStatus],
) -> ChecklistControlStatus:
    applicable = [
        status for status in statuses if status is not ChecklistControlStatus.NOT_APPLICABLE
    ]
    if not applicable:
        return ChecklistControlStatus.NOT_APPLICABLE
    if mode is RequirementMode.ANY and ChecklistControlStatus.SATISFIED in applicable:
        return ChecklistControlStatus.SATISFIED
    if mode is RequirementMode.ALL and all(
        status is ChecklistControlStatus.SATISFIED for status in applicable
    ):
        return ChecklistControlStatus.SATISFIED
    for status in (
        ChecklistControlStatus.FAILED,
        ChecklistControlStatus.STALE,
        ChecklistControlStatus.UNKNOWN,
    ):
        if status in applicable:
            return status
    return ChecklistControlStatus.FAILED


__all__ = [
    "ChecklistControlResult",
    "ChecklistControlStatus",
    "evaluate_best_practices",
]

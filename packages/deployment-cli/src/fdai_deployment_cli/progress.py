"""Monotonic run progress and full-subscription inventory closure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ProgressState(StrEnum):
    """Current progress disposition."""

    RUNNING = "running"
    WAITING = "waiting"
    FAILED = "failed"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    """Bounded counters shared by CLI and operator projections."""

    sequence: int
    state: ProgressState
    stages_completed: int
    stages_total: int
    checkpoints_completed: int
    checkpoints_total: int
    started_at: str
    last_progress_at: str
    resources_observed: int | None = None
    resources_expected: int | None = None
    pages_completed: int | None = None
    pages_expected: int | None = None

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("progress sequence MUST be positive")
        _bounded_pair(self.stages_completed, self.stages_total, "stages")
        _bounded_pair(self.checkpoints_completed, self.checkpoints_total, "checkpoints")
        _optional_pair(self.resources_observed, self.resources_expected, "resources")
        _optional_pair(self.pages_completed, self.pages_expected, "pages")
        started = _moment(self.started_at, "started_at")
        progressed = _moment(self.last_progress_at, "last_progress_at")
        if progressed < started:
            raise ValueError("last_progress_at MUST NOT precede started_at")
        if self.state is ProgressState.COMPLETE and (
            self.stages_completed != self.stages_total
            or self.checkpoints_completed != self.checkpoints_total
        ):
            raise ValueError("complete progress MUST close every stage and checkpoint")

    @property
    def fraction(self) -> float:
        """Return exact work completion, never an elapsed-time estimate."""

        stage_fraction = self.stages_completed / self.stages_total
        checkpoint_fraction = self.checkpoints_completed / self.checkpoints_total
        value = (stage_fraction + checkpoint_fraction) / 2
        return 1.0 if self.state is ProgressState.COMPLETE else min(value, 0.999)


def validate_progression(
    previous: ProgressSnapshot,
    current: ProgressSnapshot,
) -> None:
    """Reject replay, regression, changing totals, and post-terminal progress."""

    if previous.state in {ProgressState.COMPLETE, ProgressState.FAILED}:
        raise ValueError("terminal progress cannot advance")
    if current.sequence != previous.sequence + 1:
        raise ValueError("progress sequence MUST advance by one")
    if (
        current.stages_total != previous.stages_total
        or current.checkpoints_total != previous.checkpoints_total
    ):
        raise ValueError("sealed progress totals MUST NOT change")
    if (
        current.stages_completed < previous.stages_completed
        or current.checkpoints_completed < previous.checkpoints_completed
    ):
        raise ValueError("progress counters MUST NOT regress")
    if _moment(current.last_progress_at, "last_progress_at") < _moment(
        previous.last_progress_at,
        "last_progress_at",
    ):
        raise ValueError("progress time MUST NOT regress")


@dataclass(frozen=True, slots=True)
class InventoryClosure:
    """Independent postconditions required to close genesis inventory."""

    subscription_root: bool
    resource_type_filter: bool
    final_fence: bool
    provider_coverage_complete: bool
    truncated: bool
    active_generation_matches: bool
    overlay_open: bool
    child_sources_complete: bool
    observer_distinct: bool

    def blockers(self) -> tuple[str, ...]:
        """Return stable reasons that keep the initial scan incomplete."""

        reasons: list[str] = []
        if not self.subscription_root:
            reasons.append("subscription_root_missing")
        if self.resource_type_filter:
            reasons.append("genesis_resource_type_filter_present")
        if not self.final_fence:
            reasons.append("final_fence_missing")
        if not self.provider_coverage_complete:
            reasons.append("provider_coverage_incomplete")
        if self.truncated:
            reasons.append("inventory_truncated")
        if not self.active_generation_matches:
            reasons.append("active_generation_mismatch")
        if self.overlay_open:
            reasons.append("newer_change_overlay_open")
        if not self.child_sources_complete:
            reasons.append("child_source_incomplete")
        if not self.observer_distinct:
            reasons.append("observer_not_independent")
        return tuple(reasons)

    @property
    def complete(self) -> bool:
        """Return whether independent inventory closure succeeded."""

        return not self.blockers()


def _bounded_pair(completed: int, total: int, label: str) -> None:
    if total < 1 or not 0 <= completed <= total:
        raise ValueError(f"{label} progress MUST be within a positive total")


def _optional_pair(completed: int | None, total: int | None, label: str) -> None:
    if (completed is None) != (total is None):
        raise ValueError(f"{label} progress values MUST be supplied together")
    if completed is not None and total is not None and (completed < 0 or total < 0):
        raise ValueError(f"{label} progress values MUST be non-negative")


def _moment(value: str, field: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} MUST be ISO 8601") from exc
    if moment.tzinfo is None:
        raise ValueError(f"{field} MUST be timezone-aware")
    return moment

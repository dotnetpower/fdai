"""Promotion-gate measurement - is a shadow-mode ActionType ready to promote?

Every upstream :class:`~fdai.shared.contracts.models.OntologyActionType`
ships in shadow mode with a
:class:`~fdai.shared.contracts.models.PromotionGate` block declaring
four measurable criteria (``min_shadow_days``, ``min_samples``,
``min_accuracy``, ``max_policy_escapes``). This module turns a stream
of shadow-mode verdict records into a
:class:`PromotionGateProgress` report so an on-call can see at a
glance whether each ActionType is ready for promotion.

The evaluator is pure computation. It takes verdict records via an
injected :class:`ShadowVerdictSource` Protocol so a fork can plug in
any backing store (Postgres audit table, Log Analytics, in-memory
fixture) without editing ``core/``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from fdai.shared.contracts.models import OntologyActionType


@dataclass(frozen=True, slots=True)
class ShadowVerdictRecord:
    """One shadow-mode verdict the audit log persisted.

    ``was_policy_escape`` MUST be True when the T0/T2 pipeline
    would have applied an action that the risk-classification table
    forbids (i.e. a real policy violation that shadow mode caught).
    ``operator_reviewed`` marks the verdict as reviewed by a human
    (the promotion-gate accuracy metric only counts reviewed
    verdicts). ``operator_agreed`` is True when the operator would
    have taken the same action.
    """

    action_type_name: str
    observed_at: datetime
    was_policy_escape: bool
    operator_reviewed: bool
    operator_agreed: bool


@runtime_checkable
class ShadowVerdictSource(Protocol):
    """Fork-injected seam that streams shadow verdicts to the evaluator."""

    def list_recent(
        self,
        *,
        action_type_name: str | None = None,
        since: datetime | None = None,
    ) -> Iterable[ShadowVerdictRecord]:
        """Yield verdicts, optionally filtered by action type and lower time bound."""
        ...


@dataclass(frozen=True, slots=True)
class PromotionGateProgress:
    """One row of the promotion-gate dashboard."""

    action_type_name: str
    shadow_days_elapsed: float
    sample_count: int
    reviewed_count: int
    agreed_count: int
    policy_escapes: int
    accuracy: float
    ready: bool
    gaps: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "action_type_name": self.action_type_name,
            "shadow_days_elapsed": self.shadow_days_elapsed,
            "sample_count": self.sample_count,
            "reviewed_count": self.reviewed_count,
            "agreed_count": self.agreed_count,
            "policy_escapes": self.policy_escapes,
            "accuracy": self.accuracy,
            "ready": self.ready,
            "gaps": list(self.gaps),
        }


@dataclass(frozen=True, slots=True)
class PromotionGateEvaluator:
    """Turns verdict records into per-ActionType progress rows."""

    now_fn: object = field(default=None)
    """Optional callable returning the current UTC ``datetime``; defaults
    to :func:`datetime.now` when ``None``. Injected so tests get
    deterministic wall clocks."""

    def evaluate(
        self,
        action_type: OntologyActionType,
        verdicts: Sequence[ShadowVerdictRecord],
    ) -> PromotionGateProgress:
        """Compute progress against ``action_type.promotion_gate``."""
        gate = action_type.promotion_gate
        relevant = [v for v in verdicts if v.action_type_name == action_type.name]
        sample_count = len(relevant)
        reviewed = [v for v in relevant if v.operator_reviewed]
        reviewed_count = len(reviewed)
        agreed_count = sum(1 for v in reviewed if v.operator_agreed)
        policy_escapes = sum(1 for v in relevant if v.was_policy_escape)

        if reviewed_count == 0:
            accuracy = 0.0
        else:
            accuracy = agreed_count / reviewed_count

        now = self._now()
        # Measured between the first and last observation, not up to now.
        # Using now would let the clock satisfy the gate: an ActionType observed
        # on one day and never again accrues "shadow days" while nothing is
        # being observed at all, so stale evidence could promote an action to
        # autonomous execution today. The window has to be the period the
        # ActionType was actually watched.
        observed = [v.observed_at for v in relevant]
        earliest = min(observed, default=now)
        latest = max(observed, default=now)
        shadow_days_elapsed = max(0.0, (latest - earliest).total_seconds() / 86400.0)

        gaps: list[str] = []
        if shadow_days_elapsed < gate.min_shadow_days:
            gaps.append(
                f"shadow_days_elapsed={shadow_days_elapsed:.2f}"
                f"<min_shadow_days={gate.min_shadow_days}"
            )
        if sample_count < gate.min_samples:
            gaps.append(f"sample_count={sample_count}<min_samples={gate.min_samples}")
        if reviewed_count == 0:
            gaps.append("no_reviewed_verdicts")
        elif accuracy < gate.min_accuracy:
            gaps.append(f"accuracy={accuracy:.3f}<min_accuracy={gate.min_accuracy}")
        if policy_escapes > gate.max_policy_escapes:
            gaps.append(
                f"policy_escapes={policy_escapes}>max_policy_escapes={gate.max_policy_escapes}"
            )

        return PromotionGateProgress(
            action_type_name=action_type.name,
            shadow_days_elapsed=round(shadow_days_elapsed, 3),
            sample_count=sample_count,
            reviewed_count=reviewed_count,
            agreed_count=agreed_count,
            policy_escapes=policy_escapes,
            accuracy=round(accuracy, 4),
            ready=not gaps,
            gaps=tuple(gaps),
        )

    def evaluate_many(
        self,
        action_types: Iterable[OntologyActionType],
        source: ShadowVerdictSource,
        *,
        window_days: int | None = None,
    ) -> tuple[PromotionGateProgress, ...]:
        """Convenience: pull verdicts from a source and evaluate every ActionType.

        ``window_days`` optionally caps how far back to scan. ``None``
        means "no lower bound" - the source decides.
        """
        since = None
        if window_days is not None:
            since = self._now() - timedelta(days=window_days)

        results: list[PromotionGateProgress] = []
        for at in action_types:
            verdicts = list(source.list_recent(action_type_name=at.name, since=since))
            results.append(self.evaluate(at, verdicts))
        return tuple(results)

    def _now(self) -> datetime:
        if self.now_fn is None:
            return datetime.now(tz=UTC)
        result = self.now_fn()  # type: ignore[operator]
        if not isinstance(result, datetime):
            raise TypeError("now_fn MUST return a datetime")
        return result


@dataclass(slots=True)
class InMemoryShadowVerdictSource:
    """Test / dev shadow verdict source backed by a list."""

    verdicts: list[ShadowVerdictRecord] = field(default_factory=list)

    def list_recent(
        self,
        *,
        action_type_name: str | None = None,
        since: datetime | None = None,
    ) -> Iterable[ShadowVerdictRecord]:
        for v in self.verdicts:
            if action_type_name is not None and v.action_type_name != action_type_name:
                continue
            if since is not None and v.observed_at < since:
                continue
            yield v


__all__ = [
    "InMemoryShadowVerdictSource",
    "PromotionGateEvaluator",
    "PromotionGateProgress",
    "ShadowVerdictRecord",
    "ShadowVerdictSource",
]

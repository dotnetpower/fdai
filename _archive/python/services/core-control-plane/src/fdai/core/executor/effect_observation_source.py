"""Provider-neutral source seam for independent effect observation.

An observer needs exactly one thing from a provider: an authoritative
reading of whether the declared expected effect is present, plus enough
metadata to judge whether that reading may be believed.  This module owns
that seam so Core never learns what a VM, a pull request, or an issue is,
and a delivery adapter never learns the receipt rules.

Fail-closed is the whole point of :class:`SafeguardEffectObserver`.  A
source that raises, times out, or cannot decide does not produce silence -
it produces a retained ``unavailable`` or ``censored`` receipt, which is a
hold.  An absent observation and an unreadable one are therefore both
visible in the matrix instead of one of them looking like success.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai.core.executor.effect_observation import (
    IndependentEffectObservationBinding,
    IndependentEffectObservationReceipt,
    IndependentEffectOutcome,
    ObservationCompleteness,
    ObservationContainment,
    ObservationFinality,
    ObservationQuality,
)

_LOGGER = logging.getLogger("fdai.core.executor.effect_observation")

#: Default freshness bound for a provider reading. Deliberately short: a
#: reading older than this cannot be attributed to the dispatch that
#: prompted it, so it is downgraded to ``stale`` rather than trusted.
DEFAULT_MAX_SOURCE_AGE = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class ObservedEffectState:
    """One authoritative provider reading, described in quality terms.

    ``expected_state_present`` is deliberately tri-state.  ``True`` means
    the declared expected effect was seen, ``False`` means the source
    positively showed its absence, and ``None`` means the source could not
    decide - which is an unknown hold, never a failure.
    """

    source_instance_id: str
    observed_at: datetime
    source_recorded_at: datetime
    evidence_window_start: datetime
    evidence_window_end: datetime
    expected_state_present: bool | None
    complete: bool = True
    final: bool = True
    contained: bool | None = True
    synthetic: bool = False
    conflicts: tuple[str, ...] = ()
    censoring_refs: tuple[str, ...] = ()
    unavailable_reason: str | None = None
    detail: str = "provider reading"

    def __post_init__(self) -> None:
        if not self.source_instance_id.strip():
            raise ValueError("observed effect state requires a source identity")
        for name, value in (
            ("observed_at", self.observed_at),
            ("source_recorded_at", self.source_recorded_at),
            ("evidence_window_start", self.evidence_window_start),
            ("evidence_window_end", self.evidence_window_end),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"observed effect state {name} MUST be timezone-aware")


class EffectObservationSource(Protocol):
    """Read the authoritative state of one dispatched effect.

    Implementations MUST use an identity that is independent of the
    executor and MUST NOT mutate provider state.
    """

    @property
    def source_instance_id(self) -> str:
        """Stable identity of the authoritative source being read."""
        ...

    async def read(
        self,
        *,
        binding: IndependentEffectObservationBinding,
    ) -> ObservedEffectState:
        """Return one bounded reading, or raise to signal unavailability."""
        ...


def classify(
    state: ObservedEffectState,
) -> tuple[IndependentEffectOutcome, str]:
    """Map one reading to its strongest honest outcome.

    Strength order is fixed so two observers reading the same state reach
    the same outcome: unreachable beats censored beats conflicted beats
    undecided.  Only a clean, decided reading reaches ``verified`` or
    ``failed``; the receipt then re-applies every quality axis, so this
    function cannot over-claim on its own.
    """

    if state.unavailable_reason is not None:
        return IndependentEffectOutcome.UNAVAILABLE, state.unavailable_reason
    if state.censoring_refs:
        return (
            IndependentEffectOutcome.CENSORED,
            f"observer was denied {len(state.censoring_refs)} required read(s)",
        )
    if state.conflicts:
        return (
            IndependentEffectOutcome.CONFLICTING,
            f"{len(state.conflicts)} independent source(s) disagree",
        )
    if state.expected_state_present is None:
        return (
            IndependentEffectOutcome.MISSING,
            "authoritative source did not report the declared expected effect",
        )
    if state.expected_state_present:
        return IndependentEffectOutcome.VERIFIED, state.detail
    return IndependentEffectOutcome.FAILED, state.detail


def quality_from(
    state: ObservedEffectState,
    *,
    max_source_age: timedelta,
) -> ObservationQuality:
    """Describe one reading in the receipt's quality vocabulary."""

    return ObservationQuality(
        schema_version="1.0.0",
        evidence_window_start=state.evidence_window_start.astimezone(UTC),
        evidence_window_end=state.evidence_window_end.astimezone(UTC),
        source_recorded_at=state.source_recorded_at.astimezone(UTC),
        max_source_age_seconds=max_source_age.total_seconds(),
        finality=(ObservationFinality.FINAL if state.final else ObservationFinality.PROVISIONAL),
        completeness=(
            ObservationCompleteness.COMPLETE if state.complete else ObservationCompleteness.PARTIAL
        ),
        containment=_containment(state.contained),
        conflicting_source_count=len(state.conflicts),
        synthetic=state.synthetic,
    )


def _containment(contained: bool | None) -> ObservationContainment:
    if contained is None:
        return ObservationContainment.UNKNOWN
    return (
        ObservationContainment.WITHIN_DECLARED_TARGET
        if contained
        else ObservationContainment.EXCEEDS_DECLARED_TARGET
    )


class SafeguardEffectObserver:
    """Turn one provider reading into one retained observation receipt."""

    def __init__(
        self,
        *,
        source: EffectObservationSource,
        observer_instance_id: str,
        executor_instance_id: str,
        max_source_age: timedelta = DEFAULT_MAX_SOURCE_AGE,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not observer_instance_id.strip() or not executor_instance_id.strip():
            raise ValueError("independent effect observation identities MUST be non-empty")
        if observer_instance_id.casefold() == executor_instance_id.casefold():
            raise ValueError("observer identity MUST differ from the executor identity")
        if observer_instance_id.casefold() == source.source_instance_id.casefold():
            raise ValueError("observer identity MUST differ from the source identity")
        if executor_instance_id.casefold() == source.source_instance_id.casefold():
            raise ValueError("executor identity MUST differ from the source identity")
        if max_source_age <= timedelta(0):
            raise ValueError("independent effect observation freshness bound MUST be positive")
        self._source = source
        self._observer_instance_id = observer_instance_id
        self._executor_instance_id = executor_instance_id
        self._max_source_age = max_source_age
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def observe(
        self,
        *,
        binding: IndependentEffectObservationBinding,
        observation_id: str,
        sequence: int,
        prior_receipt_digest: str | None,
    ) -> IndependentEffectObservationReceipt:
        """Return one receipt, degrading to an unknown hold rather than raising."""

        started_at = self._clock().astimezone(UTC)
        try:
            state = await self._source.read(binding=binding)
        except Exception as exc:
            _LOGGER.warning(
                "independent_effect_observation_unavailable",
                extra={"source": type(exc).__name__},
            )
            state = self._unreachable(started_at, exc)
        outcome, reason = classify(state)
        try:
            return self._receipt(
                state,
                outcome=outcome,
                reason=reason,
                observation_id=observation_id,
                binding=binding,
                sequence=sequence,
                prior_receipt_digest=prior_receipt_digest,
            )
        except ValueError as exc:
            # The reading is real but cannot be expressed as a valid quality
            # record - most often because the authoritative source state
            # predates the widest representable evidence window. Dropping it
            # would hide the very staleness the matrix needs recorded, so it
            # collapses to a hold anchored at the observation instant.
            _LOGGER.warning(
                "independent_effect_observation_unrepresentable",
                extra={"source": type(exc).__name__},
            )
            return self._receipt(
                self._unrepresentable(state),
                outcome=IndependentEffectOutcome.STALE,
                reason=f"authoritative reading is outside the representable window: {exc}",
                observation_id=observation_id,
                binding=binding,
                sequence=sequence,
                prior_receipt_digest=prior_receipt_digest,
            )

    def _receipt(
        self,
        state: ObservedEffectState,
        *,
        outcome: IndependentEffectOutcome,
        reason: str,
        observation_id: str,
        binding: IndependentEffectObservationBinding,
        sequence: int,
        prior_receipt_digest: str | None,
    ) -> IndependentEffectObservationReceipt:
        observed_at = state.observed_at.astimezone(UTC)
        completed_at = max(self._clock().astimezone(UTC), observed_at)
        return IndependentEffectObservationReceipt.create(
            observation_id=observation_id,
            binding=binding,
            quality=quality_from(state, max_source_age=self._max_source_age),
            outcome=outcome,
            reason=reason,
            observer_instance_id=self._observer_instance_id,
            executor_instance_id=self._executor_instance_id,
            source_instance_id=state.source_instance_id,
            observed_at=observed_at,
            completed_at=completed_at,
            sequence=sequence,
            prior_receipt_digest=prior_receipt_digest,
        )

    def _unrepresentable(self, state: ObservedEffectState) -> ObservedEffectState:
        """Collapse an unrepresentable reading onto the observation instant.

        The observer proved nothing about any earlier interval, so the window
        shrinks to the attempt rather than being clamped: clamping would move
        the source timestamp outside its own window and fail differently.
        """

        anchor = state.observed_at.astimezone(UTC)
        return ObservedEffectState(
            source_instance_id=state.source_instance_id,
            observed_at=anchor,
            source_recorded_at=anchor,
            evidence_window_start=anchor - timedelta(seconds=1),
            evidence_window_end=anchor,
            expected_state_present=None,
            complete=False,
            final=False,
            contained=None,
            detail=state.detail,
        )

    def _unreachable(
        self,
        started_at: datetime,
        error: BaseException,
    ) -> ObservedEffectState:
        """Describe a source that could not be read at all.

        The window collapses to the attempt itself, which is truthful: the
        observer proved nothing about any earlier interval.
        """

        return ObservedEffectState(
            source_instance_id=self._source.source_instance_id,
            observed_at=started_at,
            source_recorded_at=started_at,
            evidence_window_start=started_at - timedelta(seconds=1),
            evidence_window_end=started_at,
            expected_state_present=None,
            complete=False,
            final=False,
            contained=None,
            unavailable_reason=(f"authoritative source read failed: {type(error).__name__}"),
        )


__all__ = [
    "DEFAULT_MAX_SOURCE_AGE",
    "EffectObservationSource",
    "SafeguardEffectObserver",
    "ObservedEffectState",
    "classify",
    "quality_from",
]

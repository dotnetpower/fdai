"""Independent effect observation receipts that never grant authority.

FDAI-CONST-007 requires an independent authoritative observation before an
effect may be reported as an operational success.  Dispatch, broker
acceptance, and a provider receipt all stay on the executor side of that
line: they prove a request was made, never that the world changed.

This module owns the receipt an *observer* writes.  It binds the exact
safeguard bundle, action, target, source revision, durable evidence record
and executor receipt the observation is about, plus the quality axes that
decide whether the observation may be believed at all - evidence window,
freshness, finality, completeness, conflict, syntheticness and containment.

Only :attr:`IndependentEffectOutcome.VERIFIED` closes an effect.  Every
inconclusive outcome resolves to :attr:`IndependentEffectDisposition.UNKNOWN_HOLD`,
which is a stop, not a retry.  :attr:`IndependentEffectOutcome.FAILED` is
the single outcome that may *request* a separately governed recovery, and
even then the request it produces is inert.

The receipt carries four hard-false authority flags.  An observer cannot
execute, cannot attest a sink commit, cannot release a target lock, and
cannot promote a capability - so a compromised or confused observer
degrades availability of evidence rather than safety of execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, Self

from fdai.core.executor.execution_provenance import (
    SafeguardExecutionOrigin,
    SafeguardExecutionVenue,
)
from fdai.core.executor.safeguard_dispatch_support import (
    payload_digest,
    validate_digest,
    validate_text,
    validate_utc,
)

#: Longest evidence window one receipt may claim to summarize. A wider
#: window cannot be attributed to a single dispatch with confidence, so it
#: is refused rather than weighted.
MAX_EVIDENCE_WINDOW = timedelta(hours=24)


class IndependentEffectOutcome(StrEnum):
    """What one independent observation actually established.

    ``verified`` and ``failed`` are the only conclusive outcomes.  The rest
    describe *why* the observation could not conclude, and are kept distinct
    so a matrix cell records the real reason instead of collapsing every
    inconclusive case into one bucket.
    """

    VERIFIED = "verified"
    """The authoritative source shows the declared expected effect."""

    FAILED = "failed"
    """The authoritative source shows the effect did not take hold."""

    MISSING = "missing"
    """No observation exists for the bound dispatch."""

    STALE = "stale"
    """The source state predates the dispatch or exceeds its freshness bound."""

    CONFLICTING = "conflicting"
    """Independent sources disagree about the observed state."""

    CENSORED = "censored"
    """The observer was denied the read it needed to conclude."""

    UNAVAILABLE = "unavailable"
    """The authoritative source could not be reached at all."""


#: Outcomes that leave the effect unknown. Every one of these is a hold.
UNKNOWN_OUTCOMES: frozenset[IndependentEffectOutcome] = frozenset(
    {
        IndependentEffectOutcome.MISSING,
        IndependentEffectOutcome.STALE,
        IndependentEffectOutcome.CONFLICTING,
        IndependentEffectOutcome.CENSORED,
        IndependentEffectOutcome.UNAVAILABLE,
    }
)


class IndependentEffectDisposition(StrEnum):
    """What the control plane may do next, given one observation outcome."""

    EFFECT_VERIFIED = "effect_verified"
    """The effect is closed. No further dispatch is permitted or needed."""

    RECOVERY_REQUIRED = "recovery_required"
    """A separately governed, separately approved recovery MAY be requested."""

    UNKNOWN_HOLD = "unknown_hold"
    """The effect is unknown. No new effect, no retry, no release."""


class ObservationFinality(StrEnum):
    """Whether the observed source state can still change for this dispatch."""

    FINAL = "final"
    PROVISIONAL = "provisional"


class ObservationCompleteness(StrEnum):
    """Whether the observer read every source it declared it needed."""

    COMPLETE = "complete"
    PARTIAL = "partial"


class ObservationContainment(StrEnum):
    """Whether observed change stayed inside the declared logical target."""

    WITHIN_DECLARED_TARGET = "within_declared_target"
    EXCEEDS_DECLARED_TARGET = "exceeds_declared_target"
    UNKNOWN = "unknown"


def disposition_for(outcome: IndependentEffectOutcome) -> IndependentEffectDisposition:
    """Map one outcome to the only disposition it may produce."""

    if outcome is IndependentEffectOutcome.VERIFIED:
        return IndependentEffectDisposition.EFFECT_VERIFIED
    if outcome is IndependentEffectOutcome.FAILED:
        return IndependentEffectDisposition.RECOVERY_REQUIRED
    return IndependentEffectDisposition.UNKNOWN_HOLD


@dataclass(frozen=True, slots=True)
class IndependentEffectObservationBinding:
    """The exact dispatch one observation is about.

    Every field is an identity the executor already persisted.  An observer
    that cannot reproduce all of them is observing something else, so the
    binding is validated as a unit rather than field by field at use sites.
    """

    schema_version: Literal["1.0.0"]
    action_id: str
    action_payload_digest: str
    target_digest: str
    source_revision: str
    execution_path: str
    execution_origin: str
    execution_venue: str
    safeguard_bundle_digest: str
    evidence_identity_digest: str
    evidence_record_digest: str
    evidence_record_revision: int
    executor_receipt_digest: str
    binding_digest: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported independent effect observation binding schema")
        validate_text("action_id", self.action_id)
        validate_text("execution_path", self.execution_path)
        validate_text("source_revision", self.source_revision)
        for name, value in (
            ("action_payload_digest", self.action_payload_digest),
            ("target_digest", self.target_digest),
            ("safeguard_bundle_digest", self.safeguard_bundle_digest),
            ("evidence_identity_digest", self.evidence_identity_digest),
            ("evidence_record_digest", self.evidence_record_digest),
            ("executor_receipt_digest", self.executor_receipt_digest),
            ("binding_digest", self.binding_digest),
        ):
            validate_digest(name, value)
        if type(self.evidence_record_revision) is not int or self.evidence_record_revision < 1:
            raise ValueError("independent effect observation evidence revision MUST be positive")
        try:
            SafeguardExecutionOrigin(self.execution_origin)
            SafeguardExecutionVenue(self.execution_venue)
        except ValueError as exc:
            raise ValueError(
                "independent effect observation binding provenance is invalid"
            ) from exc
        expected = payload_digest(
            asdict(self),
            "independent-effect-observation-binding",
            digest_field="binding_digest",
        )
        if self.binding_digest != expected:
            raise ValueError("independent effect observation binding digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        action_id: str,
        action_payload_digest: str,
        target_digest: str,
        source_revision: str,
        execution_path: str,
        execution_origin: SafeguardExecutionOrigin,
        execution_venue: SafeguardExecutionVenue,
        safeguard_bundle_digest: str,
        evidence_identity_digest: str,
        evidence_record_digest: str,
        evidence_record_revision: int,
        executor_receipt_digest: str,
    ) -> Self:
        """Content-address one complete dispatch binding."""

        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "action_id": action_id,
            "action_payload_digest": action_payload_digest,
            "target_digest": target_digest,
            "source_revision": source_revision,
            "execution_path": execution_path,
            "execution_origin": execution_origin.value,
            "execution_venue": execution_venue.value,
            "safeguard_bundle_digest": safeguard_bundle_digest,
            "evidence_identity_digest": evidence_identity_digest,
            "evidence_record_digest": evidence_record_digest,
            "evidence_record_revision": evidence_record_revision,
            "executor_receipt_digest": executor_receipt_digest,
        }
        values["binding_digest"] = payload_digest(
            values,
            "independent-effect-observation-binding",
            digest_field="binding_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ObservationQuality:
    """Why one observation may or may not be believed.

    These axes are separate from the outcome on purpose.  An observer that
    read a complete, final, uncontested, non-synthetic, contained source may
    report ``verified``; anything weaker is downgraded by
    :func:`quality_downgrade` rather than trusted and footnoted.
    """

    schema_version: Literal["1.0.0"]
    evidence_window_start: datetime
    evidence_window_end: datetime
    source_recorded_at: datetime
    max_source_age_seconds: float
    finality: ObservationFinality
    completeness: ObservationCompleteness
    containment: ObservationContainment
    conflicting_source_count: int
    synthetic: bool

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported independent effect observation quality schema")
        for name, value in (
            ("evidence_window_start", self.evidence_window_start),
            ("evidence_window_end", self.evidence_window_end),
            ("source_recorded_at", self.source_recorded_at),
        ):
            validate_utc(name, value)
        if self.evidence_window_end <= self.evidence_window_start:
            raise ValueError("independent effect observation window MUST be positive")
        if self.evidence_window_end - self.evidence_window_start > MAX_EVIDENCE_WINDOW:
            raise ValueError("independent effect observation window MUST stay bounded")
        if not (self.evidence_window_start <= self.source_recorded_at <= self.evidence_window_end):
            raise ValueError("independent effect observation source is outside its window")
        if type(self.max_source_age_seconds) not in {int, float} or (
            self.max_source_age_seconds <= 0
        ):
            raise ValueError("independent effect observation freshness bound MUST be positive")
        if type(self.finality) is not ObservationFinality:
            raise ValueError("independent effect observation finality is invalid")
        if type(self.completeness) is not ObservationCompleteness:
            raise ValueError("independent effect observation completeness is invalid")
        if type(self.containment) is not ObservationContainment:
            raise ValueError("independent effect observation containment is invalid")
        if type(self.conflicting_source_count) is not int or self.conflicting_source_count < 0:
            raise ValueError("independent effect observation conflict count MUST NOT be negative")
        if type(self.synthetic) is not bool:
            raise ValueError("independent effect observation syntheticness MUST be explicit")

    def stale_at(self, observed_at: datetime) -> bool:
        """Whether the source state is older than its declared freshness bound."""

        age = observed_at.astimezone(UTC) - self.source_recorded_at
        return age > timedelta(seconds=self.max_source_age_seconds)


def quality_downgrade(
    quality: ObservationQuality,
    *,
    observed_at: datetime,
) -> IndependentEffectOutcome | None:
    """Return the outcome a weak observation is forced to, if any.

    Order matters only for reporting, not for safety: every branch here
    lands in :data:`UNKNOWN_OUTCOMES`, so the effect stays unknown whichever
    weakness fired first.  Synthetic evidence is checked first because it is
    the one weakness that can otherwise look perfect.
    """

    if quality.synthetic:
        return IndependentEffectOutcome.UNAVAILABLE
    if quality.conflicting_source_count > 0:
        return IndependentEffectOutcome.CONFLICTING
    if quality.stale_at(observed_at):
        return IndependentEffectOutcome.STALE
    if quality.finality is not ObservationFinality.FINAL:
        return IndependentEffectOutcome.STALE
    if quality.completeness is not ObservationCompleteness.COMPLETE:
        return IndependentEffectOutcome.CENSORED
    if quality.containment is not ObservationContainment.WITHIN_DECLARED_TARGET:
        return IndependentEffectOutcome.CONFLICTING
    return None


@dataclass(frozen=True, slots=True)
class IndependentEffectObservationReceipt:
    """One append-only independent observation of a single dispatch."""

    schema_version: Literal["1.0.0"]
    observation_id: str
    binding: IndependentEffectObservationBinding
    quality: ObservationQuality
    outcome: IndependentEffectOutcome
    disposition: IndependentEffectDisposition
    reason: str
    observer_instance_id: str
    executor_instance_id: str
    source_instance_id: str
    observed_at: datetime
    completed_at: datetime
    sequence: int
    prior_receipt_digest: str | None
    receipt_digest: str
    effect_verified: bool = False
    execution_authority: Literal[False] = False
    sink_commit_authority: Literal[False] = False
    lock_release_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported independent effect observation receipt schema")
        if (
            self.execution_authority is not False
            or self.sink_commit_authority is not False
            or self.lock_release_authority is not False
            or self.promotion_authority is not False
        ):
            raise ValueError("independent effect observation MUST NOT grant authority")
        if type(self.binding) is not IndependentEffectObservationBinding:
            raise ValueError("independent effect observation requires an exact binding")
        if type(self.quality) is not ObservationQuality:
            raise ValueError("independent effect observation requires exact quality")
        if type(self.outcome) is not IndependentEffectOutcome:
            raise ValueError("independent effect observation outcome is invalid")
        if type(self.disposition) is not IndependentEffectDisposition:
            raise ValueError("independent effect observation disposition is invalid")
        if self.disposition is not disposition_for(self.outcome):
            raise ValueError("independent effect observation disposition contradicts its outcome")
        validate_text("observation_id", self.observation_id)
        validate_text("reason", self.reason)
        for name, value in (
            ("observer_instance_id", self.observer_instance_id),
            ("executor_instance_id", self.executor_instance_id),
            ("source_instance_id", self.source_instance_id),
        ):
            validate_text(name, value)
        self._validate_independence()
        validate_utc("observed_at", self.observed_at)
        validate_utc("completed_at", self.completed_at)
        if self.completed_at < self.observed_at:
            raise ValueError("independent effect observation completion precedes observation")
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("independent effect observation sequence MUST be positive")
        if self.sequence == 1:
            if self.prior_receipt_digest is not None:
                raise ValueError("the first independent effect observation has no predecessor")
        else:
            if self.prior_receipt_digest is None:
                raise ValueError("independent effect observation lineage lacks a predecessor")
            validate_digest("prior_receipt_digest", self.prior_receipt_digest)
        if type(self.effect_verified) is not bool:
            raise ValueError("independent effect observation verification MUST be explicit")
        if self.effect_verified != (self.outcome is IndependentEffectOutcome.VERIFIED):
            raise ValueError("independent effect verification requires a verified outcome")
        if (
            self.outcome is IndependentEffectOutcome.VERIFIED
            and quality_downgrade(self.quality, observed_at=self.observed_at) is not None
        ):
            raise ValueError("a verified observation requires complete, final, exact evidence")
        validate_digest("receipt_digest", self.receipt_digest)
        expected = payload_digest(
            asdict(self),
            "independent-effect-observation-receipt",
            digest_field="receipt_digest",
        )
        if self.receipt_digest != expected:
            raise ValueError("independent effect observation receipt digest mismatched")

    def _validate_independence(self) -> None:
        """Require three distinct identities for observer, executor and source.

        Independence is the whole value of this receipt.  Comparison is
        case-folded because an identity that differs only in case is the
        same principal wearing a different hat.
        """

        identities = {
            self.observer_instance_id.casefold(),
            self.executor_instance_id.casefold(),
            self.source_instance_id.casefold(),
        }
        if len(identities) != 3:
            raise ValueError(
                "independent effect observation observer, executor, and source "
                "identities MUST be distinct"
            )

    @classmethod
    def create(
        cls,
        *,
        observation_id: str,
        binding: IndependentEffectObservationBinding,
        quality: ObservationQuality,
        outcome: IndependentEffectOutcome,
        reason: str,
        observer_instance_id: str,
        executor_instance_id: str,
        source_instance_id: str,
        observed_at: datetime,
        completed_at: datetime,
        sequence: int,
        prior_receipt_digest: str | None,
    ) -> Self:
        """Create one receipt, downgrading any outcome its evidence cannot carry.

        A caller may only ever *weaken* the outcome here.  ``verified`` and
        ``failed`` both require evidence that passed every quality axis, so a
        weak observation claiming either is rewritten to the unknown outcome
        its own quality implies rather than rejected - the observation still
        happened and is still worth retaining.
        """

        effective = outcome
        downgrade = quality_downgrade(quality, observed_at=observed_at)
        if downgrade is not None and outcome in {
            IndependentEffectOutcome.VERIFIED,
            IndependentEffectOutcome.FAILED,
        }:
            effective = downgrade
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "observation_id": observation_id,
            "binding": binding,
            "quality": quality,
            "outcome": effective,
            "disposition": disposition_for(effective),
            "reason": reason,
            "observer_instance_id": observer_instance_id,
            "executor_instance_id": executor_instance_id,
            "source_instance_id": source_instance_id,
            "observed_at": observed_at,
            "completed_at": completed_at,
            "sequence": sequence,
            "prior_receipt_digest": prior_receipt_digest,
            "effect_verified": effective is IndependentEffectOutcome.VERIFIED,
            "execution_authority": False,
            "sink_commit_authority": False,
            "lock_release_authority": False,
            "promotion_authority": False,
        }
        values["receipt_digest"] = payload_digest(
            values,
            "independent-effect-observation-receipt",
            digest_field="receipt_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


__all__ = [
    "MAX_EVIDENCE_WINDOW",
    "UNKNOWN_OUTCOMES",
    "IndependentEffectDisposition",
    "IndependentEffectObservationBinding",
    "IndependentEffectObservationReceipt",
    "IndependentEffectOutcome",
    "ObservationCompleteness",
    "ObservationContainment",
    "ObservationFinality",
    "ObservationQuality",
    "disposition_for",
    "quality_downgrade",
]

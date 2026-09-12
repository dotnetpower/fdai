"""Append-only independent effect observation ledger and its state machine.

The ledger is the only writer of independent effect state.  It answers one
question per dispatch - *is the effect verified, failed, or unknown* - and
it answers it from retained receipts rather than from a live call, so a
replay reaches the same answer as the original run.

Three rules make the answer safe:

1. **Verified is terminal.**  Once an effect is closed, no later receipt may
   reopen it.  A contradicting receipt is retained (it is evidence) and
   raises a conflict rather than silently winning.
2. **Unknown is a stop.**  Missing, stale, conflicting, censored and
   unavailable all resolve to a hold.  A hold never authorizes a retry,
   a new effect, a lock release, or a promotion.
3. **Failed only requests.**  A failed observation may produce a
   :class:`GovernedRecoveryRequest`, which is inert: it carries no
   authority and explicitly restates that recovery needs all seven
   safeguards and its own current human approval.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal, Protocol, Self

from fdai.core.executor.effect_observation import (
    IndependentEffectDisposition,
    IndependentEffectObservationReceipt,
    IndependentEffectOutcome,
)
from fdai.core.executor.safeguard_dispatch_support import (
    payload_digest,
    validate_digest,
    validate_text,
    validate_utc,
)


class IndependentEffectLedgerError(RuntimeError):
    """The retained observation lineage cannot support the requested write."""


class IndependentEffectConflictError(IndependentEffectLedgerError):
    """A later observation contradicts an already-closed effect."""


@dataclass(frozen=True, slots=True)
class GovernedRecoveryRequest:
    """An inert request for a separately governed recovery attempt.

    This is a *request*, not a decision.  It names the failed dispatch and
    restates the conditions any recovery must independently satisfy.  It
    grants nothing: the recovery attempt is a new action that acquires its
    own lock, its own idempotency identity, its own audit intent, and its
    own current human approval.
    """

    schema_version: Literal["1.0.0"]
    evidence_identity_digest: str
    safeguard_bundle_digest: str
    action_id: str
    target_digest: str
    source_revision: str
    observation_receipt_digest: str
    requested_at: datetime
    reason: str
    request_digest: str
    requires_seven_safeguards: Literal[True] = True
    requires_current_human_approval: Literal[True] = True
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported governed recovery request schema")
        if self.requires_seven_safeguards is not True:
            raise ValueError("governed recovery MUST require every safeguard")
        if self.requires_current_human_approval is not True:
            raise ValueError("governed recovery MUST require current human approval")
        if self.execution_authority is not False or self.promotion_authority is not False:
            raise ValueError("governed recovery request MUST NOT grant authority")
        validate_text("action_id", self.action_id)
        validate_text("source_revision", self.source_revision)
        validate_text("reason", self.reason)
        for name, value in (
            ("evidence_identity_digest", self.evidence_identity_digest),
            ("safeguard_bundle_digest", self.safeguard_bundle_digest),
            ("target_digest", self.target_digest),
            ("observation_receipt_digest", self.observation_receipt_digest),
            ("request_digest", self.request_digest),
        ):
            validate_digest(name, value)
        validate_utc("requested_at", self.requested_at)
        expected = payload_digest(
            asdict(self),
            "governed-recovery-request",
            digest_field="request_digest",
        )
        if self.request_digest != expected:
            raise ValueError("governed recovery request digest mismatched")

    @classmethod
    def create(
        cls,
        receipt: IndependentEffectObservationReceipt,
        *,
        requested_at: datetime,
    ) -> Self:
        """Create the inert recovery request implied by one failed observation."""

        if receipt.outcome is not IndependentEffectOutcome.FAILED:
            raise ValueError("only an authoritative failed observation may request recovery")
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "evidence_identity_digest": receipt.binding.evidence_identity_digest,
            "safeguard_bundle_digest": receipt.binding.safeguard_bundle_digest,
            "action_id": receipt.binding.action_id,
            "target_digest": receipt.binding.target_digest,
            "source_revision": receipt.binding.source_revision,
            "observation_receipt_digest": receipt.receipt_digest,
            "requested_at": requested_at,
            "reason": receipt.reason,
            "requires_seven_safeguards": True,
            "requires_current_human_approval": True,
            "execution_authority": False,
            "promotion_authority": False,
        }
        values["request_digest"] = payload_digest(
            values,
            "governed-recovery-request",
            digest_field="request_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class IndependentEffectState:
    """The current independent effect answer for one dispatch."""

    evidence_identity_digest: str
    disposition: IndependentEffectDisposition
    outcome: IndependentEffectOutcome
    latest_receipt_digest: str
    observation_count: int
    effect_verified: bool
    recovery_request: GovernedRecoveryRequest | None = None

    def __post_init__(self) -> None:
        if self.effect_verified != (
            self.disposition is IndependentEffectDisposition.EFFECT_VERIFIED
        ):
            raise ValueError("independent effect state verification contradicts its disposition")
        if (
            self.recovery_request is not None
            and self.disposition is not IndependentEffectDisposition.RECOVERY_REQUIRED
        ):
            raise ValueError("only a failed effect may carry a recovery request")

    @property
    def permits_new_effect(self) -> bool:
        """Whether this state alone authorizes another forward dispatch.

        Always ``False``.  Verified needs no further effect, unknown is a
        hold, and recovery is a separately approved action rather than a
        continuation of this one.  The property exists so a caller that asks
        gets a written-down answer instead of inferring one.
        """

        return False


class IndependentEffectObservationStore(Protocol):
    """Append-only retention for independent effect observations."""

    async def append(
        self,
        receipt: IndependentEffectObservationReceipt,
    ) -> IndependentEffectObservationReceipt:
        """Persist one receipt, or return the identical retained receipt.

        Implementations MUST reject a different receipt that reuses an
        existing ``(evidence_identity_digest, sequence)`` position and MUST
        NOT mutate a retained receipt.
        """
        ...

    async def read_lineage(
        self,
        evidence_identity_digest: str,
    ) -> tuple[IndependentEffectObservationReceipt, ...]:
        """Return every retained receipt for one dispatch, in sequence order."""
        ...


def validate_lineage(
    receipts: Sequence[IndependentEffectObservationReceipt],
) -> None:
    """Require a contiguous, correctly chained, single-dispatch lineage."""

    for index, receipt in enumerate(receipts):
        if type(receipt) is not IndependentEffectObservationReceipt:
            raise IndependentEffectLedgerError("observation lineage requires exact receipts")
        if receipt.sequence != index + 1:
            raise IndependentEffectLedgerError("observation lineage is not contiguous")
        if index == 0:
            continue
        prior = receipts[index - 1]
        if receipt.prior_receipt_digest != prior.receipt_digest:
            raise IndependentEffectLedgerError("observation lineage chain is broken")
        if receipt.binding.evidence_identity_digest != prior.binding.evidence_identity_digest:
            raise IndependentEffectLedgerError("observation lineage spans two dispatches")


def project_state(
    receipts: Sequence[IndependentEffectObservationReceipt],
    *,
    evidence_identity_digest: str,
    recovery_requested_at: datetime | None = None,
) -> IndependentEffectState:
    """Fold one retained lineage into the current independent effect state.

    Replay-safe: the result depends only on the retained receipts and, for a
    failed effect, on the caller-supplied request time.  An empty lineage is
    :attr:`IndependentEffectOutcome.MISSING`, which is a hold - absence of
    evidence never reads as absence of effect.
    """

    validate_digest("evidence_identity_digest", evidence_identity_digest)
    if not receipts:
        raise IndependentEffectLedgerError(
            "independent effect state requires at least one retained observation"
        )
    validate_lineage(receipts)
    if receipts[0].binding.evidence_identity_digest != evidence_identity_digest:
        raise IndependentEffectLedgerError("observation lineage does not bind this dispatch")

    verified = next(
        (r for r in receipts if r.outcome is IndependentEffectOutcome.VERIFIED),
        None,
    )
    if verified is not None:
        contradiction = next(
            (
                r
                for r in receipts
                if r.sequence > verified.sequence and r.outcome is IndependentEffectOutcome.FAILED
            ),
            None,
        )
        if contradiction is not None:
            raise IndependentEffectConflictError(
                "a retained observation contradicts an already-verified effect"
            )
        return IndependentEffectState(
            evidence_identity_digest=evidence_identity_digest,
            disposition=IndependentEffectDisposition.EFFECT_VERIFIED,
            outcome=IndependentEffectOutcome.VERIFIED,
            latest_receipt_digest=receipts[-1].receipt_digest,
            observation_count=len(receipts),
            effect_verified=True,
        )

    latest = receipts[-1]
    if latest.outcome is IndependentEffectOutcome.FAILED:
        request = (
            GovernedRecoveryRequest.create(latest, requested_at=recovery_requested_at)
            if recovery_requested_at is not None
            else None
        )
        return IndependentEffectState(
            evidence_identity_digest=evidence_identity_digest,
            disposition=IndependentEffectDisposition.RECOVERY_REQUIRED,
            outcome=IndependentEffectOutcome.FAILED,
            latest_receipt_digest=latest.receipt_digest,
            observation_count=len(receipts),
            effect_verified=False,
            recovery_request=request,
        )
    return IndependentEffectState(
        evidence_identity_digest=evidence_identity_digest,
        disposition=IndependentEffectDisposition.UNKNOWN_HOLD,
        outcome=latest.outcome,
        latest_receipt_digest=latest.receipt_digest,
        observation_count=len(receipts),
        effect_verified=False,
    )


class IndependentEffectLedger:
    """Record observations and project the effect state they support."""

    def __init__(self, *, store: IndependentEffectObservationStore) -> None:
        self._store = store

    async def record(
        self,
        receipt: IndependentEffectObservationReceipt,
        *,
        recovery_requested_at: datetime | None = None,
    ) -> IndependentEffectState:
        """Append one observation and return the resulting state.

        The append happens before projection so a contradicting observation
        is retained as evidence even when projecting it raises.
        """

        if type(receipt) is not IndependentEffectObservationReceipt:
            raise IndependentEffectLedgerError("independent effect ledger requires exact receipts")
        await self._store.append(receipt)
        return await self.state(
            receipt.binding.evidence_identity_digest,
            recovery_requested_at=recovery_requested_at,
        )

    async def state(
        self,
        evidence_identity_digest: str,
        *,
        recovery_requested_at: datetime | None = None,
    ) -> IndependentEffectState:
        """Project the current state for one dispatch from retained receipts."""

        lineage = await self._store.read_lineage(evidence_identity_digest)
        return project_state(
            lineage,
            evidence_identity_digest=evidence_identity_digest,
            recovery_requested_at=recovery_requested_at,
        )


__all__ = [
    "GovernedRecoveryRequest",
    "IndependentEffectConflictError",
    "IndependentEffectLedger",
    "IndependentEffectLedgerError",
    "IndependentEffectObservationStore",
    "IndependentEffectState",
    "project_state",
    "validate_lineage",
]

"""Process-local one-shot coordinator for inert provider acceptance attempts."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol, cast

from fdai.core.standing_authority.lease import (
    LeaseOutcome,
    ProviderCommitFenceRequest,
)
from fdai.core.standing_authority.lifecycle import LifecycleFence
from fdai.core.standing_authority.lifecycle_codec import (
    AuthorizationLifecycleError,
    aware_utc,
    content_digest,
)
from fdai.core.standing_authority.provider_acceptance import (
    ProviderAcceptanceAmbiguityReason,
    ProviderAcceptanceIdentity,
    ProviderAcceptanceRecord,
    ProviderAcceptanceState,
    ProviderNonAcceptanceEvidenceKind,
    ProviderSubmissionResult,
    complete_provider_acceptance,
    prepare_provider_acceptance,
)
from fdai.core.standing_authority.provider_acceptance_store import (
    PROCESS_LOCAL_LINEARIZATION,
    ProviderAcceptanceAcquireDecision,
    ProviderAcceptanceStore,
    ProviderAcceptanceTransitionReceipt,
    ProviderSubmissionPermit,
)
from fdai.shared.providers.standing_authority import (
    StandingAuthorizationLeaseStore,
    StandingAuthorizationStoreError,
)


class ProviderAcceptancePersistenceError(RuntimeError):
    """Raised when durable preparation or exact readback cannot be confirmed."""


class ProviderAcceptanceReentrancyError(RuntimeError):
    """Raised when one callback re-enters the same target acceptance section."""


class ProviderSubmitPort(Protocol):
    """Submit exactly one provider request using the supplied correlation permit."""

    async def submit(
        self,
        *,
        identity: ProviderAcceptanceIdentity,
        permit: ProviderSubmissionPermit,
    ) -> ProviderSubmissionResult: ...


@dataclass(frozen=True, slots=True)
class ProviderAcceptanceAttempt:
    """No-authority outcome of one coordinator call."""

    decision: ProviderAcceptanceAcquireDecision
    record: ProviderAcceptanceRecord
    submitted: bool
    transition_receipt: ProviderAcceptanceTransitionReceipt | None
    attempt_digest: str
    execution_authority: Literal[False] = False
    effect_verification_authority: Literal[False] = False
    promotion_authority: Literal[False] = False
    production_eligible: Literal[False] = False

    def __post_init__(self) -> None:
        if any(
            (
                self.execution_authority,
                self.effect_verification_authority,
                self.promotion_authority,
                self.production_eligible,
            )
        ):
            raise AuthorizationLifecycleError(
                "provider acceptance attempt MUST remain no-authority and ineligible"
            )
        local_denial = bool(
            self.record.state is ProviderAcceptanceState.NOT_ACCEPTED
            and self.record.result is not None
            and self.record.result.non_acceptance_kind
            in {
                ProviderNonAcceptanceEvidenceKind.LOCAL_FENCE_DENIED,
                ProviderNonAcceptanceEvidenceKind.LOCAL_FENCE_UNAVAILABLE,
            }
        )
        if self.submitted != (
            self.decision is ProviderAcceptanceAcquireDecision.PERMITTED
            and self.record.state
            in {
                ProviderAcceptanceState.ACCEPTED,
                ProviderAcceptanceState.NOT_ACCEPTED,
                ProviderAcceptanceState.UNKNOWN,
            }
            and self.transition_receipt is not None
            and not local_denial
        ):
            raise AuthorizationLifecycleError(
                "provider acceptance submitted flag mismatched outcome"
            )
        expected = _attempt_digest(self)
        if self.attempt_digest != expected:
            raise AuthorizationLifecycleError("provider acceptance attempt digest mismatch")


class ProviderAcceptanceCoordinator:
    """Order one scripted provider callback without claiming distributed atomicity."""

    def __init__(
        self,
        *,
        store: ProviderAcceptanceStore,
        lease_store: StandingAuthorizationLeaseStore,
    ) -> None:
        if store.linearization_scope != PROCESS_LOCAL_LINEARIZATION:
            raise ValueError("provider acceptance store MUST declare process-local linearization")
        self._store = store
        self._lease_store = lease_store
        self._locks: dict[str, asyncio.Lock] = {}
        self._active_targets: ContextVar[frozenset[str]] = ContextVar(
            f"provider_acceptance_active_{id(self)}",
            default=frozenset(),
        )

    async def submit_once(
        self,
        *,
        identity: ProviderAcceptanceIdentity,
        submitter: ProviderSubmitPort,
        prepared_at: datetime,
        completed_at: datetime,
    ) -> ProviderAcceptanceAttempt:
        """Prepare, re-check, and submit at most once for one target-fence key."""

        target_key = identity.target_fence_digest
        active = self._active_targets.get()
        if target_key in active:
            raise ProviderAcceptanceReentrancyError(
                "provider acceptance callback re-entered the same target"
            )
        token = self._active_targets.set(active | {target_key})
        try:
            async with self._locks.setdefault(target_key, asyncio.Lock()):
                return await self._submit_locked(
                    identity=identity,
                    submitter=submitter,
                    prepared_at=prepared_at,
                    completed_at=completed_at,
                )
        finally:
            self._active_targets.reset(token)

    async def _submit_locked(
        self,
        *,
        identity: ProviderAcceptanceIdentity,
        submitter: ProviderSubmitPort,
        prepared_at: datetime,
        completed_at: datetime,
    ) -> ProviderAcceptanceAttempt:
        prepared = prepare_provider_acceptance(
            identity,
            prepared_at=aware_utc(prepared_at),
        )
        acquired = await self._store.acquire_prepared(prepared)
        if acquired.candidate_identity != identity:
            raise ProviderAcceptancePersistenceError(
                "provider acceptance store substituted the prepared identity"
            )
        if acquired.decision is not ProviderAcceptanceAcquireDecision.PERMITTED:
            return _attempt(
                decision=acquired.decision,
                record=acquired.observed_record,
                submitted=False,
                transition_receipt=None,
            )
        persisted_prepared = acquired.observed_record
        observed = await self._store.read(identity.target_fence_digest)
        if observed != persisted_prepared:
            raise ProviderAcceptancePersistenceError(
                "provider acceptance preparation readback failed"
            )
        permit = acquired.permit
        if permit is None:  # pragma: no cover - acquire result validates this
            raise RuntimeError("provider acceptance permit disappeared")
        terminal_at = max(
            aware_utc(completed_at),
            persisted_prepared.state_changed_at,
        )
        denied = await self._pre_submit_denial(
            identity,
            checked_at=terminal_at,
        )
        if denied is not None:
            terminal = complete_provider_acceptance(
                persisted_prepared,
                result=denied,
                completed_at=terminal_at,
            )
            transition = await self._persist_transition(
                persisted_prepared,
                terminal,
            )
            return _attempt(
                decision=acquired.decision,
                record=transition.record,
                submitted=False,
                transition_receipt=transition,
            )
        try:
            result = await submitter.submit(identity=identity, permit=permit)
            _validate_submitted_result(result)
        except BaseException as exc:
            reason = (
                ProviderAcceptanceAmbiguityReason.SUBMISSION_CANCELLED
                if isinstance(exc, asyncio.CancelledError)
                else (
                    ProviderAcceptanceAmbiguityReason.SUBMISSION_TIMEOUT
                    if isinstance(exc, TimeoutError)
                    else ProviderAcceptanceAmbiguityReason.SUBMISSION_EXCEPTION
                )
            )
            unknown = complete_provider_acceptance(
                persisted_prepared,
                result=ProviderSubmissionResult.create(
                    state=ProviderAcceptanceState.UNKNOWN,
                    evidence_digest=content_digest(
                        {
                            "domain": "provider-submission-exception",
                            "identity_digest": identity.identity_digest,
                            "exception_type": type(exc).__name__,
                        }
                    ),
                    ambiguity_reason=reason,
                ),
                completed_at=terminal_at,
            )
            try:
                await self._persist_transition(persisted_prepared, unknown)
            except BaseException as persist_error:
                exc.add_note(
                    "provider acceptance UNKNOWN persistence failed; "
                    "the durable PREPARED record remains submission-blocking"
                )
                exc.add_note(f"persistence_error={type(persist_error).__name__}")
            raise
        terminal = complete_provider_acceptance(
            persisted_prepared,
            result=result,
            completed_at=terminal_at,
        )
        transition = await self._persist_transition(
            persisted_prepared,
            terminal,
        )
        return _attempt(
            decision=acquired.decision,
            record=transition.record,
            submitted=True,
            transition_receipt=transition,
        )

    async def _pre_submit_denial(
        self,
        identity: ProviderAcceptanceIdentity,
        *,
        checked_at: datetime,
    ) -> ProviderSubmissionResult | None:
        if checked_at >= identity.lease_valid_until:
            return ProviderSubmissionResult.create(
                state=ProviderAcceptanceState.NOT_ACCEPTED,
                evidence_digest=content_digest(
                    {
                        "domain": "provider-acceptance-local-fence",
                        "identity_digest": identity.identity_digest,
                        "outcome": LeaseOutcome.EXPIRED.value,
                    }
                ),
                non_acceptance_kind=(ProviderNonAcceptanceEvidenceKind.LOCAL_FENCE_DENIED),
            )
        request = ProviderCommitFenceRequest(
            lease_id=identity.lease_id,
            lease_generation=identity.lease_generation,
            fence=LifecycleFence(
                family_id=identity.family_id,
                revision_id=identity.authorization_revision_id,
                fencing_generation=identity.fencing_generation,
                transition_digest=identity.transition_digest,
            ),
        )
        try:
            result = await self._lease_store.check_commit_fence(request)
        except StandingAuthorizationStoreError:
            return ProviderSubmissionResult.create(
                state=ProviderAcceptanceState.NOT_ACCEPTED,
                evidence_digest=content_digest(
                    {
                        "domain": "provider-acceptance-local-fence",
                        "identity_digest": identity.identity_digest,
                        "outcome": LeaseOutcome.PERSISTENCE_FAILURE.value,
                    }
                ),
                non_acceptance_kind=(ProviderNonAcceptanceEvidenceKind.LOCAL_FENCE_UNAVAILABLE),
            )
        if result.allowed:
            return None
        return ProviderSubmissionResult.create(
            state=ProviderAcceptanceState.NOT_ACCEPTED,
            evidence_digest=content_digest(
                {
                    "domain": "provider-acceptance-local-fence",
                    "identity_digest": identity.identity_digest,
                    "outcome": result.outcome.value,
                }
            ),
            non_acceptance_kind=ProviderNonAcceptanceEvidenceKind.LOCAL_FENCE_DENIED,
        )

    async def _persist_transition(
        self,
        prior: ProviderAcceptanceRecord,
        current: ProviderAcceptanceRecord,
    ) -> ProviderAcceptanceTransitionReceipt:
        try:
            transition = await self._store.compare_and_transition(
                prior_record_digest=prior.record_digest,
                expected_revision=prior.revision,
                record=current,
            )
            observed = await self._store.read(current.identity.target_fence_digest)
        except Exception as exc:
            raise ProviderAcceptancePersistenceError(
                "provider acceptance terminal persistence failed; "
                "the prepared record remains submission-blocking"
            ) from exc
        if transition.record != current or observed != current:
            raise ProviderAcceptancePersistenceError(
                "provider acceptance terminal readback mismatched the planned transition"
            )
        return transition


def _attempt(
    *,
    decision: ProviderAcceptanceAcquireDecision,
    record: ProviderAcceptanceRecord,
    submitted: bool,
    transition_receipt: ProviderAcceptanceTransitionReceipt | None,
) -> ProviderAcceptanceAttempt:
    values = {
        "decision": decision,
        "record": record,
        "submitted": submitted,
        "transition_receipt": transition_receipt,
        "execution_authority": False,
        "effect_verification_authority": False,
        "promotion_authority": False,
        "production_eligible": False,
    }
    attempt_digest = content_digest(
        {
            "domain": "provider-acceptance-attempt",
            **_canonical_mapping(values),
        }
    )
    return ProviderAcceptanceAttempt(
        decision=decision,
        record=record,
        submitted=submitted,
        transition_receipt=transition_receipt,
        attempt_digest=attempt_digest,
    )


def _validate_submitted_result(result: object) -> None:
    if type(result) is not ProviderSubmissionResult:
        raise AuthorizationLifecycleError("provider submitter returned an invalid result")
    if (
        result.state is ProviderAcceptanceState.NOT_ACCEPTED
        and result.non_acceptance_kind
        is not ProviderNonAcceptanceEvidenceKind.PROVIDER_REJECTED_BEFORE_ACCEPTANCE
    ):
        raise AuthorizationLifecycleError(
            "provider submitter MUST use provider non-acceptance evidence"
        )
    if (
        result.state is ProviderAcceptanceState.UNKNOWN
        and result.ambiguity_reason is not ProviderAcceptanceAmbiguityReason.PROVIDER_RESULT_UNKNOWN
    ):
        raise AuthorizationLifecycleError("provider submitter MUST use provider-result ambiguity")


def _attempt_digest(attempt: ProviderAcceptanceAttempt) -> str:
    values = asdict(attempt)
    values.pop("attempt_digest", None)
    return content_digest(
        {
            "domain": "provider-acceptance-attempt",
            **_canonical_mapping(values),
        }
    )


def _canonicalize(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _canonicalize(asdict(cast(Any, value)))
    if isinstance(value, datetime):
        return aware_utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    return value


def _canonical_mapping(value: dict[str, object]) -> dict[str, object]:
    canonical = _canonicalize(value)
    if not isinstance(canonical, dict):
        raise TypeError("provider acceptance canonical value MUST remain a mapping")
    return cast(dict[str, object], canonical)


__all__ = [
    "ProviderAcceptanceAttempt",
    "ProviderAcceptanceCoordinator",
    "ProviderAcceptancePersistenceError",
    "ProviderAcceptanceReentrancyError",
    "ProviderSubmitPort",
]

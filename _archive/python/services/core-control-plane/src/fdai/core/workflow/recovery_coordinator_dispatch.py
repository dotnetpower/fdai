"""Exactly-once recovery claim and exclusive in-flight provider dispatch.

One caller owns the in-flight claim for one attempt and hold revision, so a
concurrent recovery never invokes the provider twice. An unresolved dispatch
stays explicitly in doubt; it is never optimistically treated as delivered.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from fdai.core.workflow.recovery_attempt import (
    RecoveryAttemptIdentity,
    RecoveryDispatchOutcome,
    RecoveryDispatchResult,
    RecoveryPreDispatchClaim,
    recovery_attempt_idempotency_key,
)
from fdai.core.workflow.recovery_coordinator_models import (
    RecoveryClaimDispatchState,
    RecoveryCoordinatorConfig,
    RecoveryDispatchPort,
)
from fdai.core.workflow.recovery_coordinator_records import (
    ACTOR,
    aware_or_none,
    claim_from_record,
    claim_key,
    dispatch_from_record,
    int_or_none,
)
from fdai.core.workflow.recovery_coordinator_support import RecoveryEvidenceJournal
from fdai.shared.providers.process_runtime import ProcessSnapshot
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _InFlightLease:
    """Proof that this caller owns the exclusive in-flight claim."""

    owner: str
    took_over: bool


class RecoveryDispatchCoordinator:
    """Claim one recovery attempt exactly once and dispatch it at most once."""

    __slots__ = ("_audit_store", "_config", "_dispatcher", "_journal")

    def __init__(
        self,
        *,
        audit_store: StateStore,
        config: RecoveryCoordinatorConfig,
        journal: RecoveryEvidenceJournal,
        dispatcher: RecoveryDispatchPort | None = None,
    ) -> None:
        self._audit_store = audit_store
        self._config = config
        self._journal = journal
        self._dispatcher = dispatcher

    async def claim_once(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        hold_revision: int,
    ) -> RecoveryPreDispatchClaim | None:
        key = claim_key(attempt, hold_revision)
        existing = await self._audit_store.read_state(key)
        if existing is not None:
            return claim_from_record(existing, attempt=attempt, hold_revision=hold_revision)
        claim = RecoveryPreDispatchClaim.create(
            attempt_identity_digest=attempt.identity_digest,
            hold_revision=hold_revision,
            claim_revision=1,
            idempotency_key=recovery_attempt_idempotency_key(attempt),
            claimed_at=self._journal.now(),
        )
        record = {
            "process_id": attempt.process_id,
            "attempt_identity_digest": claim.attempt_identity_digest,
            "hold_revision": claim.hold_revision,
            "claim_revision": claim.claim_revision,
            "idempotency_key": claim.idempotency_key,
            "claimed_at": claim.claimed_at.astimezone(UTC).isoformat(),
            "claim_digest": claim.claim_digest,
            "dispatch_state": RecoveryClaimDispatchState.UNCLAIMED,
            "in_flight_owner": None,
            "in_flight_expires_at": None,
            "dispatch_outcome": RecoveryDispatchOutcome.NOT_INVOKED,
            "provider_receipt_digest": None,
            "execution_authority": False,
            "revision": 1,
        }
        created = await self._audit_store.write_state_with_audit_if_absent(
            key,
            record,
            {
                "actor": ACTOR,
                "action_kind": "workflow.recovery.claim_acquired",
                **record,
            },
        )
        if created:
            return claim
        stored = await self._audit_store.read_state(key)
        if stored is None:
            return None
        return claim_from_record(stored, attempt=attempt, hold_revision=hold_revision)

    async def dispatch_once(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
        claim: RecoveryPreDispatchClaim,
        safeguard_bundle_digest: str,
        recovery_params: Mapping[str, object],
    ) -> RecoveryDispatchResult:
        key = claim_key(attempt, claim.hold_revision)
        stored = await self._audit_store.read_state(key)
        recorded = dispatch_from_record(stored, claim=claim)
        if recorded is not None and recorded.outcome == RecoveryDispatchOutcome.DISPATCHED:
            return recorded
        if self._dispatcher is None:
            return RecoveryDispatchResult.create(
                attempt_identity_digest=attempt.identity_digest,
                claim_digest=claim.claim_digest,
                outcome=RecoveryDispatchOutcome.NOT_INVOKED,
                provider_receipt_digest=None,
                recorded_at=self._journal.now(),
            )
        lease = await self._acquire_in_flight(key=key, claim=claim, stored=stored)
        if lease is None:
            # Another caller owns the exclusive in-flight claim: this caller
            # never invokes the provider and stays in doubt until that owner
            # resolves or its lease expires.
            _LOGGER.info(
                "workflow_recovery_dispatch_claim_held",
                extra={"process_id": snapshot.process_id},
            )
            return RecoveryDispatchResult.create(
                attempt_identity_digest=attempt.identity_digest,
                claim_digest=claim.claim_digest,
                outcome=RecoveryDispatchOutcome.IN_DOUBT,
                provider_receipt_digest=None,
                recorded_at=self._journal.now(),
            )
        unresolved = recorded is not None and recorded.outcome == RecoveryDispatchOutcome.IN_DOUBT
        if unresolved or lease.took_over:
            reconciled = await self._reconcile(attempt=attempt, claim=claim)
            result = (
                reconciled
                if reconciled is not None
                else (
                    recorded
                    if recorded is not None
                    else RecoveryDispatchResult.create(
                        attempt_identity_digest=attempt.identity_digest,
                        claim_digest=claim.claim_digest,
                        outcome=RecoveryDispatchOutcome.IN_DOUBT,
                        provider_receipt_digest=None,
                        recorded_at=self._journal.now(),
                    )
                )
            )
        else:
            try:
                result = await self._dispatcher.dispatch_recovery(
                    attempt=attempt,
                    claim=claim,
                    safeguard_bundle_digest=safeguard_bundle_digest,
                    target_resource_id=snapshot.target_resource_id,
                    params=dict(recovery_params),
                    correlation_id=snapshot.correlation_id,
                )
            except Exception:  # noqa: BLE001 - an unresolved dispatch stays in doubt
                _LOGGER.exception(
                    "workflow_recovery_dispatch_in_doubt",
                    extra={"process_id": snapshot.process_id},
                )
                result = RecoveryDispatchResult.create(
                    attempt_identity_digest=attempt.identity_digest,
                    claim_digest=claim.claim_digest,
                    outcome=RecoveryDispatchOutcome.IN_DOUBT,
                    provider_receipt_digest=None,
                    recorded_at=self._journal.now(),
                )
        await self._record_dispatch(key=key, claim=claim, result=result, lease=lease)
        return result

    async def _acquire_in_flight(
        self,
        *,
        key: str,
        claim: RecoveryPreDispatchClaim,
        stored: Mapping[str, Any] | None,
    ) -> _InFlightLease | None:
        """Own the claim exclusively, or return ``None`` and stay in doubt.

        Exactly one caller may hold the in-flight claim for one attempt and
        hold revision, so a concurrent recovery never invokes the provider a
        second time. A lease that expires is taken over only for
        reconciliation, never for a fresh provider invocation.
        """

        record = dict(stored) if stored is not None else None
        for _ in range(3):
            if record is None:
                return None
            revision = int_or_none(record.get("revision"))
            if revision is None:
                return None
            if record.get("dispatch_outcome") == RecoveryDispatchOutcome.DISPATCHED:
                return None
            now = self._journal.now()
            took_over = False
            if record.get("dispatch_state") == RecoveryClaimDispatchState.IN_FLIGHT:
                expires_at = aware_or_none(record.get("in_flight_expires_at"))
                if expires_at is None or now < expires_at:
                    return None
                took_over = True
            owner = secrets.token_urlsafe(24)
            updated = {
                **record,
                "dispatch_state": RecoveryClaimDispatchState.IN_FLIGHT,
                "in_flight_owner": owner,
                "in_flight_claimed_at": now.isoformat(),
                "in_flight_expires_at": (now + self._config.dispatch_lease).isoformat(),
                "revision": revision + 1,
            }
            claimed = await self._audit_store.compare_and_set_state_with_audit(
                key,
                updated,
                expected_revision=revision,
                audit_entry={
                    "actor": ACTOR,
                    "action_kind": "workflow.recovery.dispatch_claim_acquired",
                    "attempt_identity_digest": claim.attempt_identity_digest,
                    "claim_digest": claim.claim_digest,
                    "hold_revision": claim.hold_revision,
                    "took_over_expired_lease": took_over,
                    "execution_authority": False,
                },
            )
            if claimed:
                return _InFlightLease(owner=owner, took_over=took_over)
            record = await self._journal.read_mapping(key)
        return None

    async def _reconcile(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        claim: RecoveryPreDispatchClaim,
    ) -> RecoveryDispatchResult | None:
        if self._dispatcher is None:
            return None
        try:
            return await self._dispatcher.reconcile_recovery(attempt=attempt, claim=claim)
        except Exception:  # noqa: BLE001 - reconciliation outage keeps the doubt
            _LOGGER.exception(
                "workflow_recovery_reconciliation_failed",
                extra={"process_id": attempt.process_id},
            )
            return None

    async def _record_dispatch(
        self,
        *,
        key: str,
        claim: RecoveryPreDispatchClaim,
        result: RecoveryDispatchResult,
        lease: _InFlightLease,
    ) -> None:
        for _ in range(3):
            stored = await self._journal.read_mapping(key)
            if stored is None:
                return
            revision = int_or_none(stored.get("revision"))
            if revision is None:
                return
            if (
                stored.get("dispatch_outcome") == RecoveryDispatchOutcome.DISPATCHED
                and stored.get("in_flight_owner") != lease.owner
            ):
                return
            updated = {
                **stored,
                "dispatch_state": RecoveryClaimDispatchState.RESOLVED,
                "in_flight_owner": None,
                "in_flight_expires_at": None,
                "dispatch_outcome": result.outcome,
                "provider_receipt_digest": result.provider_receipt_digest,
                "dispatch_result_digest": result.result_digest,
                "dispatch_recorded_at": result.recorded_at.astimezone(UTC).isoformat(),
                "revision": revision + 1,
            }
            committed = await self._audit_store.compare_and_set_state_with_audit(
                key,
                updated,
                expected_revision=revision,
                audit_entry={
                    "actor": ACTOR,
                    "action_kind": "workflow.recovery.dispatch_recorded",
                    "attempt_identity_digest": claim.attempt_identity_digest,
                    "claim_digest": claim.claim_digest,
                    "outcome": result.outcome,
                    "provider_receipt_digest": result.provider_receipt_digest,
                    "dispatch_result_digest": result.result_digest,
                },
            )
            if committed:
                return


__all__ = ["RecoveryDispatchCoordinator"]

"""Terminalize one recovered Process through a replay-healable outbox.

The terminal transition is committed once under the expected Process revision
and its Saga audit is delivered from a durable outbox, so a replay after a
crash re-delivers the same completion instead of minting a second one.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.workflow.recovery_attempt import (
    RecoveryAttemptIdentity,
    RecoveryAttemptRejectionReason,
    RecoveryPreDispatchClaim,
)
from fdai.core.workflow.recovery_coordinator_effect import RecoveryEffectCoordinator
from fdai.core.workflow.recovery_coordinator_models import (
    RecoveryCoordinationResult,
    RecoveryDisposition,
)
from fdai.core.workflow.recovery_coordinator_records import (
    ACTOR,
    PROCESS_EVENT_DELIVERY,
    SAGA_AUDIT_DELIVERY,
    int_or_none,
    outbox_key,
    terminal_reason,
)
from fdai.core.workflow.recovery_coordinator_release import RecoveryReleaseLedger
from fdai.core.workflow.recovery_coordinator_support import RecoveryEvidenceJournal
from fdai.core.workflow.recovery_effect_claim import EffectCompletionClaim
from fdai.core.workflow.recovery_terminalization import (
    CompletionOutboxEntry,
    OutboxDeliveryState,
    RecoveryCompletionDigest,
    TerminalTransitionRejection,
    check_replay_idempotent,
    validate_terminal_preconditions,
)
from fdai.core.workflow.workflow_runtime import WorkflowApprovalSnapshot, event_id
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRevisionConflictError,
    ProcessRuntimeStore,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)


class RecoveryTerminalizer:
    """Commit the terminal Process and Saga audit exactly once."""

    __slots__ = (
        "_audit_store",
        "_effect",
        "_journal",
        "_process_store",
        "_release_ledger",
    )

    def __init__(
        self,
        *,
        audit_store: StateStore,
        effect: RecoveryEffectCoordinator,
        journal: RecoveryEvidenceJournal,
        process_store: ProcessRuntimeStore,
        release_ledger: RecoveryReleaseLedger,
    ) -> None:
        self._audit_store = audit_store
        self._effect = effect
        self._journal = journal
        self._process_store = process_store
        self._release_ledger = release_ledger

    async def terminalize(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
        claim: RecoveryPreDispatchClaim,
        effect_claim: EffectCompletionClaim,
        approval: WorkflowApprovalSnapshot,
        hold_revision: int,
        compensation_receipt_digests: tuple[str, ...],
    ) -> RecoveryCoordinationResult:
        lookup = await self._release_ledger.read_release_lookup(
            attempt=attempt,
            effect_claim=effect_claim,
            hold_revision=hold_revision,
        )
        release_receipt_digest = lookup.release_receipt_digest if lookup is not None else None
        if release_receipt_digest is None:
            receipt = await self._release_ledger.release(
                snapshot=snapshot,
                attempt=attempt,
                effect_claim=effect_claim,
                approval=approval,
                hold_revision=hold_revision,
                compensation_receipt_digests=compensation_receipt_digests,
            )
            if receipt is None:
                return await self._journal.reject(
                    snapshot,
                    reason=RecoveryAttemptRejectionReason.SAFEGUARD_DENIED,
                    attempt=attempt,
                    claim=claim,
                )
            release_receipt_digest = receipt.receipt_digest
            await self._release_ledger.store_release_lookup(
                attempt=attempt,
                effect_claim=effect_claim,
                hold_revision=hold_revision,
                release_receipt_digest=release_receipt_digest,
            )
        return await self.commit_terminal(
            snapshot=snapshot,
            attempt=attempt,
            effect_claim=effect_claim,
            release_receipt_digest=release_receipt_digest,
            hold_revision=hold_revision,
        )

    async def commit_terminal(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
        effect_claim: EffectCompletionClaim,
        release_receipt_digest: str,
        hold_revision: int,
        evaluated_at: datetime | None = None,
    ) -> RecoveryCoordinationResult:
        current = await self._process_store.get(snapshot.process_id) or snapshot
        committed = await self._committed_completion_digest(snapshot.process_id)
        terminal_event_digest = content_digest(
            {
                "domain": "workflow-recovery-terminal-event",
                "process_id": current.process_id,
                "attempt_identity_digest": attempt.identity_digest,
                "effect_claim_digest": effect_claim.claim_digest,
            }
        )
        audit_payload_digest = content_digest(
            {
                "domain": "workflow-recovery-saga-audit",
                "process_id": current.process_id,
                "release_receipt_digest": release_receipt_digest,
                "effect_claim_digest": effect_claim.claim_digest,
            }
        )
        expected_revision = current.revision if committed is None else current.revision - 1
        completion = RecoveryCompletionDigest.create(
            process_id=current.process_id,
            saga_id=current.correlation_id,
            expected_process_revision=max(expected_revision, 0),
            recovery_attempt_digest=attempt.identity_digest,
            effect_claim_generation=effect_claim.generation,
            effect_claim_digest=effect_claim.claim_digest,
            release_receipt_digest=release_receipt_digest,
            terminal_event_digest=terminal_event_digest,
            audit_payload_digest=audit_payload_digest,
        )
        if check_replay_idempotent(
            committed_completion_digest=committed,
            expected_completion_digest=completion.completion_digest,
        ):
            await self._drain_outbox(snapshot=current, completion=completion)
            return RecoveryCoordinationResult(
                disposition=RecoveryDisposition.REPLAYED,
                attempt_identity_digest=attempt.identity_digest,
                effect_claim_digest=effect_claim.claim_digest,
                release_receipt_digest=release_receipt_digest,
                completion_digest=completion.completion_digest,
            )
        eligible, reasons = validate_terminal_preconditions(
            claim=effect_claim,
            completion=completion,
            hold_revision=hold_revision,
            fencing_generation=hold_revision + 1,
            process_revision=max(expected_revision, 0),
            expected_completion_digest=completion.completion_digest,
            release_receipt_digest=release_receipt_digest,
            committed_completion_digest=committed,
            now=evaluated_at if evaluated_at is not None else self._journal.now(),
        )
        if not eligible:
            return await self._journal.reject(
                current,
                reason=terminal_reason(reasons),
                attempt=attempt,
                disposition=RecoveryDisposition.EFFECT_UNVERIFIED,
            )
        await self._stage_outbox(completion=completion)
        terminal = await self._append_terminal(
            snapshot=current,
            attempt=attempt,
            completion=completion,
            effect_claim=effect_claim,
            release_receipt_digest=release_receipt_digest,
        )
        if terminal is None:
            return await self._journal.reject(
                current,
                reason=TerminalTransitionRejection.PROCESS_REVISION_CONFLICT.value,
                attempt=attempt,
                disposition=RecoveryDisposition.EFFECT_UNVERIFIED,
            )
        await self._drain_outbox(snapshot=terminal, completion=completion)
        return RecoveryCoordinationResult(
            disposition=RecoveryDisposition.COMPLETED,
            attempt_identity_digest=attempt.identity_digest,
            effect_claim_digest=effect_claim.claim_digest,
            release_receipt_digest=release_receipt_digest,
            completion_digest=completion.completion_digest,
        )

    async def _append_terminal(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
        completion: RecoveryCompletionDigest,
        effect_claim: EffectCompletionClaim,
        release_receipt_digest: str,
    ) -> ProcessSnapshot | None:
        try:
            return await self._process_store.transition(
                process_id=snapshot.process_id,
                expected_revision=completion.expected_process_revision,
                status=ProcessStatus.COMPENSATED,
                current_step="",
                event=ProcessEvent(
                    event_id=event_id(
                        snapshot.process_id,
                        f"recovery:completed:{completion.completion_digest}",
                    ),
                    process_id=snapshot.process_id,
                    kind=ProcessEventKind.RECOVERY_COMPLETED,
                    idempotency_key=(
                        f"{snapshot.process_id}:recovery:{completion.completion_digest}"
                    ),
                    recorded_at=self._journal.now(),
                    correlation_id=snapshot.correlation_id,
                    payload={
                        "completion_digest": completion.completion_digest,
                        "recovery_attempt_digest": attempt.identity_digest,
                        "effect_claim_digest": effect_claim.claim_digest,
                        "effect_claim_generation": effect_claim.generation,
                        "release_receipt_digest": release_receipt_digest,
                        "terminal_event_digest": completion.terminal_event_digest,
                        "audit_payload_digest": completion.audit_payload_digest,
                        "execution_authority": False,
                    },
                ),
            )
        except ProcessRevisionConflictError:
            _LOGGER.warning(
                "workflow_recovery_process_revision_conflict",
                extra={"process_id": snapshot.process_id},
            )
            return None

    async def _committed_completion_digest(self, process_id: str) -> str | None:
        events = await self._process_store.events(process_id)
        for event in reversed(events):
            if event.kind is ProcessEventKind.RECOVERY_COMPLETED:
                digest = event.payload.get("completion_digest")
                if isinstance(digest, str):
                    return digest
        return None

    # -- completion outbox --------------------------------------------------

    async def _stage_outbox(self, *, completion: RecoveryCompletionDigest) -> None:
        for kind, payload_digest in (
            (PROCESS_EVENT_DELIVERY, completion.terminal_event_digest),
            (SAGA_AUDIT_DELIVERY, completion.audit_payload_digest),
        ):
            entry = CompletionOutboxEntry.create_pending(
                completion_digest=completion.completion_digest,
                delivery_kind=kind,
                payload_digest=payload_digest,
            )
            record = {
                "process_id": completion.process_id,
                "completion_digest": entry.completion_digest,
                "delivery_kind": entry.delivery_kind,
                "delivery_state": entry.delivery_state,
                "payload_digest": entry.payload_digest,
                "attempt_count": entry.attempt_count,
                "entry_digest": entry.entry_digest,
                "execution_authority": False,
                "revision": 1,
            }
            await self._audit_store.write_state_with_audit_if_absent(
                outbox_key(completion.completion_digest, kind),
                record,
                {
                    "actor": ACTOR,
                    "action_kind": "workflow.recovery.outbox_staged",
                    **record,
                },
            )

    async def _drain_outbox(
        self,
        *,
        snapshot: ProcessSnapshot,
        completion: RecoveryCompletionDigest,
    ) -> None:
        for kind in (PROCESS_EVENT_DELIVERY, SAGA_AUDIT_DELIVERY):
            key = outbox_key(completion.completion_digest, kind)
            stored = await self._audit_store.read_state(key)
            if stored is None:
                continue
            if stored.get("delivery_state") == OutboxDeliveryState.DELIVERED:
                continue
            revision = int_or_none(stored.get("revision"))
            if revision is None:
                continue
            if kind == SAGA_AUDIT_DELIVERY:
                await self._journal.audit(
                    snapshot,
                    action_kind="workflow.recovery.completed",
                    payload={
                        "completion_digest": completion.completion_digest,
                        "recovery_attempt_digest": completion.recovery_attempt_digest,
                        "effect_claim_digest": completion.effect_claim_digest,
                        "release_receipt_digest": completion.release_receipt_digest,
                        "audit_payload_digest": completion.audit_payload_digest,
                    },
                )
            await self._audit_store.compare_and_set_state_with_audit(
                key,
                {
                    **dict(stored),
                    "delivery_state": OutboxDeliveryState.DELIVERED,
                    "attempt_count": (int_or_none(stored.get("attempt_count")) or 0) + 1,
                    "last_attempt_at": self._journal.now().isoformat(),
                    "revision": revision + 1,
                },
                expected_revision=revision,
                audit_entry={
                    "actor": ACTOR,
                    "action_kind": "workflow.recovery.outbox_delivered",
                    "completion_digest": completion.completion_digest,
                    "delivery_kind": kind,
                    "payload_digest": stored.get("payload_digest"),
                },
            )

    async def heal_committed(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
    ) -> RecoveryCoordinationResult | None:
        committed = await self._committed_completion_digest(snapshot.process_id)
        if committed is None:
            return None
        lookup = await self._release_ledger.read_release_lookup_for(attempt)
        effect_claim = await self._effect.read_current_claim(attempt)
        completion = await self._committed_completion(snapshot.process_id, committed)
        if completion is not None:
            await self._drain_outbox(snapshot=snapshot, completion=completion)
        return RecoveryCoordinationResult(
            disposition=RecoveryDisposition.REPLAYED,
            attempt_identity_digest=attempt.identity_digest,
            effect_claim_digest=(effect_claim.claim_digest if effect_claim is not None else None),
            release_receipt_digest=(lookup.release_receipt_digest if lookup is not None else None),
            completion_digest=committed,
        )

    async def _committed_completion(
        self,
        process_id: str,
        completion_digest: str,
    ) -> RecoveryCompletionDigest | None:
        events = await self._process_store.events(process_id)
        for event in reversed(events):
            if (
                event.kind is not ProcessEventKind.RECOVERY_COMPLETED
                or event.payload.get("completion_digest") != completion_digest
            ):
                continue
            snapshot = await self._process_store.get(process_id)
            if snapshot is None:
                return None
            try:
                return RecoveryCompletionDigest.create(
                    process_id=process_id,
                    saga_id=event.correlation_id,
                    expected_process_revision=max(snapshot.revision - 1, 0),
                    recovery_attempt_digest=str(event.payload["recovery_attempt_digest"]),
                    effect_claim_generation=int(str(event.payload["effect_claim_generation"])),
                    effect_claim_digest=str(event.payload["effect_claim_digest"]),
                    release_receipt_digest=str(event.payload["release_receipt_digest"]),
                    terminal_event_digest=str(event.payload["terminal_event_digest"]),
                    audit_payload_digest=str(event.payload["audit_payload_digest"]),
                )
            except (KeyError, TypeError, ValueError):
                return None
        return None


__all__ = ["RecoveryTerminalizer"]

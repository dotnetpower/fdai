"""Approval-guarded hold release and the durable release-receipt lookup.

The release consumes exactly one current successful completion claim under a
re-assessed admission. The durable lookup it writes is what lets a crash
between release, Process CAS, and Saga delivery heal without re-releasing.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime

from fdai.core.workflow.automation_hold import (
    AutomationHoldReleaseReceipt,
    StateStoreAutomationHoldLedger,
)
from fdai.core.workflow.recovery_attempt import (
    RecoveryAttemptIdentity,
    recovery_attempt_step_id,
)
from fdai.core.workflow.recovery_coordinator_models import RecoveryCoordinatorConfig
from fdai.core.workflow.recovery_coordinator_records import (
    ACTOR,
    LOOKUP_PREFIX,
    aware_or_none,
    lookup_from_record,
    lookup_key,
    recovery_action_id,
    target_evidence_digest,
)
from fdai.core.workflow.recovery_coordinator_support import (
    RecoveryAdmissionGate,
    RecoveryEvidenceJournal,
)
from fdai.core.workflow.recovery_effect_claim import EffectCompletionClaim
from fdai.core.workflow.recovery_terminalization import ReleaseReceiptLookup
from fdai.core.workflow.workflow_runtime import WorkflowApprovalSnapshot
from fdai.shared.providers.process_runtime import ProcessSnapshot
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)


class RecoveryReleaseLedger:
    """Release one held target under admission and record the exact binding."""

    __slots__ = ("_admission", "_audit_store", "_config", "_holds", "_journal")

    def __init__(
        self,
        *,
        admission: RecoveryAdmissionGate,
        audit_store: StateStore,
        config: RecoveryCoordinatorConfig,
        holds: StateStoreAutomationHoldLedger,
        journal: RecoveryEvidenceJournal,
    ) -> None:
        self._admission = admission
        self._audit_store = audit_store
        self._config = config
        self._holds = holds
        self._journal = journal

    async def consumed_release_instant(
        self,
        *,
        snapshot: ProcessSnapshot,
        lookup: ReleaseReceiptLookup,
        effect_claim: EffectCompletionClaim,
    ) -> datetime | None:
        """Return when the durable release consumed this exact claim.

        Returns ``None`` unless the persisted hold record still proves the same
        release receipt, released hold revision, fencing generation, Process,
        and consumed admission that this completion claim was bound to, and the
        hold was not reissued after that release.
        """

        record = await self._holds.read_hold_record(target_ref=snapshot.target_resource_id)
        if record is None or record.get("state") != "released":
            return None
        receipt = record.get("release_receipt")
        if not isinstance(receipt, Mapping):
            return None
        if (
            receipt.get("receipt_digest") != lookup.release_receipt_digest
            or receipt.get("released_hold_revision") != lookup.hold_revision
            or receipt.get("process_id") != snapshot.process_id
            or receipt.get("target_digest") != target_evidence_digest(snapshot.target_resource_id)
            or record.get("fencing_generation") != lookup.hold_revision + 1
            or record.get("revision") != lookup.hold_revision + 1
        ):
            return None
        if record.get("consumed_recovery_admission_digest") != effect_claim.admission_digest:
            return None
        released_at = aware_or_none(receipt.get("released_at"))
        if released_at is None or released_at < effect_claim.validity_start.astimezone(UTC):
            return None
        return released_at

    async def release(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
        effect_claim: EffectCompletionClaim,
        approval: WorkflowApprovalSnapshot,
        hold_revision: int,
        compensation_receipt_digests: tuple[str, ...],
    ) -> AutomationHoldReleaseReceipt | None:
        assessment = await self._admission.assess(
            snapshot=snapshot,
            approval=approval,
            hold_revision=hold_revision,
            compensation_receipt_digests=compensation_receipt_digests,
        )
        if (
            not assessment.eligible
            or assessment.admission is None
            or assessment.admission.receipt_digest != effect_claim.admission_digest
        ):
            return None
        try:
            return await self._holds.release_admitted(
                target_ref=snapshot.target_resource_id,
                process_id=snapshot.process_id,
                action_id=recovery_action_id(attempt),
                hold_revision=hold_revision,
                approval_snapshot=approval,
                quorum=self._config.quorum,
                no_self_approval=self._config.no_self_approval,
                compensation_receipt_digests=compensation_receipt_digests,
                executor_identity=self._config.executor_identity,
                source_revision=self._config.source_revision,
                assessment=assessment,
                workflow_lineage=(
                    snapshot.process_id,
                    recovery_attempt_step_id(attempt),
                ),
            )
        except Exception:  # noqa: BLE001 - release persistence keeps the hold in force
            _LOGGER.exception(
                "workflow_recovery_release_failed",
                extra={"process_id": snapshot.process_id},
            )
            return None

    async def store_release_lookup(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        effect_claim: EffectCompletionClaim,
        hold_revision: int,
        release_receipt_digest: str,
    ) -> None:
        lookup = ReleaseReceiptLookup.create(
            recovery_attempt_digest=attempt.identity_digest,
            effect_claim_digest=effect_claim.claim_digest,
            hold_revision=hold_revision,
            release_receipt_digest=release_receipt_digest,
        )
        record = {
            "process_id": attempt.process_id,
            "recovery_attempt_digest": lookup.recovery_attempt_digest,
            "effect_claim_digest": lookup.effect_claim_digest,
            "hold_revision": lookup.hold_revision,
            "release_receipt_digest": lookup.release_receipt_digest,
            "lookup_digest": lookup.lookup_digest,
            "execution_authority": False,
            "revision": 1,
        }
        await self._audit_store.write_state_with_audit_if_absent(
            lookup_key(attempt, effect_claim, hold_revision),
            record,
            {
                "actor": ACTOR,
                "action_kind": "workflow.recovery.release_lookup_stored",
                **record,
            },
        )

    async def read_release_lookup(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        effect_claim: EffectCompletionClaim,
        hold_revision: int,
    ) -> ReleaseReceiptLookup | None:
        stored = await self._audit_store.read_state(
            lookup_key(attempt, effect_claim, hold_revision)
        )
        return lookup_from_record(stored)

    async def read_release_lookup_for(
        self,
        attempt: RecoveryAttemptIdentity,
    ) -> ReleaseReceiptLookup | None:
        stored = await self._audit_store.find_state(
            LOOKUP_PREFIX,
            field="recovery_attempt_digest",
            value=attempt.identity_digest,
        )
        return lookup_from_record(stored)


__all__ = ["RecoveryReleaseLedger"]

"""Shared evidence journal and admission gate for the recovery path.

Both seams are deliberately small. The journal owns the one place a recovery
decision becomes an audit record and the one clock the whole path reads; the
admission gate owns the one place current approval, quorum, and identity
separation are re-assessed. Neither grants authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.workflow.recovery_admission import (
    WorkflowRecoveryAdmissionAssessment,
    assess_workflow_recovery_admission,
)
from fdai.core.workflow.recovery_attempt import (
    RecoveryAttemptIdentity,
    RecoveryPreDispatchClaim,
)
from fdai.core.workflow.recovery_coordinator_models import (
    RecoveryCoordinationResult,
    RecoveryCoordinatorConfig,
    RecoveryDisposition,
)
from fdai.core.workflow.recovery_coordinator_records import ACTOR, target_evidence_digest
from fdai.core.workflow.workflow_runtime import WorkflowApprovalSnapshot, event_id
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.process_runtime import ProcessSnapshot
from fdai.shared.providers.state_store import StateStore


class RecoveryEvidenceJournal:
    """Append recovery evidence and read the single aware recovery clock."""

    __slots__ = ("_audit_store", "_clock")

    def __init__(
        self,
        *,
        audit_store: StateStore,
        clock: Callable[[], datetime],
    ) -> None:
        self._audit_store = audit_store
        self._clock = clock

    async def reject(
        self,
        snapshot: ProcessSnapshot,
        *,
        reason: str,
        detail: str | None = None,
        attempt: RecoveryAttemptIdentity | None = None,
        claim: RecoveryPreDispatchClaim | None = None,
        disposition: RecoveryDisposition = RecoveryDisposition.REJECTED,
    ) -> RecoveryCoordinationResult:
        await self.audit(
            snapshot,
            action_kind="workflow.recovery.rejected",
            payload={
                "reason": reason,
                "detail": detail,
                "attempt_identity_digest": (
                    attempt.identity_digest if attempt is not None else None
                ),
                "claim_digest": claim.claim_digest if claim is not None else None,
                "recovery_incomplete": True,
            },
        )
        return RecoveryCoordinationResult(
            disposition=disposition,
            reason=reason,
            attempt_identity_digest=(attempt.identity_digest if attempt is not None else None),
            claim_digest=claim.claim_digest if claim is not None else None,
        )

    async def audit(
        self,
        snapshot: ProcessSnapshot,
        *,
        action_kind: str,
        payload: Mapping[str, object],
    ) -> None:
        await self._audit_store.append_audit_entry(
            {
                "event_id": event_id(
                    snapshot.process_id,
                    f"recovery:{action_kind}:{content_digest(dict(payload))}",
                ),
                "correlation_id": snapshot.correlation_id,
                "actor": ACTOR,
                "action_kind": action_kind,
                "process_id": snapshot.process_id,
                **dict(payload),
                "recorded_at": self.now().isoformat(),
            }
        )

    async def read_mapping(self, key: str) -> dict[str, Any] | None:
        stored = await self._audit_store.read_state(key)
        return dict(stored) if stored is not None else None

    def now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recovery coordinator clock MUST return aware time")
        return value.astimezone(UTC)


class RecoveryAdmissionGate:
    """Re-assess current approval, quorum, and identity separation."""

    __slots__ = ("_admission_provider", "_config", "_journal")

    def __init__(
        self,
        *,
        admission_provider: DecisionEvidenceAdmissionProvider | None,
        config: RecoveryCoordinatorConfig,
        journal: RecoveryEvidenceJournal,
    ) -> None:
        self._admission_provider = admission_provider
        self._config = config
        self._journal = journal

    async def assess(
        self,
        *,
        snapshot: ProcessSnapshot,
        approval: WorkflowApprovalSnapshot,
        hold_revision: int,
        compensation_receipt_digests: tuple[str, ...],
    ) -> WorkflowRecoveryAdmissionAssessment:
        """Assess current approval, quorum, identity separation, and admission."""

        return await assess_workflow_recovery_admission(
            self._admission_provider,
            snapshot=approval,
            quorum=self._config.quorum,
            no_self_approval=self._config.no_self_approval,
            hold_revision=hold_revision,
            target_digest=target_evidence_digest(snapshot.target_resource_id),
            compensation_receipt_digests=compensation_receipt_digests,
            executor_identity=self._config.executor_identity,
            source_revision=self._config.source_revision,
            evaluated_at=self._journal.now(),
        )


__all__ = [
    "RecoveryAdmissionGate",
    "RecoveryEvidenceJournal",
]

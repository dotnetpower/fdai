"""Bind one recovery attempt to its identity, approval, and safeguard bundle.

Binding is evidence work only. It proves that a distinct recovery attempt
exists, that a separate immutable human approval was recorded for it, and that
the finalized safeguard bundle the production dispatch retained is the one
this attempt is bound to. None of it approves, dispatches, or verifies.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.workflow.recovery_attempt import (
    RecoveryApprovalEvidence,
    RecoveryAttemptIdentity,
    RecoverySafeguardEvidence,
    recovery_attempt_step_id,
)
from fdai.core.workflow.recovery_coordinator_models import (
    RecoveryApprovalReader,
    RecoveryApprovalRequester,
    RecoveryCoordinatorConfig,
    RecoverySafeguardBundleReader,
)
from fdai.core.workflow.recovery_coordinator_records import (
    ACTOR,
    ATTEMPT_PREFIX,
    DIGEST_LENGTH,
    attempt_key,
    int_or_none,
    target_evidence_digest,
)
from fdai.core.workflow.recovery_coordinator_support import RecoveryEvidenceJournal
from fdai.core.workflow.workflow_runtime import WorkflowApprovalSnapshot
from fdai.shared.providers.process_runtime import ProcessSnapshot
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)


class RecoveryAttemptBinder:
    """Own attempt identity, approval resolution, and safeguard binding."""

    __slots__ = (
        "_approval_reader",
        "_approval_requester",
        "_audit_store",
        "_bundle_reader",
        "_config",
        "_journal",
    )

    def __init__(
        self,
        *,
        audit_store: StateStore,
        config: RecoveryCoordinatorConfig,
        journal: RecoveryEvidenceJournal,
        approval_reader: RecoveryApprovalReader | None = None,
        approval_requester: RecoveryApprovalRequester | None = None,
        bundle_reader: RecoverySafeguardBundleReader | None = None,
    ) -> None:
        self._audit_store = audit_store
        self._config = config
        self._journal = journal
        self._approval_reader = approval_reader
        self._approval_requester = approval_requester
        self._bundle_reader = bundle_reader

    async def build_attempt(
        self,
        *,
        snapshot: ProcessSnapshot,
        failed_compensation_proposal_digest: str,
        recovery_action_type: str,
        recovery_params: Mapping[str, object],
        hold_revision: int,
    ) -> RecoveryAttemptIdentity:
        existing, _ = await self._audit_store.read_state_page(
            ATTEMPT_PREFIX,
            limit=64,
            field="process_id",
            value=snapshot.process_id,
        )
        attempt_number = 1 + sum(
            1
            for row in existing
            if isinstance(row.get("attempt_number"), int)
            and row.get("hold_revision") != hold_revision
        )
        return RecoveryAttemptIdentity.create(
            process_id=snapshot.process_id,
            failed_compensation_proposal_digest=failed_compensation_proposal_digest,
            hold_revision=hold_revision,
            recovery_action_type=recovery_action_type,
            recovery_payload_digest=content_digest(
                {
                    "action_type": recovery_action_type,
                    "params": dict(recovery_params),
                    "purpose": "workflow-recovery-payload",
                }
            ),
            target_digest=target_evidence_digest(snapshot.target_resource_id),
            source_revision=self._config.source_revision,
            attempt_number=attempt_number,
        )

    async def persist_attempt(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        approval_evidence: RecoveryApprovalEvidence,
        process_id: str,
    ) -> None:
        key = attempt_key(attempt)
        record = {
            "process_id": process_id,
            "recovery_step_id": recovery_attempt_step_id(attempt),
            "attempt_identity_digest": attempt.identity_digest,
            "failed_compensation_proposal_digest": (attempt.failed_compensation_proposal_digest),
            "hold_revision": attempt.hold_revision,
            "recovery_action_type": attempt.recovery_action_type,
            "recovery_payload_digest": attempt.recovery_payload_digest,
            "target_digest": attempt.target_digest,
            "source_revision": attempt.source_revision,
            "attempt_number": attempt.attempt_number,
            "approval_evidence_digest": approval_evidence.evidence_digest,
            "approver_identity": approval_evidence.approver_identity,
            "safeguard_bundle_digest": None,
            "safeguard_evidence_digest": None,
            "execution_authority": False,
            "revision": 1,
        }
        created = await self._audit_store.write_state_with_audit_if_absent(
            key,
            record,
            {
                "actor": ACTOR,
                "action_kind": "workflow.recovery.attempt_bound",
                **record,
            },
        )
        if created:
            return
        stored = await self._audit_store.read_state(key)
        if stored is None or stored.get("attempt_identity_digest") != attempt.identity_digest:
            raise ValueError("recovery attempt identity conflicted with a stored attempt")
        if stored.get("approval_evidence_digest") != approval_evidence.evidence_digest:
            raise ValueError("recovery attempt approval evidence is not immutable")

    async def bind_safeguard_evidence(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
    ) -> str | None:
        """Bind the finalized safeguard bundle this attempt dispatched under.

        The executor finalizes the bundle inside its own logical-target lock,
        so the workflow binds it once the production dispatch retained it. The
        binding is immutable: a different bundle for the same attempt fails
        closed and the hold stays in force.
        """

        key = attempt_key(attempt)
        stored = await self._journal.read_mapping(key)
        if stored is None:
            return None
        bundle_digest = await self.resolve_bundle(snapshot=snapshot, attempt=attempt)
        if bundle_digest is None:
            return None
        evidence = RecoverySafeguardEvidence.create(
            attempt_identity_digest=attempt.identity_digest,
            safeguard_bundle_digest=bundle_digest,
            completed_at=self._journal.now(),
        )
        recorded = stored.get("safeguard_bundle_digest")
        if recorded is not None:
            return str(recorded) if recorded == bundle_digest else None
        revision = int_or_none(stored.get("revision"))
        if revision is None:
            return None
        updated = {
            **stored,
            "safeguard_bundle_digest": evidence.safeguard_bundle_digest,
            "safeguard_evidence_digest": evidence.evidence_digest,
            "revision": revision + 1,
        }
        committed = await self._audit_store.compare_and_set_state_with_audit(
            key,
            updated,
            expected_revision=revision,
            audit_entry={
                "actor": ACTOR,
                "action_kind": "workflow.recovery.safeguard_bundle_bound",
                "attempt_identity_digest": attempt.identity_digest,
                "safeguard_bundle_digest": evidence.safeguard_bundle_digest,
                "safeguard_evidence_digest": evidence.evidence_digest,
                "execution_authority": False,
            },
        )
        if committed:
            return bundle_digest
        current = await self._journal.read_mapping(key)
        if current is None or current.get("safeguard_bundle_digest") != bundle_digest:
            return None
        return bundle_digest

    # -- approval and safeguard binding -------------------------------------

    async def request_approval(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
    ) -> None:
        """Ask a separate human for this exact attempt, never grant it."""

        requester = self._approval_requester
        if requester is None:
            return
        try:
            await requester.request_recovery_approval(
                attempt=attempt,
                process_id=snapshot.process_id,
                target_resource_id=snapshot.target_resource_id,
                correlation_id=snapshot.correlation_id,
            )
        except Exception:  # noqa: BLE001 - an unrequestable approval keeps the hold
            _LOGGER.exception(
                "workflow_recovery_approval_request_failed",
                extra={"process_id": snapshot.process_id},
            )
            return
        await self._journal.audit(
            snapshot,
            action_kind="workflow.recovery.approval_requested",
            payload={
                "attempt_identity_digest": attempt.identity_digest,
                "recovery_step_id": recovery_attempt_step_id(attempt),
                "approval_authority": False,
            },
        )

    async def resolve_approval(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
    ) -> WorkflowApprovalSnapshot | None:
        """Return the approval bound to this exact attempt, without judging it.

        Eligibility belongs to ``assess_workflow_recovery_admission``; this seam
        only proves that a separate approval record exists for this Process.
        """

        if self._approval_reader is None:
            return None
        approval = await self._approval_reader.recovery_approval(
            attempt=attempt,
            process_id=snapshot.process_id,
            target_resource_id=snapshot.target_resource_id,
        )
        if approval is None or approval.process_id != snapshot.process_id:
            return None
        return approval

    async def resolve_bundle(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
    ) -> str | None:
        if self._bundle_reader is None:
            return None
        digest = await self._bundle_reader.finalized_recovery_bundle_digest(
            attempt=attempt,
            target_resource_id=snapshot.target_resource_id,
        )
        if digest is None or DIGEST_LENGTH != len(digest) or not digest.startswith("sha256:"):
            return None
        return digest


__all__ = ["RecoveryAttemptBinder"]

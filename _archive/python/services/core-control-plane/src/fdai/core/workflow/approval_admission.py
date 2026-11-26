"""Shared evidence admission for one durable workflow approval outcome.

A recorded approval quorum is a positive decision boundary: it lets a Process
leave an approval step and advance toward a state change. The durable decision
snapshot alone proves only that decisions were persisted, so this module binds
that snapshot to the shared decision-critical evidence admission contract. The
admission carries no execution or promotion authority; it only reports that the
exact snapshot the executor read is admissible evidence for advancing.
"""

from __future__ import annotations

from datetime import datetime

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.workflow.workflow_runtime import WorkflowApprovalSnapshot
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)

WORKFLOW_APPROVAL_EVIDENCE_PURPOSE = "workflow-approval-quorum"
"""Purpose the admission MUST declare before a quorum can advance a Process."""


def workflow_approval_evidence_digest(
    snapshot: WorkflowApprovalSnapshot,
    *,
    quorum: int,
    no_self_approval: bool,
) -> str:
    """Return the exact digest of the durable decision snapshot being admitted.

    Every field that changes who approved, how many approvals count, or which
    attempt they belong to is part of the digest, so a replayed or reshaped
    snapshot cannot reuse an admission issued for a different one.
    """

    return content_digest(
        {
            "process_id": snapshot.process_id,
            "step_id": snapshot.step_id,
            "attempt": snapshot.attempt,
            "revision": snapshot.revision,
            "requester_principal": snapshot.requester_principal,
            "quorum": quorum,
            "no_self_approval": no_self_approval,
            "decisions": [
                {
                    "principal": decision.principal,
                    "decision": decision.decision,
                    "receipt_ref": decision.receipt_ref,
                }
                for decision in snapshot.decisions
            ],
        }
    )


def workflow_approval_scope_digest(snapshot: WorkflowApprovalSnapshot) -> str:
    """Return the Process, step, and attempt scope one admission may cover."""

    return content_digest(
        {
            "process_id": snapshot.process_id,
            "step_id": snapshot.step_id,
            "attempt": snapshot.attempt,
        }
    )


async def workflow_approval_admission_rejection_reasons(
    provider: DecisionEvidenceAdmissionProvider | None,
    *,
    snapshot: WorkflowApprovalSnapshot,
    quorum: int,
    no_self_approval: bool,
    evaluated_at: datetime,
) -> tuple[str, ...]:
    """Return why the shared admission cannot advance this recorded quorum.

    An unbound provider, an absent admission, or any mismatch between the
    admission and the exact snapshot fails closed. An empty tuple means the
    snapshot is admissible evidence at ``evaluated_at``.
    """

    evidence_digest = workflow_approval_evidence_digest(
        snapshot,
        quorum=quorum,
        no_self_approval=no_self_approval,
    )
    scope_digest = workflow_approval_scope_digest(snapshot)
    source_revision = f"workflow-approval-revision:{snapshot.revision}"
    admission: DecisionEvidenceAdmission | None = None
    if provider is not None:
        admission = await provider.admit(
            evidence_digest=evidence_digest,
            scope_digest=scope_digest,
            purpose_id=WORKFLOW_APPROVAL_EVIDENCE_PURPOSE,
            source_revision=source_revision,
        )
    if admission is None:
        return ("decision_evidence_admission_missing",)
    return tuple(
        f"decision_evidence_{reason.value}"
        for reason in assess_decision_evidence_admission(
            admission,
            expected_evidence_digest=evidence_digest,
            expected_scope_digest=scope_digest,
            expected_purpose_id=WORKFLOW_APPROVAL_EVIDENCE_PURPOSE,
            expected_source_revision=source_revision,
            evaluated_at=evaluated_at,
        )
    )


__all__ = [
    "WORKFLOW_APPROVAL_EVIDENCE_PURPOSE",
    "workflow_approval_admission_rejection_reasons",
    "workflow_approval_evidence_digest",
    "workflow_approval_scope_digest",
]

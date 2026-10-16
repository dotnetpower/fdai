from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef
from fdai_service_contracts.rule_activation_retention import (
    RuleRevisionReferenceKind,
    RuleRevisionReferenceV2,
    RuleRevisionRetentionSnapshotV2,
    RuleRevisionRetirementApprovalV2,
    RuleRevisionRetirementCommandV2,
    RuleRevisionRetirementProposalV2,
    RuleRevisionRetirementReceiptV2,
    rule_revision_retention_snapshot_digest,
    rule_revision_retirement_approval_digest,
    rule_revision_retirement_command_digest,
    rule_revision_retirement_proposal_digest,
    rule_revision_retirement_receipt_digest,
)

NOW = datetime(2026, 10, 18, tzinfo=UTC)


def _digest(character: str) -> str:
    return "sha256:" + (character * 64)


def _revision() -> RuleRevisionIdentityRef:
    return RuleRevisionIdentityRef(
        rule_id="rule.retired",
        rule_version="1.0.0",
        revision_digest=_digest("a"),
    )


def _snapshot(
    references: tuple[RuleRevisionReferenceV2, ...] = (),
) -> RuleRevisionRetentionSnapshotV2:
    values = {
        "revision": _revision(),
        "retention_epoch_revision": 3,
        "references": references,
        "captured_at": NOW,
    }
    return RuleRevisionRetentionSnapshotV2(
        **values,
        snapshot_digest=rule_revision_retention_snapshot_digest(**values),
    )


def test_retirement_contract_binds_zero_reference_snapshot_and_receipt() -> None:
    snapshot = _snapshot()
    proposal_values = {
        "snapshot": snapshot,
        "reviewed_source_revision": "b" * 40,
        "requested_by": "requester-a",
        "requested_at": NOW + timedelta(seconds=1),
        "reason": "The revision has no remaining governed references.",
    }
    proposal = RuleRevisionRetirementProposalV2(
        **proposal_values,
        proposal_digest=rule_revision_retirement_proposal_digest(**proposal_values),
    )
    approval_values = {
        "proposal_digest": proposal.proposal_digest,
        "authority_receipt_digest": _digest("c"),
        "approval_profile_digest": _digest("d"),
        "requester_id": proposal.requested_by,
        "approver_ids": ("approver-a", "approver-b"),
        "original_quorum": 2,
        "effective_quorum": 2,
        "approved_at": NOW + timedelta(seconds=2),
    }
    approval = RuleRevisionRetirementApprovalV2(
        **approval_values,
        approval_digest=rule_revision_retirement_approval_digest(**approval_values),
    )
    command_values = {
        "proposal": proposal,
        "approval": approval,
        "commanded_at": NOW + timedelta(seconds=3),
    }
    command = RuleRevisionRetirementCommandV2(
        **command_values,
        command_digest=rule_revision_retirement_command_digest(**command_values),
    )
    receipt_values = {
        "revision": snapshot.revision,
        "reference_snapshot_digest": snapshot.snapshot_digest,
        "retirement_command_digest": command.command_digest,
        "retired_at": command.commanded_at,
    }
    receipt = RuleRevisionRetirementReceiptV2(
        **receipt_values,
        receipt_digest=rule_revision_retirement_receipt_digest(**receipt_values),
    )

    assert receipt.revision == snapshot.revision


def test_referenced_revision_cannot_be_proposed_for_retirement() -> None:
    reference = RuleRevisionReferenceV2(
        revision=_revision(),
        kind=RuleRevisionReferenceKind.ROLLBACK_ELIGIBLE,
        owner_digest=_digest("e"),
    )
    snapshot = _snapshot((reference,))
    values = {
        "snapshot": snapshot,
        "reviewed_source_revision": "b" * 40,
        "requested_by": "requester-a",
        "requested_at": NOW + timedelta(seconds=1),
        "reason": "The revision still has a rollback reference.",
    }

    with pytest.raises(ValueError, match="Referenced"):
        RuleRevisionRetirementProposalV2(
            **values,
            proposal_digest=rule_revision_retirement_proposal_digest(**values),
        )

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from fdai_service_contracts.rule_activation import (
    RuleActivationApproval,
    RuleActivationCommand,
    RuleActivationDelta,
    RuleActivationGeneration,
    RuleActivationMember,
    RuleActivationProposal,
    RuleActivationResult,
    RuleActivationSource,
    RuleActivationStatus,
    rule_activation_generation_digest,
    rule_activation_proposal_digest,
)

NOW = datetime(2026, 9, 22, tzinfo=UTC)
DIGEST = "a" * 64


def _generation() -> RuleActivationGeneration:
    members = (
        RuleActivationMember(
            rule_id="rule.alpha",
            rule_version="1.0.0",
            rule_digest="b" * 64,
        ),
    )
    digest = rule_activation_generation_digest(
        profile_id="baseline",
        profile_version="1.0.0",
        catalog_digest=DIGEST,
        members=members,
    )
    return RuleActivationGeneration(
        generation_id=f"rule-activation-{digest[:32]}",
        generation_digest=digest,
        profile_id="baseline",
        profile_version="1.0.0",
        catalog_digest=DIGEST,
        members=members,
        created_at=NOW,
    )


def _proposal(*, requested_by: str = "requester") -> RuleActivationProposal:
    changes = (RuleActivationDelta(rule_id="rule.alpha", enabled=True),)
    digest = rule_activation_proposal_digest(
        idempotency_key="activate-alpha",
        expected_generation_digest=DIGEST,
        source=RuleActivationSource.DIRECT,
        source_ref="operator-api:rules",
        source_digest="c" * 64,
        requested_by=requested_by,
        requested_at=NOW,
        reason="Enable the reviewed baseline Rule for observation.",
        changes=changes,
    )
    return RuleActivationProposal(
        request_id=f"rule-activation-request-{digest[:32]}",
        idempotency_key="activate-alpha",
        expected_generation_digest=DIGEST,
        source=RuleActivationSource.DIRECT,
        source_ref="operator-api:rules",
        source_digest="c" * 64,
        requested_by=requested_by,
        requested_at=NOW,
        reason="Enable the reviewed baseline Rule for observation.",
        changes=changes,
    )


def test_generation_requires_sorted_unique_members_and_exact_digest() -> None:
    generation = _generation()

    assert generation.generation_id.endswith(generation.generation_digest[:32])
    with pytest.raises(ValidationError, match="digest mismatch"):
        RuleActivationGeneration.model_validate(
            {**generation.model_dump(mode="json"), "generation_digest": "d" * 64}
        )


def test_non_installation_proposal_requires_expected_generation() -> None:
    proposal = _proposal()

    with pytest.raises(ValidationError, match="expected generation"):
        RuleActivationProposal.model_validate(
            {**proposal.model_dump(mode="json"), "expected_generation_digest": None}
        )


def test_command_binds_distinct_approval_to_exact_proposal() -> None:
    proposal = _proposal()
    approval = RuleActivationApproval(
        proposal_digest=proposal.proposal_digest,
        approver_ids=("approver",),
        approved_at=NOW + timedelta(minutes=1),
        approval_ref="approval:one",
    )
    command = RuleActivationCommand(
        proposal=proposal,
        approval=approval,
        generation=_generation(),
        commanded_at=NOW + timedelta(minutes=2),
    )

    assert len(command.command_digest) == 64
    with pytest.raises(ValidationError, match="MUST NOT approve"):
        RuleActivationCommand(
            proposal=proposal,
            approval=approval.model_copy(update={"approver_ids": ("requester",)}),
            generation=_generation(),
            commanded_at=NOW + timedelta(minutes=2),
        )


def test_requester_cannot_approve_with_a_case_variant() -> None:
    proposal = _proposal(requested_by="Human.Example")
    approval = RuleActivationApproval(
        proposal_digest=proposal.proposal_digest,
        approver_ids=("human.example",),
        approved_at=NOW + timedelta(minutes=1),
        approval_ref="approval:case-variant",
    )

    with pytest.raises(ValidationError, match="MUST NOT approve"):
        RuleActivationCommand(
            proposal=proposal,
            approval=approval,
            generation=_generation(),
            commanded_at=NOW + timedelta(minutes=2),
        )


def test_applied_result_requires_authoritative_readback() -> None:
    with pytest.raises(ValidationError, match="verified readback"):
        RuleActivationResult(
            request_id=_proposal().request_id,
            command_digest="d" * 64,
            source=RuleActivationSource.DIRECT,
            source_ref="operator-api:rules",
            requested_by="requester",
            approver_ids=("approver",),
            reason="Apply the reviewed Rule membership change safely.",
            changes=(RuleActivationDelta(rule_id="rule.alpha", enabled=True),),
            status=RuleActivationStatus.APPLIED,
            previous_generation_digest=DIGEST,
            resulting_generation_digest="e" * 64,
            completed_at=NOW,
            readback_verified=False,
        )


def test_conflict_result_requires_auditable_reason() -> None:
    with pytest.raises(ValidationError, match="requires exactly one failure reason"):
        RuleActivationResult(
            request_id=_proposal().request_id,
            command_digest="d" * 64,
            source=RuleActivationSource.DIRECT,
            source_ref="operator-api:rules",
            requested_by="requester",
            approver_ids=("approver",),
            reason="Apply the reviewed Rule membership change safely.",
            changes=(RuleActivationDelta(rule_id="rule.alpha", enabled=True),),
            status=RuleActivationStatus.CONFLICT,
            previous_generation_digest=DIGEST,
            resulting_generation_digest=None,
            completed_at=NOW,
            readback_verified=False,
        )

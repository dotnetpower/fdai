from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai_service_contracts.rule_activation_identity import (
    build_rule_activation_identity_context_v2,
    build_rule_activation_identity_transition_v2,
)
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef
from fdai_service_contracts.rule_activation_revision_change import (
    RuleBindingAuthorityPointerV2,
    RuleRevisionChangeApprovalV2,
    RuleRevisionChangeCommandV2,
    RuleRevisionChangeProposalV2,
    RuleRevisionTransitionKind,
    rule_binding_authority_pointer_v2_digest,
    rule_revision_change_approval_digest,
    rule_revision_change_command_digest,
    rule_revision_change_proposal_digest,
)
from fdai_service_contracts.rule_activation_slots import (
    RuleBindingMode,
    RuleRevisionBindingV2,
    rule_revision_binding_digest,
)

NOW = datetime(2026, 10, 18, tzinfo=UTC)


def _digest(character: str) -> str:
    return "sha256:" + (character * 64)


def _revision(rule_id: str, version: str, character: str) -> RuleRevisionIdentityRef:
    return RuleRevisionIdentityRef(
        rule_id=rule_id,
        rule_version=version,
        revision_digest=_digest(character),
    )


def _proposal() -> RuleRevisionChangeProposalV2:
    old = _revision("rule.alpha", "1.0.0", "a")
    new = _revision("rule.alpha", "1.1.0", "b")
    unchanged = _revision("rule.beta", "1.0.0", "c")
    source = build_rule_activation_identity_context_v2(
        catalog_revisions=(old, new, unchanged),
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=(old, unchanged),
    )
    target = build_rule_activation_identity_context_v2(
        catalog_revisions=(old, new, unchanged),
        profile_id="baseline",
        profile_version="1.1.0",
        active_members=(new, unchanged),
    )
    transition = build_rule_activation_identity_transition_v2(source=source, target=target)
    values = {
        "source_authority_pointer_digest": _digest("d"),
        "identity_transition": transition,
        "transition_kind": RuleRevisionTransitionKind.REVISION_CHANGE,
        "rollback_eligibility_digest": None,
        "rollback_eligible_until": NOW + timedelta(days=7),
        "rule_id": old.rule_id,
        "binding_id": "binding-alpha",
        "from_revision": old,
        "to_revision": new,
        "slot_digest": _digest("e"),
        "binding_move_command_digest": _digest("f"),
        "signed_manifest_digest": _digest("1"),
        "release_id": "release-2",
        "revision_registry_root": _digest("2"),
        "cohort_prepare_digest": _digest("3"),
        "reviewed_source_revision": "4" * 40,
        "proposed_by": "requester-a",
        "proposed_at": NOW,
    }
    return RuleRevisionChangeProposalV2(
        **values,
        proposal_digest=rule_revision_change_proposal_digest(**values),
    )


def _approval(proposal: RuleRevisionChangeProposalV2) -> RuleRevisionChangeApprovalV2:
    values = {
        "proposal_digest": proposal.proposal_digest,
        "authority_receipt_digest": _digest("5"),
        "approval_profile_digest": _digest("6"),
        "requester_id": proposal.proposed_by,
        "approver_ids": ("approver-a", "approver-b"),
        "original_quorum": 2,
        "effective_quorum": 2,
        "approved_at": NOW + timedelta(seconds=1),
    }
    return RuleRevisionChangeApprovalV2(
        **values,
        approval_digest=rule_revision_change_approval_digest(**values),
    )


def test_revision_change_binds_transition_approval_and_binding_pointer() -> None:
    proposal = _proposal()
    approval = _approval(proposal)
    command_values = {
        "proposal": proposal,
        "approval": approval,
        "commanded_at": NOW + timedelta(seconds=2),
    }
    command = RuleRevisionChangeCommandV2(
        **command_values,
        command_digest=rule_revision_change_command_digest(**command_values),
    )
    binding_values = {
        "binding_id": "binding-alpha",
        "revision": proposal.to_revision,
        "profile_snapshot_digest": (
            proposal.identity_transition.target.profile_snapshot.snapshot_digest
        ),
        "mode": RuleBindingMode.ENFORCE,
        "promotion_evidence_digest": approval.approval_digest,
    }
    enforcing = RuleRevisionBindingV2(
        **binding_values,
        binding_digest=rule_revision_binding_digest(**binding_values),
    )
    pointer_values = {
        "revision": 1,
        "binding_id": enforcing.binding_id,
        "enforcing": enforcing,
        "generation_digest": proposal.identity_transition.target.generation.generation_digest,
        "previous_binding_digest": _digest("7"),
        "binding_move_command_digest": proposal.binding_move_command_digest,
        "revision_change_command_digest": command.command_digest,
        "changed_at": command.commanded_at,
    }
    pointer = RuleBindingAuthorityPointerV2(
        **pointer_values,
        pointer_digest=rule_binding_authority_pointer_v2_digest(**pointer_values),
    )

    assert pointer.activation_authority is True
    assert pointer.enforcing.revision == proposal.to_revision


def test_revision_change_rejects_an_unattended_second_revision() -> None:
    proposal = _proposal()
    source = proposal.identity_transition.source
    second = _revision("rule.beta", "1.1.0", "8")
    target = build_rule_activation_identity_context_v2(
        catalog_revisions=(*source.catalog_manifest.revisions, second),
        profile_id=source.profile_snapshot.profile_id,
        profile_version="1.1.0",
        active_members=(proposal.to_revision, second),
    )
    transition = build_rule_activation_identity_transition_v2(source=source, target=target)
    values = {
        **proposal.model_dump(),
        "identity_transition": transition,
    }
    values["proposal_digest"] = rule_revision_change_proposal_digest(
        **{
            key: value
            for key, value in values.items()
            if key
            not in {
                "schema_version",
                "proposal_digest",
                "approval_authority",
                "activation_authority",
                "execution_authority",
            }
        }
    )

    with pytest.raises(ValueError, match="exactly the named Rule"):
        RuleRevisionChangeProposalV2.model_validate(values)


def test_revision_change_rejects_an_unrelated_profile_switch() -> None:
    proposal = _proposal()
    source = proposal.identity_transition.source
    target = build_rule_activation_identity_context_v2(
        catalog_revisions=source.catalog_manifest.revisions,
        profile_id="emergency",
        profile_version="1.0.0",
        active_members=(proposal.to_revision, source.profile_snapshot.members[1]),
    )
    transition = build_rule_activation_identity_transition_v2(source=source, target=target)
    values = {
        **proposal.model_dump(),
        "identity_transition": transition,
    }
    values["proposal_digest"] = rule_revision_change_proposal_digest(
        **{
            key: value
            for key, value in values.items()
            if key
            not in {
                "schema_version",
                "proposal_digest",
                "approval_authority",
                "activation_authority",
                "execution_authority",
            }
        }
    )

    with pytest.raises(ValueError, match="within one profile"):
        RuleRevisionChangeProposalV2.model_validate(values)

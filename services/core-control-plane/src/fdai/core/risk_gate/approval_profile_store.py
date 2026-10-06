"""Authoritative approval-profile revision lookup for pinned approval replay."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fdai_service_contracts.approval_profile import (
    ApprovalProfileRevision,
    approval_profile_from_audit_dict,
)
from fdai_service_contracts.policy_administration import ApprovalPolicyContent, PolicyKind

if TYPE_CHECKING:
    from fdai.shared.providers.state_store import StateStore


async def approval_profile_pin_is_authorized(
    store: StateStore | None,
    *,
    pinned: ApprovalProfileRevision,
    bound: ApprovalProfileRevision | None,
    bootstrap: ApprovalProfileRevision | None = None,
) -> bool:
    """Return whether one pinned profile is the active/bound or stored revision."""

    if bound is not None and pinned.as_audit_dict() == bound.as_audit_dict():
        return True
    if bootstrap is not None and pinned.as_audit_dict() == bootstrap.as_audit_dict():
        return True
    if store is None:
        return False
    stored = await store.read_state(_revision_key(pinned.revision_id))
    if stored is None:
        return False
    content = stored.get("content")
    if not isinstance(content, dict):
        return False
    document = content.get("document")
    if not isinstance(document, dict):
        return False
    try:
        ApprovalPolicyContent.model_validate(content)
        stored_profile = approval_profile_from_audit_dict(document)
    except ValueError:
        return False
    return (
        stored.get("policy_kind") == PolicyKind.APPROVAL.value
        and isinstance(stored_profile, ApprovalProfileRevision)
        and stored_profile.as_audit_dict() == pinned.as_audit_dict()
    )


def _revision_key(revision_id: str) -> str:
    return f"policy_revision:{PolicyKind.APPROVAL.value}:{revision_id}"


__all__ = ["approval_profile_pin_is_authorized"]

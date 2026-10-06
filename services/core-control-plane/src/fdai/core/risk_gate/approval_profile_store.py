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
    index = await store.read_state(_activation_index_key(pinned.policy_digest))
    mimir_revision_id = _index_revision_id(index)
    if mimir_revision_id is None:
        return False
    history = await store.read_state(_activation_history_key(mimir_revision_id))
    if history is None or _history_profile_digest(index) != pinned.policy_digest:
        return False
    if _history_revision_id(history) != mimir_revision_id:
        return False
    stored = await store.read_state(_revision_key(mimir_revision_id))
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


def _activation_history_key(revision_id: str) -> str:
    return f"policy_activation_history:{PolicyKind.APPROVAL.value}:{revision_id}"


def _activation_index_key(policy_digest: str) -> str:
    return f"policy_activation_history:approval-profile:{policy_digest}"


def _index_revision_id(index: object) -> str | None:
    if not isinstance(index, dict):
        return None
    revision_id = index.get("revision_id")
    return revision_id if isinstance(revision_id, str) and revision_id else None


def _history_revision_id(history: object) -> str | None:
    if not isinstance(history, dict):
        return None
    revision_id = history.get("revision_id")
    return revision_id if isinstance(revision_id, str) and revision_id else None


def _history_profile_digest(history: object) -> object:
    if not isinstance(history, dict):
        return None
    return history.get("approval_profile_digest") or history.get("policy_digest")


__all__ = ["approval_profile_pin_is_authorized"]

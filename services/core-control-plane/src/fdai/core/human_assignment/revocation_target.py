"""Read-only binding of a removal intent to its exact original assignment."""

from __future__ import annotations

from fdai.core.human_assignment.coverage import normalize_principal_ref
from fdai.core.human_assignment.model import AssignmentCase, AssignmentIntent, AssignmentState
from fdai.core.human_assignment.repository import load_case_state
from fdai.shared.providers.state_store import StateStore


async def require_revocation_target(
    store: StateStore,
    intent: AssignmentIntent,
    *,
    revocation_case_id: str,
    allow_held: bool = False,
) -> AssignmentCase:
    """Read the exact active grant, or this removal's own durable pre-effect hold.

    A hold is not a removal receipt. It only prevents the old assignment from authorizing new
    goal mutations while effect convergence is unknown. Another case cannot borrow that hold.
    """
    target = intent.revocation
    if target is None or target.case_id == revocation_case_id:
        raise ValueError("revocation requires a separate original assignment")
    old = await load_case_state(store, target.case_id)
    matches = (
        old.intent.revocation is None
        and old.has_required_effects
        and old.intent.subject.provider == intent.subject.provider == "entra"
        and normalize_principal_ref(old.intent.subject.subject_id)
        == normalize_principal_ref(intent.subject.subject_id)
        and old.intent.requested_role is intent.requested_role
        and old.intent.duty_bindings == intent.duty_bindings
    )
    active = old.state is AssignmentState.ACTIVE and old.revision == target.revision
    held = (
        allow_held
        and old.state is AssignmentState.DEGRADED
        and old.revision == target.revision + 1
        and old.revocation_case_id == revocation_case_id
        and old.degraded_reason == "revocation_pending"
    )
    if not matches or not (active or held):
        raise ValueError("revocation no longer matches the original grant revision and target")
    return old


__all__ = ["require_revocation_target"]

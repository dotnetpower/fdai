"""Development-profile inputs for one control-loop authority evaluation.

Only an event that carries ``development_authority_confirmation`` takes the development path.
Every other event keeps the ordinary multi-operator authority, even when a profile is selected, so
selecting the profile never widens or blocks unrelated work. Malformed confirmation evidence grants
nothing: the shared evaluator then denies the development path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fdai.shared.contracts.models import (
    Action,
    DevelopmentActionConfirmation,
    Event,
    FullAuthorityDevelopmentProfile,
    OntologyActionType,
)
from fdai.shared.providers.development_authority import (
    DevelopmentAuthorityBindingRequest,
    DevelopmentAuthorityBindingSource,
)

CONFIRMATION_FIELD = "development_authority_confirmation"


def development_authority_inputs(
    *,
    profile: FullAuthorityDevelopmentProfile | None,
    binding_source: DevelopmentAuthorityBindingSource | None,
    executor_principal: str | None,
    event: Event,
    action: Action,
    action_type: OntologyActionType,
    now: datetime,
) -> dict[str, Any]:
    """Return ``evaluate_unified`` development keywords, or none for the ordinary path."""
    raw = event.payload.get(CONFIRMATION_FIELD)
    if raw is None or profile is None or binding_source is None or not executor_principal:
        return {}
    try:
        confirmation: DevelopmentActionConfirmation | None = (
            DevelopmentActionConfirmation.model_validate(raw)
        )
    except (TypeError, ValueError):
        confirmation = None
    return {
        "development_profile": profile,
        "development_confirmation": confirmation,
        "development_binding_source": binding_source,
        "development_binding_request": DevelopmentAuthorityBindingRequest.from_action(
            action_type=action_type.name,
            action_id=str(action.action_id),
            target_ref=action.target_resource_ref,
            params=action.params,
            requester_principal=profile.owner_principal,
            executor_principal=executor_principal,
            idempotency_key=action.idempotency_key,
            rollback_contract=action.rollback_ref.kind.value,
        ),
        "development_evaluated_at": now,
    }


__all__ = ["CONFIRMATION_FIELD", "development_authority_inputs"]

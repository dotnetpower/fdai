"""Development-profile park preparation for one operator request.

When the full-authority development profile is selected and the Owner's own request routes to
human approval, Core reads the exact target revision, records the binding of the exact action it
is about to park, and attaches a digest-bound park block. The block grants nothing: the Owner's
self-approval still needs a fresh authenticated attestation when the approval resolves. Missing
development evidence parks the action for ordinary multi-operator approval instead.

A category-only denial of the Owner's own request parks only inside a currently valid profile,
with an Owner-only block that keeps the category facts and the evaluated event. Missing
development evidence keeps that denial.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fdai.core.hil_resume.development import development_park_block
from fdai.core.risk_gate.category_denial import CategoryDenial
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision
from fdai.shared.contracts.development_authority import normalized_principal
from fdai.shared.contracts.models import (
    Action,
    Event,
    FullAuthorityDevelopmentProfile,
    OntologyActionType,
)
from fdai.shared.providers.development_authority import (
    DevelopmentAuthorityBindingSource,
    DevelopmentBindingPreparer,
)
from fdai.shared.providers.execution_authorization import (
    ExecutionAuthorizationResult,
    ExecutionAuthorizationStatus,
)
from fdai.shared.providers.target_revision import TargetRevisionReader

_LOGGER = logging.getLogger(__name__)


async def prepare_development_park(
    *,
    profile: FullAuthorityDevelopmentProfile | None,
    bindings: DevelopmentAuthorityBindingSource | None,
    revisions: TargetRevisionReader | None,
    initiator: object,
    action: Action,
    action_type: OntologyActionType | None,
    authorization: ExecutionAuthorizationResult | None,
    unified: UnifiedRiskDecision,
    category_denial: CategoryDenial | None = None,
    evaluation_event: Event | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Return the park block for the Owner's exact action, or ``None`` for ordinary approval.

    With ``category_denial`` the block is Owner-only, records the residual quorum as the original
    requirement, and requires the evaluated event and a profile that is valid at ``now``;
    ``None`` then keeps the denial.
    """
    if category_denial is not None and (
        profile is None
        or evaluation_event is None
        or now is None
        or not profile.valid_from <= now < profile.valid_until
    ):
        return None
    if (
        profile is None
        or not isinstance(bindings, DevelopmentBindingPreparer)
        or revisions is None
        or action_type is None
        or not isinstance(initiator, str)
        or normalized_principal(initiator) != normalized_principal(profile.owner_principal)
        or authorization is None
        or authorization.status is not ExecutionAuthorizationStatus.AUTHORIZED
        or action.executor_identity_ref is None
    ):
        return None
    try:
        revision = await revisions.read_revision(action.target_resource_ref)
        if revision is None:
            return None
        verification = await bindings.prepare_park_binding(
            action=action,
            action_type=action_type,
            target_revision=revision,
        )
    except Exception:  # noqa: BLE001 - missing development evidence parks for ordinary approval
        _LOGGER.warning(
            "development_park_binding_unavailable",
            extra={"action_type": action.action_type},
            exc_info=True,
        )
        return None
    return development_park_block(
        profile=profile,
        verification=verification,
        original_level=unified.decision,
        # A lifted category prohibition leaves the table's residual quorum, which the Owner's one
        # approval then stands in for; the audit records it instead of the denial's quorum.
        original_quorum=(
            max(unified.quorum, category_denial.residual_quorum)
            if category_denial is not None
            else unified.quorum
        ),
        executor_identity_ref=action.executor_identity_ref,
        category_denial=(category_denial.as_audit_dict() if category_denial is not None else None),
        evaluation_event=(
            evaluation_event.model_dump(mode="json")
            if category_denial is not None and evaluation_event is not None
            else None
        ),
    )


__all__ = ["prepare_development_park"]

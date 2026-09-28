"""Development-profile park preparation for one operator request.

When the full-authority development profile is selected and the Owner's own request routes to
human approval, Core reads the exact target revision, records the binding of the exact action it
is about to park, and attaches a digest-bound park block. The block grants nothing: the Owner's
self-approval still needs a fresh authenticated attestation when the approval resolves. Missing
development evidence parks the action for ordinary multi-operator approval instead.
"""

from __future__ import annotations

import logging
from typing import Any

from fdai.core.hil_resume.development import development_park_block
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision
from fdai.shared.contracts.development_authority import normalized_principal
from fdai.shared.contracts.models import (
    Action,
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
) -> dict[str, Any] | None:
    """Return the park block for the Owner's exact action, or ``None`` for ordinary approval."""
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
        original_quorum=unified.quorum,
        executor_identity_ref=action.executor_identity_ref,
    )


__all__ = ["prepare_development_park"]

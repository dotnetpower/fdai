"""Human-approval registry binding for Core bootstrap."""

from __future__ import annotations

from fdai.shared.providers.hil_registry import HilWorkflowDecisionRegistry
from fdai.shared.providers.state_store import StateStore


def build_hil_workflow_registry(state_store: StateStore) -> HilWorkflowDecisionRegistry:
    """Bind the authoritative quorum owner used by the HIL decision consumer."""

    from fdai.delivery.persistence.state_store_hil_registry import (
        StateStoreHilApprovalRegistry,
    )

    return StateStoreHilApprovalRegistry(store=state_store)


__all__ = ["build_hil_workflow_registry"]

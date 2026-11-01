"""FDAI Lifecycle Hub.

The Hub computes signed Lifecycle Plans from an installation's channel subscription, version
range, configuration revision, and constraints. It holds no Azure credential, secret value, or
operational data, and it grants no lifecycle authority by itself: installation agents admit,
narrow, and apply a Plan only under their own local checks.
"""

from __future__ import annotations

from fdai_lifecycle_hub.entitlement_handoff import (
    EntitlementHandoffGovernanceError,
    GovernedEntitlementRotationReceipt,
    HubEntitlementHandoffStore,
    OpaqueEntitlementCarrierHandoff,
)

__all__ = [
    "EntitlementHandoffGovernanceError",
    "GovernedEntitlementRotationReceipt",
    "HubEntitlementHandoffStore",
    "OpaqueEntitlementCarrierHandoff",
]

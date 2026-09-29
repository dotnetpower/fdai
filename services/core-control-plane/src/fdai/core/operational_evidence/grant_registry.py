"""Compatibility facade for the shared case-scope grant registry."""

from fdai_service_contracts.operational_evidence_grants import (
    GRANT_OPERATIONS,
    GRANT_REGISTRY_ID,
    CaseScope,
    CaseScopeGrantRegistry,
    GrantDecision,
    PrincipalGrant,
    ReuseGrant,
)

__all__ = [
    "GRANT_OPERATIONS",
    "GRANT_REGISTRY_ID",
    "CaseScope",
    "CaseScopeGrantRegistry",
    "GrantDecision",
    "PrincipalGrant",
    "ReuseGrant",
]

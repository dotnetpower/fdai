"""Compatibility facade for the shared case-scope grant registry loader."""

from fdai_service_contracts.operational_evidence_grants import (
    RegistryUnavailableError as SharedRegistryUnavailableError,
)
from fdai_service_contracts.operational_evidence_grants import (
    RevisionClass as SharedRevisionClass,
)
from fdai_service_contracts.operational_evidence_grants import (
    classify_grant_revision as _classify_grant_revision,
)
from fdai_service_contracts.operational_evidence_grants import (
    load_grant_registry as _load_grant_registry,
)

from .grant_registry import CaseScopeGrantRegistry
from .registry_json import RegistryUnavailableError, RevisionClass


def load_grant_registry(data: bytes, *, expected_pin: str) -> CaseScopeGrantRegistry:
    """Load one pinned grant registry using the shared validation implementation."""
    try:
        return _load_grant_registry(data, expected_pin=expected_pin)
    except SharedRegistryUnavailableError as exc:
        raise RegistryUnavailableError(str(exc)) from exc


def classify_grant_revision(
    previous: CaseScopeGrantRegistry, current: CaseScopeGrantRegistry
) -> RevisionClass:
    """Classify grant revisions while preserving Core's public enum type."""
    result = _classify_grant_revision(previous, current)
    return (
        RevisionClass.REVOCATION
        if result is SharedRevisionClass.REVOCATION
        else RevisionClass.ROUTINE_ROTATION
    )


__all__ = ["classify_grant_revision", "load_grant_registry"]

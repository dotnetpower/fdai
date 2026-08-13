"""Project raw Azure discovery rows into bounded opaque provider observations."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_service_contracts.discovery import DiscoveryMappingStatus, DiscoveryScopeKind
from fdai_service_contracts.discovery_evidence import ProviderResourceObservation
from fdai_service_contracts.ontology_query import content_digest


def observe_azure_resource(
    row: Mapping[str, object],
    *,
    scope_kind: DiscoveryScopeKind,
    semantic_types: Mapping[str, str],
    evidence_ref: str,
) -> ProviderResourceObservation:
    """Retain an Azure row as mapped or unmapped without exposing its raw provider id."""

    provider_ref = row.get("id")
    provider_type = row.get("type")
    if not isinstance(provider_ref, str) or not provider_ref:
        raise ValueError("Azure discovery row MUST include a provider id")
    if not isinstance(provider_type, str) or not provider_type:
        raise ValueError("Azure discovery row MUST include a provider type")
    semantic_type = semantic_types.get(provider_type.casefold())
    name_value = row.get("name")
    name = name_value if isinstance(name_value, str) and name_value else None
    return ProviderResourceObservation(
        provider_ref_digest=content_digest(
            {"cloud": "azure", "provider_ref": provider_ref.casefold()}
        ),
        provider_type=provider_type,
        scope_kind=scope_kind,
        mapping_status=(
            DiscoveryMappingStatus.MAPPED
            if semantic_type is not None
            else DiscoveryMappingStatus.UNMAPPED
        ),
        semantic_type=semantic_type,
        name=name,
        evidence_ref=evidence_ref,
    )


__all__ = ["observe_azure_resource"]

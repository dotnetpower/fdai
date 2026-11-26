"""Project raw Azure discovery rows into bounded opaque provider observations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

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
    if not isinstance(provider_ref, str) or not provider_ref.strip():
        raise ValueError("Azure discovery row MUST include a provider id")
    if not isinstance(provider_type, str) or not provider_type.strip():
        raise ValueError("Azure discovery row MUST include a provider type")
    if not isinstance(evidence_ref, str) or not evidence_ref.strip():
        raise ValueError("Azure discovery observation MUST include an evidence_ref")
    clean_ref = provider_ref.strip()
    clean_type = provider_type.strip()
    folded_type = clean_type.casefold()
    semantic_type = semantic_types.get(folded_type)
    if semantic_type is None:
        for key, value in semantic_types.items():
            if str(key).strip().casefold() == folded_type:
                semantic_type = value
                break
    name_value = row.get("name")
    name = name_value.strip() if isinstance(name_value, str) and name_value.strip() else None
    return ProviderResourceObservation(
        provider_ref_digest=content_digest(
            {"cloud": "azure", "provider_ref": clean_ref.casefold()}
        ),
        provider_type=clean_type,
        scope_kind=scope_kind,
        mapping_status=(
            DiscoveryMappingStatus.MAPPED
            if semantic_type is not None
            else DiscoveryMappingStatus.UNMAPPED
        ),
        semantic_type=semantic_type,
        name=name,
        evidence_ref=evidence_ref.strip(),
    )


def observe_azure_resources_batch(
    rows: Sequence[Mapping[str, object]],
    *,
    scope_kind: DiscoveryScopeKind,
    semantic_types: Mapping[str, str],
    evidence_ref: str,
) -> tuple[ProviderResourceObservation, ...]:
    """Project and deterministically deduplicate a batch of Azure discovery rows."""
    by_digest: dict[str, ProviderResourceObservation] = {}
    for row in rows:
        obs = observe_azure_resource(
            row,
            scope_kind=scope_kind,
            semantic_types=semantic_types,
            evidence_ref=evidence_ref,
        )
        by_digest.setdefault(obs.provider_ref_digest, obs)
    return tuple(by_digest[k] for k in sorted(by_digest))


__all__ = ["observe_azure_resource", "observe_azure_resources_batch"]

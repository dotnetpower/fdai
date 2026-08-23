"""Project exact cross-resource Azure relationships from one complete generation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from urllib.parse import urlparse

from fdai.delivery.azure.arg_relationships import (
    ArmIdToType,
    RelationshipProjectionResult,
    ToNeutralId,
    project_provider_relationships,
)
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    ProviderRelationshipMappingCatalog,
)
from fdai.shared.providers.inventory import LinkRecord, RelationshipDrop, ResourceRecord

_MAX_ALIAS_LENGTH = 2_048
_MAX_ALIASES_PER_RESOURCE = 64
_TARGET_ALIAS_PATHS: Mapping[str, tuple[str, ...]] = {
    "api-gateway": ("properties.gatewayUrl",),
    "communication-service": ("properties.hostName",),
    "compute.container-app": (
        "properties.configuration.ingress.fqdn",
        "properties.latestRevisionFqdn",
    ),
    "compute.function": ("properties.defaultHostName",),
    "container-registry": ("properties.loginServer",),
    "event-hub": ("properties.serviceBusEndpoint",),
    "llm-endpoint": ("properties.endpoint",),
    "log-workspace": ("properties.customerId",),
    "managed-identity": ("properties.principalId",),
    "mysql-server": ("properties.fullyQualifiedDomainName",),
    "object-storage": ("properties.primaryEndpoints{values}",),
    "postgresql-server": ("properties.fullyQualifiedDomainName",),
    "redis-enterprise": ("properties.hostName",),
    "resource-group": ("name",),
    "secret-store": ("properties.vaultUri",),
    "static-web-app": ("properties.defaultHostname",),
}


def project_complete_generation_relationships(
    resources: Sequence[ResourceRecord],
    *,
    catalog: ProviderRelationshipMappingCatalog,
    arm_to_neutral: Mapping[str, str],
    arm_id_to_type: ArmIdToType,
    to_neutral_id: ToNeutralId,
) -> RelationshipProjectionResult:
    """Resolve reviewed aliases only when one complete generation has one exact target."""

    aliases: dict[str, set[str]] = defaultdict(set)
    neutral_type_by_provider_ref: dict[str, str] = {}
    for resource in resources:
        if resource.provider_ref is None:
            continue
        neutral_type_by_provider_ref[resource.provider_ref.casefold()] = resource.type
        count = 0
        for path in _TARGET_ALIAS_PATHS.get(resource.type, ()):
            for value in _path_values(resource.props, path):
                for key in _alias_keys(value):
                    aliases[key].add(resource.provider_ref)
                    count += 1
                    if count >= _MAX_ALIASES_PER_RESOURCE:
                        break
                if count >= _MAX_ALIASES_PER_RESOURCE:
                    break
            if count >= _MAX_ALIASES_PER_RESOURCE:
                break

    def resolve(reference: str) -> str | None:
        candidates: set[str] = set()
        for key in _alias_keys(reference):
            candidates.update(aliases.get(key, ()))
        return next(iter(candidates)) if len(candidates) == 1 else None

    generation_mapping_ids = {
        mapping.mapping_id
        for mapping in catalog.mappings
        if mapping.provider.casefold() == "azure"
        and mapping.source_identity.casefold() == "azure-resource-graph-complete-generation"
    }
    links: list[LinkRecord] = []
    drops: list[RelationshipDrop] = []
    for resource in resources:
        if resource.provider_ref is None:
            continue
        row = dict(resource.props)
        row["id"] = resource.provider_ref
        row["type"] = resource.props.get("providerType") or arm_id_to_type(resource.provider_ref)
        result = project_provider_relationships(
            row,
            owner=resource,
            arm_to_neutral=arm_to_neutral,
            catalog=catalog,
            arm_id_to_type=arm_id_to_type,
            to_neutral_id=to_neutral_id,
            external_reference_resolver=resolve,
            resolved_neutral_types=neutral_type_by_provider_ref,
            source_identity="azure-resource-graph-complete-generation",
        )
        links.extend(
            link
            for link in result.links
            if link.mapping_evidence is not None
            and link.mapping_evidence.mapping_id in generation_mapping_ids
        )
        drops.extend(drop for drop in result.dropped if drop.mapping_id in generation_mapping_ids)
    return RelationshipProjectionResult(
        links=tuple(links),
        dropped=tuple(
            sorted(
                drops,
                key=lambda item: (
                    item.reason.value,
                    item.mapping_id or "",
                    item.source_property_path or "",
                ),
            )
        ),
    )


def _path_values(value: object, path: str) -> tuple[str, ...]:
    values = [value]
    for segment in path.split("."):
        mapping_values = segment.endswith("{values}")
        collection = segment.endswith("[]")
        key = segment[:-8] if mapping_values else segment[:-2] if collection else segment
        next_values: list[object] = []
        for current in values:
            if not isinstance(current, Mapping):
                continue
            child = current.get(key)
            if mapping_values and isinstance(child, Mapping):
                next_values.extend(child.values())
            elif collection and isinstance(child, Sequence) and not isinstance(child, (str, bytes)):
                next_values.extend(child)
            elif not mapping_values and not collection:
                next_values.append(child)
        values = next_values
    return tuple(item.strip() for item in values if isinstance(item, str) and item.strip())


def _alias_keys(value: str) -> frozenset[str]:
    text = value.strip().casefold().rstrip("/.")
    if not text or len(text) > _MAX_ALIAS_LENGTH:
        return frozenset()
    keys = {text}
    try:
        parsed = urlparse(text if "://" in text else f"//{text}")
        hostname = parsed.hostname
    except ValueError:
        hostname = None
    if hostname:
        keys.add(hostname.casefold().rstrip("."))
    return frozenset(keys)


__all__ = ["project_complete_generation_relationships"]

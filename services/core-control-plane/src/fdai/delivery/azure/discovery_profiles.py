"""Versioned Azure discovery profiles containing only registered operation metadata."""

from __future__ import annotations

from fdai_service_contracts.discovery import (
    DiscoveryBackend,
    DiscoveryLimits,
    DiscoveryOperationProfile,
    DiscoveryPredicateField,
    DiscoveryPredicateOperator,
    DiscoveryProfile,
    DiscoveryResultKind,
    DiscoveryScopeKind,
    DiscoveryUniverse,
    discovery_profile_digest,
)

AZURE_DISCOVERY_CATALOG_VERSION = "1.0.0"


def default_azure_discovery_profiles() -> tuple[DiscoveryProfile, ...]:
    """Return the reviewed resource-container and generic ARM discovery profiles."""

    return (
        _profile(
            profile_id="azure.resource-groups",
            provider_type="Microsoft.Resources/subscriptions/resourceGroups",
            universe=DiscoveryUniverse.RESOURCE_CONTAINERS,
            operations=(
                _operation(
                    operation_id="azure.inventory.resource-groups.list",
                    backend=DiscoveryBackend.PROMOTED_INVENTORY,
                    priority=10,
                    template_id="azure.arg.resource-groups.list.v1",
                    equivalence_key="azure.resource-groups.list.v1",
                ),
                _operation(
                    operation_id="azure.arg.resource-groups.list",
                    backend=DiscoveryBackend.RESOURCE_GRAPH,
                    priority=20,
                    template_id="azure.arg.resource-groups.list.v1",
                    equivalence_key="azure.resource-groups.list.v1",
                ),
                _operation(
                    operation_id="azure.arm.resource-groups.list",
                    backend=DiscoveryBackend.GENERIC_ARM,
                    priority=30,
                    template_id="azure.arm.resource-groups.list.v1",
                    equivalence_key="azure.resource-groups.list.v1",
                ),
            ),
            provenance_ref="microsoft.resource-graph.resource-containers",
        ),
        _profile(
            profile_id="azure.arm-resources",
            provider_type="Microsoft.Resources/resources",
            universe=DiscoveryUniverse.ARM_RESOURCES,
            operations=(
                _operation(
                    operation_id="azure.inventory.resources.list",
                    backend=DiscoveryBackend.PROMOTED_INVENTORY,
                    priority=10,
                    template_id="azure.arg.resources.list.v1",
                    equivalence_key="azure.arm-resources.list.v1",
                ),
                _operation(
                    operation_id="azure.arg.resources.list",
                    backend=DiscoveryBackend.RESOURCE_GRAPH,
                    priority=20,
                    template_id="azure.arg.resources.list.v1",
                    equivalence_key="azure.arm-resources.list.v1",
                ),
                _operation(
                    operation_id="azure.arm.resources.list",
                    backend=DiscoveryBackend.GENERIC_ARM,
                    priority=30,
                    template_id="azure.arm.resources.list.v1",
                    equivalence_key="azure.arm-resources.list.v1",
                ),
            ),
            provenance_ref="microsoft.resource-graph.resources",
        ),
    )


def profile_by_id(profile_id: str) -> DiscoveryProfile:
    """Resolve one built-in profile or fail before provider I/O."""

    profiles = {profile.profile_id: profile for profile in default_azure_discovery_profiles()}
    try:
        return profiles[profile_id]
    except KeyError as exc:
        raise LookupError(f"unknown Azure discovery profile {profile_id!r}") from exc


def _operation(
    *,
    operation_id: str,
    backend: DiscoveryBackend,
    priority: int,
    template_id: str,
    equivalence_key: str,
) -> DiscoveryOperationProfile:
    return DiscoveryOperationProfile(
        operation_id=operation_id,
        backend=backend,
        universes=(
            DiscoveryUniverse.RESOURCE_CONTAINERS
            if "resource-groups" in operation_id
            else DiscoveryUniverse.ARM_RESOURCES,
        ),
        result_kinds=(
            DiscoveryResultKind.LIST,
            DiscoveryResultKind.COUNT,
            DiscoveryResultKind.TYPES,
        ),
        scope_kinds=(DiscoveryScopeKind.SUBSCRIPTION, DiscoveryScopeKind.RESOURCE_GROUP),
        predicate_fields=(
            DiscoveryPredicateField.NAME,
            DiscoveryPredicateField.PROVIDER_TYPE,
            DiscoveryPredicateField.RESOURCE_GROUP,
            DiscoveryPredicateField.LOCATION,
        ),
        predicate_operators=(
            DiscoveryPredicateOperator.EQ,
            DiscoveryPredicateOperator.CONTAINS,
            DiscoveryPredicateOperator.IN,
            DiscoveryPredicateOperator.EXISTS,
        ),
        projection=("provider_ref", "provider_type", "name", "resource_group", "location"),
        output_schema_id="provider-resource-observation.v1",
        equivalence_key=equivalence_key,
        identity_profile="azure.reader",
        priority=priority,
        command_template_id=template_id,
    )


def _profile(
    *,
    profile_id: str,
    provider_type: str,
    universe: DiscoveryUniverse,
    operations: tuple[DiscoveryOperationProfile, ...],
    provenance_ref: str,
) -> DiscoveryProfile:
    for operation in operations:
        if operation.universes != (universe,):
            raise ValueError("Azure discovery profile operation universe mismatch")
    values: dict[str, object] = {
        "profile_id": profile_id,
        "revision": AZURE_DISCOVERY_CATALOG_VERSION,
        "cloud": "azure",
        "provider_type": provider_type,
        "operations": operations,
        "limits": DiscoveryLimits(),
        "provenance_refs": (provenance_ref,),
    }
    return DiscoveryProfile.model_validate(
        {"profile_digest": discovery_profile_digest(**values), **values}
    )


__all__ = [
    "AZURE_DISCOVERY_CATALOG_VERSION",
    "default_azure_discovery_profiles",
    "profile_by_id",
]

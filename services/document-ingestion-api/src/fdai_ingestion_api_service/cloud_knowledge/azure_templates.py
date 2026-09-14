"""Inert public-source templates; source rights and collection need explicit review."""

from fdai_service_contracts.cloud_knowledge import Applicability, CloudKnowledgeSource


def azure_network_sources(collection_id: str) -> tuple[CloudKnowledgeSource, ...]:
    """Return a bounded APIM/network starter set with collection and transfer disabled."""
    definitions = (
        (
            "apim-vnet",
            "API Management virtual network resources",
            "api-management/virtual-network-injection-resources",
            "Microsoft.ApiManagement/service",
            "classic",
        ),
        (
            "vnet",
            "Virtual Network overview",
            "virtual-network/virtual-networks-overview",
            "Microsoft.Network/virtualNetworks",
            "resource-manager",
        ),
        (
            "nsg",
            "Network security groups",
            "virtual-network/network-security-groups-overview",
            "Microsoft.Network/networkSecurityGroups",
            "resource-manager",
        ),
        (
            "private-dns",
            "Private DNS overview",
            "dns/private-dns-overview",
            "Microsoft.Network/privateDnsZones",
            "resource-manager",
        ),
    )
    return tuple(
        CloudKnowledgeSource(
            source_id=identity,
            collection_id=collection_id,
            title=title,
            url=f"https://learn.microsoft.com/en-us/azure/{path}",
            applicability=Applicability(
                resource_type=resource_type,
                service_generation=generation,
                skus=("Developer", "Premium") if identity == "apim-vnet" else (),
            ),
            license_ref="requires-source-rights-review",
        )
        for identity, title, path, resource_type, generation in definitions
    )

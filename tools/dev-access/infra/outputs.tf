output "subscription_id" {
  description = "Subscription that owns the isolated development-access stack."
  value       = data.azurerm_client_config.current.subscription_id
  sensitive   = true
}

output "resource_group_name" {
  description = "Resource group containing only development-access resources."
  value       = azurerm_resource_group.dev_access.name
}

output "vpn_gateway_name" {
  description = "VPN Gateway used to generate the Azure VPN Client profile."
  value       = azurerm_virtual_network_gateway.dev_access.name
}

output "dns_resolver_inbound_ip" {
  description = "Private DNS Resolver address pushed to generated P2S profiles."
  value       = azurerm_private_dns_resolver_inbound_endpoint.dev_access.ip_configurations[0].private_ip_address
}

output "dev_access_vnet_id" {
  description = "Resource ID of the isolated development-access VNet."
  value       = azurerm_virtual_network.dev_access.id
}

output "fdai_private_dns_routing_domains" {
  description = "Split-DNS routing suffixes derived from the linked private zones, with the privatelink prefix removed so the Resolver only receives FDAI private-service lookups. Public sign-in domains such as login.microsoftonline.com keep the workstation default resolver."
  value = sort([
    for zone in var.fdai_private_dns_zones : replace(
      replace(zone.name, "privatelink.", ""),
      "vaultcore.azure.net",
      "vault.azure.net",
    )
  ])
}

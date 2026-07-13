output "vnet_id" {
  description = "Resource id of the VNet."
  value       = azurerm_virtual_network.primary.id
}

output "vnet_name" {
  value = azurerm_virtual_network.primary.name
}

output "pe_subnet_id" {
  description = "Subnet for private endpoints (KV, ACR, Event Hubs, Postgres)."
  value       = azurerm_subnet.pe.id
}

output "infra_subnet_id" {
  description = "Delegated subnet the Container App Environment binds as its infrastructure subnet."
  value       = azurerm_subnet.infra.id
}

output "postgres_subnet_id" {
  description = "Delegated subnet for PostgreSQL Flexible Server private access."
  value       = azurerm_subnet.postgres.id
}

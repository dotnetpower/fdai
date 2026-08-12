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

output "functions_subnet_id" {
  description = "Dedicated Flex Consumption Function App VNet integration subnet."
  value       = length(azurerm_subnet.functions) > 0 ? azurerm_subnet.functions[0].id : null
}

output "evidence_target_subnet_id" {
  description = "Isolated subnet for the development OHL scale-out evidence target."
  value       = length(azurerm_subnet.evidence_target) > 0 ? azurerm_subnet.evidence_target[0].id : null
}

output "evidence_target_subnet_name" {
  description = "Name of the isolated development OHL scale-out evidence subnet."
  value       = length(azurerm_subnet.evidence_target) > 0 ? azurerm_subnet.evidence_target[0].name : null
}

output "evidence_target_subnet_prefix" {
  description = "CIDR of the isolated development OHL scale-out evidence subnet."
  value       = var.enable_evidence_target_subnet ? var.evidence_target_subnet_prefix : null
}

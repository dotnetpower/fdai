output "private_endpoint_id" {
  value = azurerm_private_endpoint.this.id
}

output "private_dns_zone_id" {
  value = azurerm_private_dns_zone.this.id
}

output "private_ip_address" {
  description = "The PE NIC's private IP (first ip configuration)."
  value       = azurerm_private_endpoint.this.private_service_connection[0].private_ip_address
}

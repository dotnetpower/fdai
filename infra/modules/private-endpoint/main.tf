# Generic private-endpoint module - one PE + its private DNS zone + a VNet
# link + the zone group that auto-registers the PE's A record.
#
# Reusable across services: each service type passes its own
# `subresource_name` ("vault", "registry", "namespace", "postgresqlServer")
# and `private_dns_zone_name` (privatelink.vaultcore.azure.net,
# privatelink.azurecr.io, privatelink.servicebus.windows.net,
# privatelink.postgres.database.azure.com). Distinct zone names mean two PE
# module instances never collide on the zone resource.
#
# Design: docs/roadmap/deployment/deploy-and-onboard.md (private-networking layer).

resource "azurerm_private_dns_zone" "this" {
  name                = var.private_dns_zone_name
  resource_group_name = var.resource_group_name
  tags                = var.tags

  # Some tenant policies normalize Private DNS tags after writes. The zone's
  # security boundary is its links and records, so tag churn is non-functional.
  lifecycle {
    ignore_changes = [tags]
  }
}

resource "azurerm_private_dns_zone_virtual_network_link" "this" {
  name                  = "${var.name}-link"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.this.name
  virtual_network_id    = var.vnet_id
  registration_enabled  = false
  tags                  = var.tags

  lifecycle {
    ignore_changes = [tags]
  }
}

# Additional VNet links (e.g. a peered ops/hub VNet) so a runner outside the
# app VNet resolves this private endpoint. Keyed by a stable link name.
resource "azurerm_private_dns_zone_virtual_network_link" "extra" {
  for_each              = var.extra_vnet_links
  name                  = "${var.name}-${each.key}-link"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.this.name
  virtual_network_id    = each.value
  registration_enabled  = false
  tags                  = var.tags

  lifecycle {
    ignore_changes = [tags]
  }
}

resource "azurerm_private_endpoint" "this" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.subnet_id
  tags                = var.tags

  private_service_connection {
    name                           = "${var.name}-psc"
    private_connection_resource_id = var.target_resource_id
    subresource_names              = [var.subresource_name]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.this.id]
  }
}

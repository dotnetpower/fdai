locals {
  kinds = toset([var.kind])
  tags  = var.tags
}

resource "azurerm_resource_group" "hub" {
  for_each = local.kinds
  name     = coalesce(var.resource_group_name, "rg-${var.prefix}-${each.key}")
  location = var.location
  tags     = local.tags
}
resource "azurerm_virtual_network" "hub" {
  for_each            = local.kinds
  name                = "vnet-${var.prefix}-${each.key}"
  location            = var.location
  resource_group_name = azurerm_resource_group.hub[each.key].name
  address_space       = [var.network.vnet]
}
resource "azurerm_subnet" "apps" {
  # checkov:skip=CKV2_AZURE_31:ACA owns this delegated subnet; explicit NAT provides egress and default outbound access is disabled.
  for_each                        = local.kinds
  name                            = "apps"
  resource_group_name             = azurerm_resource_group.hub[each.key].name
  virtual_network_name            = azurerm_virtual_network.hub[each.key].name
  address_prefixes                = [var.network.apps]
  default_outbound_access_enabled = false
  delegation {
    name = "aca"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}
resource "azurerm_subnet" "database" {
  # checkov:skip=CKV2_AZURE_31:PostgreSQL owns this delegated private subnet; default outbound access is disabled.
  for_each                        = local.kinds
  name                            = "database"
  resource_group_name             = azurerm_resource_group.hub[each.key].name
  virtual_network_name            = azurerm_virtual_network.hub[each.key].name
  address_prefixes                = [var.network.database]
  default_outbound_access_enabled = false
  service_endpoints               = ["Microsoft.Storage"]
  delegation {
    name = "postgres"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}
resource "azurerm_subnet" "secrets" {
  # checkov:skip=CKV2_AZURE_31:Only private-endpoint NICs use this subnet; endpoint network policies and default outbound access are disabled.
  for_each                          = local.kinds
  name                              = "secrets"
  resource_group_name               = azurerm_resource_group.hub[each.key].name
  virtual_network_name              = azurerm_virtual_network.hub[each.key].name
  address_prefixes                  = [var.network.secrets]
  default_outbound_access_enabled   = false
  private_endpoint_network_policies = "Disabled"
}
resource "azurerm_public_ip" "egress" {
  for_each            = local.kinds
  name                = "pip-${var.prefix}-${each.key}"
  location            = var.location
  resource_group_name = azurerm_resource_group.hub[each.key].name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = {}
  zones               = []
  ip_tags             = {}
  lifecycle {
    # Preserve only Azure's routing marker, not arbitrary operator IP tags.
    ignore_changes = [ip_tags["FirstPartyUsage"]]
  }
}
resource "azurerm_nat_gateway" "hub" {
  for_each            = local.kinds
  name                = "nat-${var.prefix}-${each.key}"
  location            = var.location
  resource_group_name = azurerm_resource_group.hub[each.key].name
  sku_name            = "Standard"
}
resource "azurerm_nat_gateway_public_ip_association" "hub" {
  for_each             = local.kinds
  nat_gateway_id       = azurerm_nat_gateway.hub[each.key].id
  public_ip_address_id = azurerm_public_ip.egress[each.key].id
}
resource "azurerm_subnet_nat_gateway_association" "hub" {
  for_each       = local.kinds
  subnet_id      = azurerm_subnet.apps[each.key].id
  nat_gateway_id = azurerm_nat_gateway.hub[each.key].id
}
resource "azurerm_log_analytics_workspace" "hub" {
  for_each            = local.kinds
  name                = "log-${var.prefix}-${each.key}"
  location            = var.location
  resource_group_name = azurerm_resource_group.hub[each.key].name
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days
}
resource "azurerm_container_app_environment" "hub" {
  for_each                   = local.kinds
  name                       = "cae-${var.prefix}-${each.key}"
  location                   = var.location
  resource_group_name        = azurerm_resource_group.hub[each.key].name
  infrastructure_subnet_id   = azurerm_subnet.apps[each.key].id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.hub[each.key].id
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}
resource "azurerm_user_assigned_identity" "hub" {
  for_each            = local.kinds
  name                = "id-${var.prefix}-${each.key}"
  location            = var.location
  resource_group_name = azurerm_resource_group.hub[each.key].name
}
resource "azurerm_key_vault" "hub" {
  # checkov:skip=CKV2_AZURE_32:Checkov 3.2.256 misses the for_each graph edge; azurerm_private_endpoint.vault connects each vault only to its own Hub subnet and DNS.
  for_each                      = local.kinds
  name                          = "kv-${var.prefix}-${each.key}"
  location                      = var.location
  resource_group_name           = azurerm_resource_group.hub[each.key].name
  tenant_id                     = var.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  public_network_access_enabled = false
  purge_protection_enabled      = true
  soft_delete_retention_days    = 7
  network_acls {
    default_action = "Deny"
    bypass         = "None"
  }
}
resource "azurerm_private_dns_zone" "vault" {
  for_each            = local.kinds
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = azurerm_resource_group.hub[each.key].name
}
resource "azurerm_private_dns_zone_virtual_network_link" "vault" {
  for_each              = local.kinds
  name                  = "own-hub"
  resource_group_name   = azurerm_resource_group.hub[each.key].name
  private_dns_zone_name = azurerm_private_dns_zone.vault[each.key].name
  virtual_network_id    = azurerm_virtual_network.hub[each.key].id
}
resource "azurerm_private_endpoint" "vault" {
  for_each            = local.kinds
  name                = "pe-${var.prefix}-${each.key}-vault"
  location            = var.location
  resource_group_name = azurerm_resource_group.hub[each.key].name
  subnet_id           = azurerm_subnet.secrets[each.key].id
  private_service_connection {
    name                           = "vault"
    private_connection_resource_id = azurerm_key_vault.hub[each.key].id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "vault"
    private_dns_zone_ids = [azurerm_private_dns_zone.vault[each.key].id]
  }
}
resource "azurerm_private_dns_zone" "database" {
  for_each            = local.kinds
  name                = "${each.key}.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.hub[each.key].name
}
resource "azurerm_private_dns_zone_virtual_network_link" "database" {
  for_each              = local.kinds
  name                  = "own-hub"
  resource_group_name   = azurerm_resource_group.hub[each.key].name
  private_dns_zone_name = azurerm_private_dns_zone.database[each.key].name
  virtual_network_id    = azurerm_virtual_network.hub[each.key].id
}
# Trivy reads retired server fields for these checks, not Flexible Server parameters.
# The configuration resources below enforce connection throttling and TLS 1.2.
#trivy:ignore:AZU-0021
#trivy:ignore:AZU-0026
resource "azurerm_postgresql_flexible_server" "hub" {
  # checkov:skip=CKV_AZURE_136:This development-only single-region root retains seven-day local backups; it is not a production disaster-recovery profile.
  for_each                      = local.kinds
  name                          = "psql-${var.prefix}-${each.key}"
  location                      = var.location
  resource_group_name           = azurerm_resource_group.hub[each.key].name
  version                       = "16"
  delegated_subnet_id           = azurerm_subnet.database[each.key].id
  private_dns_zone_id           = azurerm_private_dns_zone.database[each.key].id
  public_network_access_enabled = false
  sku_name                      = var.database.sku_name
  storage_mb                    = var.database.storage_mb
  backup_retention_days         = var.database.backup_retention_days
  geo_redundant_backup_enabled  = var.database.geo_redundant_backup_enabled
  dynamic "high_availability" {
    for_each = var.database.zone_redundant ? [1] : []
    content {
      mode = "ZoneRedundant"
    }
  }
  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = false
    tenant_id                     = var.tenant_id
  }
  lifecycle {
    # Preserve the zone Azure selected at initial creation.
    ignore_changes = [zone]
  }
  depends_on = [azurerm_private_dns_zone_virtual_network_link.database]
}
resource "azurerm_postgresql_flexible_server_active_directory_administrator" "hub" {
  for_each            = local.kinds
  server_name         = azurerm_postgresql_flexible_server.hub[each.key].name
  resource_group_name = azurerm_resource_group.hub[each.key].name
  tenant_id           = var.tenant_id
  object_id           = var.database_admin.object_id
  principal_name      = var.database_admin.display_name
  principal_type      = "User"
}
resource "azurerm_postgresql_flexible_server_database" "hub" {
  for_each  = local.kinds
  name      = "${each.key}_hub"
  server_id = azurerm_postgresql_flexible_server.hub[each.key].id
  charset   = "UTF8"
  collation = "en_US.utf8"
  depends_on = [
    azurerm_postgresql_flexible_server_active_directory_administrator.hub,
  ]
}

resource "azurerm_postgresql_flexible_server_configuration" "log_connections" {
  for_each  = local.kinds
  name      = "log_connections"
  server_id = azurerm_postgresql_flexible_server.hub[each.key].id
  value     = "on"
}
resource "azurerm_postgresql_flexible_server_configuration" "log_checkpoints" {
  for_each  = local.kinds
  name      = "log_checkpoints"
  server_id = azurerm_postgresql_flexible_server.hub[each.key].id
  value     = "on"
}
resource "azurerm_postgresql_flexible_server_configuration" "connection_throttle" {
  for_each  = local.kinds
  name      = "connection_throttle.enable"
  server_id = azurerm_postgresql_flexible_server.hub[each.key].id
  value     = "on"
}
resource "azurerm_postgresql_flexible_server_configuration" "tls_floor" {
  for_each  = local.kinds
  name      = "ssl_min_protocol_version"
  server_id = azurerm_postgresql_flexible_server.hub[each.key].id
  value     = "TLSv1.2"
}

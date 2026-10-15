locals {
  kinds = toset(["release", "target"])
  tags  = { purpose = "hub-development-validation", production = "false" }
}

resource "azurerm_resource_group" "hub" {
  for_each = local.kinds
  name     = "rg-${var.prefix}-${each.key}"
  location = var.location
  tags     = local.tags
}
resource "azurerm_virtual_network" "hub" {
  for_each            = local.kinds
  name                = "vnet-${var.prefix}-${each.key}"
  location            = var.location
  resource_group_name = azurerm_resource_group.hub[each.key].name
  address_space       = [each.key == "release" ? "10.120.0.0/16" : "10.121.0.0/16"]
}
resource "azurerm_subnet" "apps" {
  for_each             = local.kinds
  name                 = "apps"
  resource_group_name  = azurerm_resource_group.hub[each.key].name
  virtual_network_name = azurerm_virtual_network.hub[each.key].name
  address_prefixes     = [each.key == "release" ? "10.120.0.0/23" : "10.121.0.0/23"]
  delegation {
    name = "aca"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}
resource "azurerm_subnet" "database" {
  for_each             = local.kinds
  name                 = "database"
  resource_group_name  = azurerm_resource_group.hub[each.key].name
  virtual_network_name = azurerm_virtual_network.hub[each.key].name
  address_prefixes     = [each.key == "release" ? "10.120.2.0/24" : "10.121.2.0/24"]
  delegation {
    name = "postgres"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}
resource "azurerm_subnet" "secrets" {
  for_each             = local.kinds
  name                 = "secrets"
  resource_group_name  = azurerm_resource_group.hub[each.key].name
  virtual_network_name = azurerm_virtual_network.hub[each.key].name
  address_prefixes     = [each.key == "release" ? "10.120.3.0/24" : "10.121.3.0/24"]
}
resource "azurerm_public_ip" "egress" {
  for_each            = local.kinds
  name                = "pip-${var.prefix}-${each.key}"
  location            = var.location
  resource_group_name = azurerm_resource_group.hub[each.key].name
  allocation_method   = "Static"
  sku                 = "Standard"
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
  retention_in_days   = 30
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
resource "azurerm_postgresql_flexible_server" "hub" {
  for_each                      = local.kinds
  name                          = "psql-${var.prefix}-${each.key}"
  location                      = var.location
  resource_group_name           = azurerm_resource_group.hub[each.key].name
  version                       = "16"
  delegated_subnet_id           = azurerm_subnet.database[each.key].id
  private_dns_zone_id           = azurerm_private_dns_zone.database[each.key].id
  public_network_access_enabled = false
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  backup_retention_days         = 7
  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = false
    tenant_id                     = var.tenant_id
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
}

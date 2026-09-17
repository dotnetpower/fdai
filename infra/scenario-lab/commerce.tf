resource "azurerm_user_assigned_identity" "commerce" {
  count = var.commerce_enabled ? 1 : 0

  name                = "id-${local.suffix}-commerce"
  location            = data.azurerm_resource_group.scenario_lab.location
  resource_group_name = data.azurerm_resource_group.scenario_lab.name
  tags                = local.tags
}

resource "azurerm_servicebus_namespace" "commerce" {
  count = var.commerce_enabled ? 1 : 0

  name                          = "sb-${local.suffix}-${local.unique_suffix}"
  location                      = data.azurerm_resource_group.scenario_lab.location
  resource_group_name           = data.azurerm_resource_group.scenario_lab.name
  sku                           = "Standard"
  local_auth_enabled            = false
  minimum_tls_version           = "1.2"
  public_network_access_enabled = false
  tags                          = local.tags
}

resource "azurerm_servicebus_queue" "orders" {
  count = var.commerce_enabled ? 1 : 0

  name         = "orders"
  namespace_id = azurerm_servicebus_namespace.commerce[0].id
}

resource "azurerm_role_assignment" "commerce_servicebus_sender" {
  count = var.commerce_enabled ? 1 : 0

  scope                = azurerm_servicebus_namespace.commerce[0].id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = azurerm_user_assigned_identity.commerce[0].principal_id
}

resource "azurerm_role_assignment" "commerce_servicebus_receiver" {
  count = var.commerce_enabled ? 1 : 0

  scope                = azurerm_servicebus_namespace.commerce[0].id
  role_definition_name = "Azure Service Bus Data Receiver"
  principal_id         = azurerm_user_assigned_identity.commerce[0].principal_id
}

resource "azurerm_private_dns_zone" "commerce_servicebus" {
  count = var.commerce_enabled ? 1 : 0

  name                = "privatelink.servicebus.windows.net"
  resource_group_name = data.azurerm_resource_group.scenario_lab.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "commerce_servicebus" {
  count = var.commerce_enabled ? 1 : 0

  name                  = "link-${local.suffix}-commerce-servicebus"
  resource_group_name   = data.azurerm_resource_group.scenario_lab.name
  private_dns_zone_name = azurerm_private_dns_zone.commerce_servicebus[0].name
  virtual_network_id    = azurerm_virtual_network.scenario_lab.id
  registration_enabled  = false
  tags                  = local.tags
}

resource "azurerm_private_endpoint" "commerce_servicebus" {
  count = var.commerce_enabled ? 1 : 0

  name                = "pe-${local.suffix}-commerce-servicebus"
  location            = data.azurerm_resource_group.scenario_lab.location
  resource_group_name = data.azurerm_resource_group.scenario_lab.name
  subnet_id           = azurerm_subnet.private_endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "pe-${local.suffix}-commerce-servicebus-psc"
    private_connection_resource_id = azurerm_servicebus_namespace.commerce[0].id
    subresource_names              = ["namespace"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.commerce_servicebus[0].id]
  }
}

resource "azurerm_cosmosdb_account" "commerce" {
  count = var.commerce_enabled ? 1 : 0

  name                          = "cosmos-${local.suffix}-${local.unique_suffix}"
  location                      = data.azurerm_resource_group.scenario_lab.location
  resource_group_name           = data.azurerm_resource_group.scenario_lab.name
  offer_type                    = "Standard"
  kind                          = "GlobalDocumentDB"
  local_authentication_enabled  = false
  minimal_tls_version           = "Tls12"
  public_network_access_enabled = false
  tags                          = local.tags

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = data.azurerm_resource_group.scenario_lab.location
    failover_priority = 0
  }
}

resource "azurerm_cosmosdb_sql_database" "commerce" {
  count = var.commerce_enabled ? 1 : 0

  name                = "orderdb"
  resource_group_name = data.azurerm_resource_group.scenario_lab.name
  account_name        = azurerm_cosmosdb_account.commerce[0].name
  throughput          = 400
}

resource "azurerm_cosmosdb_sql_container" "orders" {
  count = var.commerce_enabled ? 1 : 0

  name                  = "orders"
  resource_group_name   = data.azurerm_resource_group.scenario_lab.name
  account_name          = azurerm_cosmosdb_account.commerce[0].name
  database_name         = azurerm_cosmosdb_sql_database.commerce[0].name
  partition_key_paths   = ["/storeId"]
  partition_key_version = 2
}

resource "azurerm_cosmosdb_sql_role_definition" "commerce" {
  count = var.commerce_enabled ? 1 : 0

  name                = "CommerceDataContributor"
  resource_group_name = data.azurerm_resource_group.scenario_lab.name
  account_name        = azurerm_cosmosdb_account.commerce[0].name
  type                = "CustomRole"
  assignable_scopes   = [azurerm_cosmosdb_account.commerce[0].id]

  permissions {
    data_actions = [
      "Microsoft.DocumentDB/databaseAccounts/readMetadata",
      "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/*",
      "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/*",
    ]
  }
}

resource "azurerm_cosmosdb_sql_role_assignment" "commerce" {
  count = var.commerce_enabled ? 1 : 0

  resource_group_name = data.azurerm_resource_group.scenario_lab.name
  account_name        = azurerm_cosmosdb_account.commerce[0].name
  role_definition_id  = azurerm_cosmosdb_sql_role_definition.commerce[0].id
  principal_id        = azurerm_user_assigned_identity.commerce[0].principal_id
  scope               = azurerm_cosmosdb_account.commerce[0].id
}

resource "azurerm_private_dns_zone" "commerce_cosmos" {
  count = var.commerce_enabled ? 1 : 0

  name                = "privatelink.documents.azure.com"
  resource_group_name = data.azurerm_resource_group.scenario_lab.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "commerce_cosmos" {
  count = var.commerce_enabled ? 1 : 0

  name                  = "link-${local.suffix}-commerce-cosmos"
  resource_group_name   = data.azurerm_resource_group.scenario_lab.name
  private_dns_zone_name = azurerm_private_dns_zone.commerce_cosmos[0].name
  virtual_network_id    = azurerm_virtual_network.scenario_lab.id
  registration_enabled  = false
  tags                  = local.tags
}

resource "azurerm_private_endpoint" "commerce_cosmos" {
  count = var.commerce_enabled ? 1 : 0

  name                = "pe-${local.suffix}-commerce-cosmos"
  location            = data.azurerm_resource_group.scenario_lab.location
  resource_group_name = data.azurerm_resource_group.scenario_lab.name
  subnet_id           = azurerm_subnet.private_endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "pe-${local.suffix}-commerce-cosmos-psc"
    private_connection_resource_id = azurerm_cosmosdb_account.commerce[0].id
    subresource_names              = ["Sql"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.commerce_cosmos[0].id]
  }
}

resource "azurerm_federated_identity_credential" "commerce_workloads" {
  count = var.commerce_enabled ? 1 : 0

  name                = "aks-store-demo"
  resource_group_name = data.azurerm_resource_group.scenario_lab.name
  parent_id           = azurerm_user_assigned_identity.commerce[0].id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.scenario_lab.oidc_issuer_url
  subject             = "system:serviceaccount:${var.commerce_namespace}:aks-store-demo"
}

resource "azurerm_monitor_diagnostic_setting" "commerce_servicebus" {
  count = var.commerce_enabled ? 1 : 0

  name                       = "diag-${local.suffix}-commerce-servicebus"
  target_resource_id         = azurerm_servicebus_namespace.commerce[0].id
  log_analytics_workspace_id = module.log_analytics.workspace_id

  enabled_log {
    category_group = "allLogs"
  }

  enabled_metric {
    category = "AllMetrics"
  }
}

resource "azurerm_monitor_diagnostic_setting" "commerce_cosmos" {
  count = var.commerce_enabled ? 1 : 0

  name                       = "diag-${local.suffix}-commerce-cosmos"
  target_resource_id         = azurerm_cosmosdb_account.commerce[0].id
  log_analytics_workspace_id = module.log_analytics.workspace_id

  enabled_log {
    category_group = "allLogs"
  }

  enabled_metric {
    category = "Requests"
  }
}

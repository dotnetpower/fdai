resource "random_password" "mysql_admin" {
  length           = 32
  special          = true
  override_special = "!#$%&*+-.:=?@_"
}

resource "terraform_data" "data_services_prerequisites" {
  count = var.data_services_enabled ? 1 : 0

  lifecycle {
    precondition {
      condition = (
        var.runner_vnet != null &&
        startswith(var.azure_openai_private_dns_zone.id, "/subscriptions/") &&
        trimspace(var.azure_openai_private_dns_zone.resource_group_name) != ""
      )
      error_message = "data_services_enabled requires runner_vnet and azure_openai_private_dns_zone."
    }
  }
}

resource "azurerm_private_dns_zone" "mysql" {
  count = var.data_services_enabled ? 1 : 0

  name                = "${local.unique_suffix}.mysql.database.azure.com"
  resource_group_name = data.azurerm_resource_group.scenario_lab.name
  tags                = local.tags

  lifecycle {
    ignore_changes = [tags]
  }
}

resource "azurerm_private_dns_zone_virtual_network_link" "mysql_lab" {
  count = var.data_services_enabled ? 1 : 0

  name                  = "link-${local.suffix}-mysql"
  resource_group_name   = data.azurerm_resource_group.scenario_lab.name
  private_dns_zone_name = azurerm_private_dns_zone.mysql[0].name
  virtual_network_id    = azurerm_virtual_network.scenario_lab.id
  registration_enabled  = false
  tags                  = local.tags

  lifecycle {
    ignore_changes = [tags]
  }
}

resource "azurerm_private_dns_zone_virtual_network_link" "mysql_runner" {
  count = var.data_services_enabled && local.runner_peering_enabled ? 1 : 0

  name                  = "link-runner-mysql"
  resource_group_name   = data.azurerm_resource_group.scenario_lab.name
  private_dns_zone_name = azurerm_private_dns_zone.mysql[0].name
  virtual_network_id    = var.runner_vnet.id
  registration_enabled  = false
  tags                  = local.tags

  lifecycle {
    ignore_changes = [tags]
  }
}

resource "azurerm_private_dns_zone_virtual_network_link" "mysql_operator" {
  count = var.data_services_enabled && local.operator_enabled ? 1 : 0

  name                  = "link-operator-mysql"
  resource_group_name   = data.azurerm_resource_group.scenario_lab.name
  private_dns_zone_name = azurerm_private_dns_zone.mysql[0].name
  virtual_network_id    = var.operator_access.vnet_id
  registration_enabled  = false
  tags                  = local.tags

  lifecycle {
    ignore_changes = [tags]
  }
}

# A delegated subnet makes public access provider-computed false. TLS is enforced by the two
# azurerm_mysql_flexible_server_configuration resources below. Trivy inspects only this block.
#trivy:ignore:AZU-0022
#trivy:ignore:AZU-0026
resource "azurerm_mysql_flexible_server" "scenario_lab" {
  # checkov:skip=CKV_AZURE_94:Geo-redundant backup is outside the short-lived fault target and its explicit destroy boundary.
  count = var.data_services_enabled ? 1 : 0

  name                         = "mysql-fdai-sre-${local.unique_suffix}"
  location                     = data.azurerm_resource_group.scenario_lab.location
  resource_group_name          = data.azurerm_resource_group.scenario_lab.name
  administrator_login          = var.mysql_admin_login
  administrator_password       = random_password.mysql_admin.result
  backup_retention_days        = 7
  delegated_subnet_id          = azurerm_subnet.mysql.id
  private_dns_zone_id          = azurerm_private_dns_zone.mysql[0].id
  geo_redundant_backup_enabled = false
  sku_name                     = var.mysql_sku_name
  version                      = var.mysql_version
  tags                         = local.tags

  storage {
    auto_grow_enabled = true
    size_gb           = 32
  }

  depends_on = [
    terraform_data.data_services_prerequisites,
    azurerm_private_dns_zone_virtual_network_link.mysql_lab,
  ]
}

resource "azurerm_mysql_flexible_server_configuration" "require_secure_transport" {
  count = var.data_services_enabled ? 1 : 0

  name                = "require_secure_transport"
  resource_group_name = data.azurerm_resource_group.scenario_lab.name
  server_name         = azurerm_mysql_flexible_server.scenario_lab[0].name
  value               = "ON"
}

resource "azurerm_mysql_flexible_server_configuration" "tls_version" {
  count = var.data_services_enabled ? 1 : 0

  name                = "tls_version"
  resource_group_name = data.azurerm_resource_group.scenario_lab.name
  server_name         = azurerm_mysql_flexible_server.scenario_lab[0].name
  value               = "TLSv1.2"
}

module "azure_openai" {
  # checkov:skip=CKV_AZURE_238:The shared private account uses Entra callers directly and needs no resource identity in this lab.
  # checkov:skip=CKV2_AZURE_22:CMK infrastructure would outlive the disposable model-throttle target.
  count  = var.data_services_enabled ? 1 : 0
  source = "../modules/llm/azure-openai"

  name                  = "oai-fdai-sre-${local.unique_suffix}"
  location              = data.azurerm_resource_group.scenario_lab.location
  resource_group_name   = data.azurerm_resource_group.scenario_lab.name
  executor_principal_id = var.deploy_runner_principal_id
  grant_executor_role   = true
  additional_user_principal_ids = local.operator_enabled ? {
    operator = var.operator_access.principal_id
  } : {}
  resolved_capabilities = [{
    name           = var.azure_openai_deployment_name
    family         = var.azure_openai_model_family
    version        = var.azure_openai_model_version
    sku            = var.azure_openai_deployment_sku
    capacity_tpm   = var.azure_openai_capacity_tpm
    capacity_unit  = "tpm"
    capacity_value = 0
  }]
  tags = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "openai_lab" {
  count = var.data_services_enabled ? 1 : 0

  name                  = "link-${local.suffix}-openai"
  resource_group_name   = var.azure_openai_private_dns_zone.resource_group_name
  private_dns_zone_name = var.azure_openai_private_dns_zone.name
  virtual_network_id    = azurerm_virtual_network.scenario_lab.id
  registration_enabled  = false
  tags                  = local.tags

  lifecycle {
    ignore_changes = [tags]
  }
}

resource "azurerm_private_endpoint" "azure_openai" {
  count = var.data_services_enabled ? 1 : 0

  name                = "pe-${local.suffix}-oai"
  location            = data.azurerm_resource_group.scenario_lab.location
  resource_group_name = data.azurerm_resource_group.scenario_lab.name
  subnet_id           = azurerm_subnet.private_endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "pe-${local.suffix}-oai-psc"
    private_connection_resource_id = module.azure_openai[0].resource_id
    subresource_names              = ["account"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [var.azure_openai_private_dns_zone.id]
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.openai_lab]
}

resource "azurerm_monitor_diagnostic_setting" "mysql" {
  count = var.data_services_enabled ? 1 : 0

  name                       = "diag-${local.suffix}-mysql"
  target_resource_id         = azurerm_mysql_flexible_server.scenario_lab[0].id
  log_analytics_workspace_id = module.log_analytics.workspace_id

  enabled_metric {
    category = "AllMetrics"
  }
}

resource "azurerm_monitor_diagnostic_setting" "azure_openai" {
  count = var.data_services_enabled ? 1 : 0

  name                       = "diag-${local.suffix}-oai"
  target_resource_id         = module.azure_openai[0].resource_id
  log_analytics_workspace_id = module.log_analytics.workspace_id

  enabled_metric {
    category = "AllMetrics"
  }
}

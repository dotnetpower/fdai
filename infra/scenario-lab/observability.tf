module "log_analytics" {
  source = "../modules/observability/log-analytics"

  name                = "log-${local.suffix}"
  location            = azurerm_resource_group.scenario_lab.location
  resource_group_name = azurerm_resource_group.scenario_lab.name
  retention_days      = 30
  daily_quota_gb      = 1
  tags                = local.tags
}

resource "azurerm_application_insights" "scenario_lab" {
  name                = "appi-${local.suffix}"
  location            = azurerm_resource_group.scenario_lab.location
  resource_group_name = azurerm_resource_group.scenario_lab.name
  workspace_id        = module.log_analytics.workspace_id
  application_type    = "web"
  retention_in_days   = 30
  tags                = local.tags
}

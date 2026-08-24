data "azurerm_client_config" "current" {}

locals {
  suffix           = "fdai-sre-${var.environment}-${var.region_short}"
  unique_suffix    = substr(sha1("${data.azurerm_client_config.current.subscription_id}:${var.environment}:${var.region}"), 0, 6)
  operator_enabled = var.operator_access != null
  tags = merge({
    "fdai:managed"    = "true"
    "fdai:workload"   = "fdai"
    "fdai:env"        = var.environment
    "fdai:layer"      = "scenario-lab"
    "fdai:managed-by" = "terraform"
    "fdai:ephemeral"  = "true"
    "fdai:expires-at" = var.expires_at_utc
  }, var.additional_tags)
}

data "azurerm_resource_group" "scenario_lab" {
  name = var.resource_group_name
}

resource "azurerm_user_assigned_identity" "aks" {
  name                = "id-${local.suffix}-aks"
  location            = data.azurerm_resource_group.scenario_lab.location
  resource_group_name = data.azurerm_resource_group.scenario_lab.name
  tags                = local.tags
}

resource "azurerm_virtual_network_peering" "lab_to_runner" {
  name                         = "peer-${local.suffix}-to-runner"
  resource_group_name          = data.azurerm_resource_group.scenario_lab.name
  virtual_network_name         = azurerm_virtual_network.scenario_lab.name
  remote_virtual_network_id    = var.runner_vnet.id
  allow_virtual_network_access = true
  allow_forwarded_traffic      = true
}

resource "azurerm_virtual_network_peering" "runner_to_lab" {
  name                         = "peer-runner-to-${local.suffix}"
  resource_group_name          = var.runner_vnet.resource_group_name
  virtual_network_name         = var.runner_vnet.name
  remote_virtual_network_id    = azurerm_virtual_network.scenario_lab.id
  allow_virtual_network_access = true
  allow_forwarded_traffic      = true
}

resource "azurerm_virtual_network_peering" "lab_to_operator" {
  count = local.operator_enabled ? 1 : 0

  name                         = "peer-${local.suffix}-to-operator"
  resource_group_name          = data.azurerm_resource_group.scenario_lab.name
  virtual_network_name         = azurerm_virtual_network.scenario_lab.name
  remote_virtual_network_id    = var.operator_access.vnet_id
  allow_virtual_network_access = true
  allow_forwarded_traffic      = true
  use_remote_gateways          = true
}

resource "azurerm_virtual_network_peering" "operator_to_lab" {
  count = local.operator_enabled ? 1 : 0

  name                         = "peer-operator-to-${local.suffix}"
  resource_group_name          = var.operator_access.vnet_resource_group_name
  virtual_network_name         = var.operator_access.vnet_name
  remote_virtual_network_id    = azurerm_virtual_network.scenario_lab.id
  allow_virtual_network_access = true
  allow_forwarded_traffic      = true
  allow_gateway_transit        = true
}

resource "azurerm_role_assignment" "operator_monitoring_reader" {
  count = local.operator_enabled ? 1 : 0

  scope                = data.azurerm_resource_group.scenario_lab.id
  role_definition_name = "Monitoring Reader"
  principal_id         = var.operator_access.principal_id
}

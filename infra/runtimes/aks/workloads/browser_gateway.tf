locals {
  browser_gateway_enabled = try(var.browser_gateway.enabled, false)
  browser_gateway_name = local.browser_gateway_enabled ? format(
    "apim-%s-%s-%s-%s",
    var.browser_gateway.workload,
    var.browser_gateway.environment,
    var.browser_gateway.region_short,
    var.browser_gateway.resource_name_suffix,
  ) : "apim-fdai-disabled-placeholder"
  browser_gateway_addresses = local.browser_gateway_enabled ? {
    for service_name in ["operator-service", "document-ingestion-api"] : service_name => coalesce(
      try(kubernetes_service_v1.workload[service_name].status[0].load_balancer[0].ingress[0].ip, null),
      try(kubernetes_service_v1.workload[service_name].status[0].load_balancer[0].ingress[0].hostname, null),
    )
  } : {}
}

module "browser_gateway" {
  source = "../../../modules/console/browser-gateway"

  enabled             = local.browser_gateway_enabled
  name                = local.browser_gateway_name
  location            = try(var.browser_gateway.location, "disabled")
  resource_group_name = try(var.browser_gateway.resource_group_name, "disabled")
  publisher_name      = try(var.browser_gateway.publisher_name, "FDAI")
  publisher_email     = try(var.browser_gateway.publisher_email, "operator@example.com")
  frontend_tenant_id  = var.tenant_id
  frontend_audience = local.browser_gateway_enabled ? (
    var.workloads["operator-service"].environment["FDAI_API_AUDIENCE"]
  ) : "00000000-0000-0000-0000-000000000000"
  console_origin = local.browser_gateway_enabled ? (
    var.workloads["operator-service"].environment["FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS"]
  ) : "https://disabled.example.com"
  operator_backend_url = local.browser_gateway_enabled ? (
    "http://${local.browser_gateway_addresses["operator-service"]}"
  ) : "https://disabled.example.com"
  ingestion_backend_url = local.browser_gateway_enabled ? (
    "http://${local.browser_gateway_addresses["document-ingestion-api"]}"
  ) : "https://disabled.example.com"
  backend_nsg_id = local.browser_gateway_enabled ? var.browser_gateway.backend_nsg_id : ""
  backend_nsg_destination_addresses = local.browser_gateway_enabled ? [
    local.browser_gateway_addresses["document-ingestion-api"],
    local.browser_gateway_addresses["operator-service"],
  ] : []
  tags = var.tags
}

moved {
  from = azurerm_api_management.browser_gateway[0]
  to   = module.browser_gateway.azurerm_api_management.browser_gateway[0]
}

moved {
  from = azurerm_api_management_api.browser_gateway["operator"]
  to   = module.browser_gateway.azurerm_api_management_api.browser_gateway["operator"]
}

moved {
  from = azurerm_api_management_api.browser_gateway["ingestion"]
  to   = module.browser_gateway.azurerm_api_management_api.browser_gateway["ingestion"]
}

moved {
  from = azurerm_api_management_api_policy.browser_gateway_ingestion[0]
  to   = module.browser_gateway.azurerm_api_management_api_policy.browser_gateway_ingestion[0]
}

moved {
  from = azurerm_api_management_api_policy.browser_gateway_documents[0]
  to   = module.browser_gateway.azurerm_api_management_api_policy.browser_gateway_documents[0]
}

moved {
  from = azurerm_network_security_rule.browser_gateway[0]
  to   = module.browser_gateway.azurerm_network_security_rule.browser_gateway[0]
}

moved {
  from = azurerm_api_management_api_operation.browser_gateway["operator-delete"]
  to   = module.browser_gateway.azurerm_api_management_api_operation.browser_gateway["operator-delete"]
}

moved {
  from = azurerm_api_management_api_operation.browser_gateway["operator-get"]
  to   = module.browser_gateway.azurerm_api_management_api_operation.browser_gateway["operator-get"]
}

moved {
  from = azurerm_api_management_api_operation.browser_gateway["operator-head"]
  to   = module.browser_gateway.azurerm_api_management_api_operation.browser_gateway["operator-head"]
}

moved {
  from = azurerm_api_management_api_operation.browser_gateway["operator-options"]
  to   = module.browser_gateway.azurerm_api_management_api_operation.browser_gateway["operator-options"]
}

moved {
  from = azurerm_api_management_api_operation.browser_gateway["operator-patch"]
  to   = module.browser_gateway.azurerm_api_management_api_operation.browser_gateway["operator-patch"]
}

moved {
  from = azurerm_api_management_api_operation.browser_gateway["operator-post"]
  to   = module.browser_gateway.azurerm_api_management_api_operation.browser_gateway["operator-post"]
}

moved {
  from = azurerm_api_management_api_operation.browser_gateway["operator-put"]
  to   = module.browser_gateway.azurerm_api_management_api_operation.browser_gateway["operator-put"]
}

moved {
  from = azurerm_api_management_api_operation.browser_gateway["ingestion-delete"]
  to   = module.browser_gateway.azurerm_api_management_api_operation.browser_gateway["ingestion-delete"]
}

moved {
  from = azurerm_api_management_api_operation.browser_gateway["ingestion-get"]
  to   = module.browser_gateway.azurerm_api_management_api_operation.browser_gateway["ingestion-get"]
}

moved {
  from = azurerm_api_management_api_operation.browser_gateway["ingestion-head"]
  to   = module.browser_gateway.azurerm_api_management_api_operation.browser_gateway["ingestion-head"]
}

moved {
  from = azurerm_api_management_api_operation.browser_gateway["ingestion-options"]
  to   = module.browser_gateway.azurerm_api_management_api_operation.browser_gateway["ingestion-options"]
}

moved {
  from = azurerm_api_management_api_operation.browser_gateway["ingestion-patch"]
  to   = module.browser_gateway.azurerm_api_management_api_operation.browser_gateway["ingestion-patch"]
}

moved {
  from = azurerm_api_management_api_operation.browser_gateway["ingestion-post"]
  to   = module.browser_gateway.azurerm_api_management_api_operation.browser_gateway["ingestion-post"]
}

moved {
  from = azurerm_api_management_api_operation.browser_gateway["ingestion-put"]
  to   = module.browser_gateway.azurerm_api_management_api_operation.browser_gateway["ingestion-put"]
}

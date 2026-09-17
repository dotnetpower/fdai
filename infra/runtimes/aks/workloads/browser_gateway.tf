locals {
  browser_gateway_enabled = try(var.browser_gateway.enabled, false)
  browser_gateway_name = local.browser_gateway_enabled ? format(
    "apim-%s-%s-%s-%s",
    var.browser_gateway.workload,
    var.browser_gateway.environment,
    var.browser_gateway.region_short,
    var.browser_gateway.resource_name_suffix,
  ) : ""
  browser_gateway_services = local.browser_gateway_enabled ? {
    operator = {
      display_name = "FDAI Operator API"
      path         = ""
      workload     = "operator-service"
    }
    ingestion = {
      display_name = "FDAI Document Ingestion API"
      path         = "ingestion"
      workload     = "document-ingestion-api"
    }
  } : {}
  browser_gateway_operations = {
    for operation in flatten([
      for service_name in keys(local.browser_gateway_services) : [
        for method in ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"] : {
          key          = "${service_name}-${lower(method)}"
          service_name = service_name
          method       = method
        }
      ]
    ]) : operation.key => operation
  }
  browser_gateway_addresses = {
    for service_name, service in local.browser_gateway_services : service_name => coalesce(
      try(kubernetes_service_v1.workload[service.workload].status[0].load_balancer[0].ingress[0].ip, null),
      try(kubernetes_service_v1.workload[service.workload].status[0].load_balancer[0].ingress[0].hostname, null),
    )
  }
}

resource "azurerm_api_management" "browser_gateway" {
  # checkov:skip=CKV_AZURE_174:The browser gateway is the public HTTPS edge; backend APIs independently enforce Entra JWT, App Roles, and exact-origin CORS.
  # checkov:skip=CKV_AZURE_107:APIM Consumption has no VNet integration; it targets exact LoadBalancer addresses protected by the optional subnet NSG rule below.
  count = local.browser_gateway_enabled ? 1 : 0

  name                          = local.browser_gateway_name
  location                      = var.browser_gateway.location
  resource_group_name           = var.browser_gateway.resource_group_name
  publisher_name                = var.browser_gateway.publisher_name
  publisher_email               = var.browser_gateway.publisher_email
  sku_name                      = "Consumption_0"
  public_network_access_enabled = true
  min_api_version               = "2021-08-01"
  tags                          = var.tags
}

resource "azurerm_api_management_api" "browser_gateway" {
  for_each = local.browser_gateway_services

  name                  = "fdai-${each.key}"
  resource_group_name   = var.browser_gateway.resource_group_name
  api_management_name   = azurerm_api_management.browser_gateway[0].name
  revision              = "1"
  display_name          = each.value.display_name
  path                  = each.value.path
  protocols             = ["https"]
  service_url           = "http://${local.browser_gateway_addresses[each.key]}"
  subscription_required = false
}

resource "azurerm_api_management_api_operation" "browser_gateway" {
  for_each = local.browser_gateway_operations

  operation_id = (
    each.value.method == "GET" ? "proxy-all" : "proxy-${lower(each.value.method)}"
  )
  api_name            = azurerm_api_management_api.browser_gateway[each.value.service_name].name
  api_management_name = azurerm_api_management.browser_gateway[0].name
  resource_group_name = var.browser_gateway.resource_group_name
  display_name        = "Proxy ${each.value.method} requests"
  method              = each.value.method
  url_template        = "/*"
}

resource "azurerm_network_security_rule" "browser_gateway" {
  # checkov:skip=CKV_AZURE_160:APIM Consumption has no fixed outbound IP; this rule permits port 80 only to the two exact API LoadBalancer frontend addresses.
  count = local.browser_gateway_enabled && try(var.browser_gateway.backend_nsg_id, "") != "" ? 1 : 0

  name                   = "AllowBrowserGatewayBackends"
  priority               = 450
  direction              = "Inbound"
  access                 = "Allow"
  protocol               = "Tcp"
  source_port_range      = "*"
  destination_port_range = "80"
  source_address_prefix  = "Internet"
  destination_address_prefixes = sort([
    local.browser_gateway_addresses.ingestion,
    local.browser_gateway_addresses.operator,
  ])
  resource_group_name         = element(split("/", var.browser_gateway.backend_nsg_id), 4)
  network_security_group_name = element(split("/", var.browser_gateway.backend_nsg_id), 8)
}

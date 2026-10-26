locals {
  services = var.enabled ? {
    operator = {
      display_name = "FDAI Operator API"
      path         = ""
      backend_url  = trimsuffix(var.operator_backend_url, "/")
    }
    ingestion = {
      display_name = "FDAI Document Ingestion API"
      path         = "ingestion"
      backend_url  = trimsuffix(var.ingestion_backend_url, "/")
    }
  } : {}
  operations = {
    for operation in flatten([
      for service_name in keys(local.services) : [
        for method in ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"] : {
          key          = "${service_name}-${lower(method)}"
          service_name = service_name
          method       = method
        }
      ]
    ]) : operation.key => operation
  }
  tags = {
    for key, value in var.tags : replace(replace(key, "fdai.io/", "fdai:"), "/", "-") => value
  }
}

resource "azurerm_api_management" "browser_gateway" {
  # checkov:skip=CKV_AZURE_174:The browser gateway is the public HTTPS edge; APIM and backend APIs independently enforce Entra JWT validation, while backends retain App Role authorization.
  # checkov:skip=CKV_AZURE_107:APIM Consumption has no VNet integration; HTTP backends require exact LoadBalancer addresses protected by the optional subnet NSG rule below.
  count = var.enabled ? 1 : 0

  name                          = var.name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  publisher_name                = var.publisher_name
  publisher_email               = var.publisher_email
  sku_name                      = "Consumption_0"
  public_network_access_enabled = true
  min_api_version               = "2021-08-01"
  tags                          = local.tags

  lifecycle {
    precondition {
      condition = (
        (!startswith(var.operator_backend_url, "http://") && !startswith(var.ingestion_backend_url, "http://")) ||
        var.backend_nsg_id != ""
      )
      error_message = "HTTP browser-gateway backends require the exact backend subnet NSG binding."
    }
  }
}

resource "azurerm_api_management_api" "browser_gateway" {
  for_each = local.services

  name                  = "fdai-${each.key}"
  resource_group_name   = var.resource_group_name
  api_management_name   = azurerm_api_management.browser_gateway[0].name
  revision              = "1"
  display_name          = each.value.display_name
  path                  = each.value.path
  protocols             = ["https"]
  service_url           = each.value.backend_url
  subscription_required = false
}

resource "azurerm_api_management_api_operation" "browser_gateway" {
  for_each = local.operations

  operation_id = (
    each.value.method == "GET" ? "proxy-all" : "proxy-${lower(each.value.method)}"
  )
  api_name            = azurerm_api_management_api.browser_gateway[each.value.service_name].name
  api_management_name = azurerm_api_management.browser_gateway[0].name
  resource_group_name = var.resource_group_name
  display_name        = "Proxy ${each.value.method} requests"
  method              = each.value.method
  url_template        = "/*"
}

resource "azurerm_api_management_api_policy" "browser_gateway_ingestion" {
  count = var.enabled ? 1 : 0

  depends_on = [
    azurerm_api_management_api.browser_gateway,
    azurerm_api_management_api_operation.browser_gateway,
  ]

  api_name            = azurerm_api_management_api.browser_gateway["ingestion"].name
  api_management_name = azurerm_api_management.browser_gateway[0].name
  resource_group_name = var.resource_group_name
  xml_content = templatefile("${path.module}/policy.xml.tftpl", {
    console_origin        = var.console_origin
    frontend_audience     = var.frontend_audience
    ingestion_backend_url = trimsuffix(var.ingestion_backend_url, "/")
    service_name          = "ingestion"
    tenant_id             = var.frontend_tenant_id
  })
}

resource "azurerm_api_management_api_policy" "browser_gateway_documents" {
  count = var.enabled ? 1 : 0

  depends_on = [
    azurerm_api_management_api.browser_gateway,
    azurerm_api_management_api_operation.browser_gateway,
    azurerm_api_management_api_policy.browser_gateway_ingestion,
  ]

  api_name            = azurerm_api_management_api.browser_gateway["operator"].name
  api_management_name = azurerm_api_management.browser_gateway[0].name
  resource_group_name = var.resource_group_name
  xml_content = templatefile("${path.module}/policy.xml.tftpl", {
    console_origin        = var.console_origin
    frontend_audience     = var.frontend_audience
    ingestion_backend_url = trimsuffix(var.ingestion_backend_url, "/")
    service_name          = "operator"
    tenant_id             = var.frontend_tenant_id
  })
}

resource "azurerm_network_security_rule" "browser_gateway" {
  # checkov:skip=CKV_AZURE_160:APIM Consumption has no fixed outbound IP; this rule permits port 80 only from the AzureCloud service tag to the two exact API LoadBalancer frontend addresses.
  count = var.enabled && var.backend_nsg_id != "" ? 1 : 0

  name                         = "AllowBrowserGatewayBackends"
  priority                     = 450
  direction                    = "Inbound"
  access                       = "Allow"
  protocol                     = "Tcp"
  source_port_range            = "*"
  destination_port_range       = "80"
  source_address_prefix        = "AzureCloud"
  destination_address_prefixes = sort(var.backend_nsg_destination_addresses)
  resource_group_name          = element(split("/", var.backend_nsg_id), 4)
  network_security_group_name  = element(split("/", var.backend_nsg_id), 8)
}

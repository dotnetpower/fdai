mock_provider "azurerm" {
  mock_resource "azurerm_api_management" {
    defaults = {
      id          = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ApiManagement/service/apim-fdai-dev-wus3-abc123"
      gateway_url = "https://apim-fdai-dev-wus3-abc123.azure-api.net"
    }
  }
}

variables {
  name                  = "apim-fdai-dev-wus3-abc123"
  resource_group_name   = "rg-example"
  location              = "westus3"
  frontend_tenant_id    = "00000000-0000-0000-0000-000000000000"
  frontend_audience     = "00000000-0000-0000-0000-000000000001"
  console_origin        = "https://console.example.com"
  operator_backend_url  = "https://operator.example.com"
  ingestion_backend_url = "https://ingestion.example.com"
}

run "plans_authenticated_browser_gateway" {
  command = plan

  assert {
    condition = (
      azurerm_api_management.browser_gateway[0].sku_name == "Consumption_0" &&
      azurerm_api_management.browser_gateway[0].public_network_access_enabled &&
      length(azurerm_api_management_api_operation.browser_gateway) == 14
    )
    error_message = "The browser gateway must expose one HTTPS Consumption edge with both APIs and all supported methods."
  }

  assert {
    condition = (
      azurerm_api_management_api.browser_gateway["operator"].path == "" &&
      azurerm_api_management_api.browser_gateway["ingestion"].path == "ingestion" &&
      !azurerm_api_management_api.browser_gateway["operator"].subscription_required &&
      !azurerm_api_management_api.browser_gateway["ingestion"].subscription_required
    )
    error_message = "Operator must route at the gateway root while ingestion keeps a dedicated path."
  }

  assert {
    condition = alltrue([
      for policy in [
        azurerm_api_management_api_policy.browser_gateway_documents[0].xml_content,
        azurerm_api_management_api_policy.browser_gateway_ingestion[0].xml_content,
      ] :
      strcontains(policy, "<validate-jwt") &&
      strcontains(policy, "<audience>00000000-0000-0000-0000-000000000001</audience>") &&
      strcontains(policy, "<origin>https://console.example.com</origin>") &&
      strcontains(policy, "EndsWith(&quot;/healthz&quot;)")
    ])
    error_message = "Both gateway APIs must enforce the exact Entra audience and Console origin while retaining the health probe."
  }

  assert {
    condition = (
      strcontains(
        azurerm_api_management_api_policy.browser_gateway_ingestion[0].xml_content,
        "rewrite-uri template=\"@(&quot;/ingestion&quot; + context.Request.Url.Path)\"",
      ) &&
      strcontains(
        azurerm_api_management_api_policy.browser_gateway_documents[0].xml_content,
        "context.Request.Url.Path.StartsWith(&quot;/documents/&quot;)",
      ) &&
      strcontains(
        azurerm_api_management_api_policy.browser_gateway_documents[0].xml_content,
        "set-backend-service base-url=\"https://ingestion.example.com\"",
      )
    )
    error_message = "Ingestion and root-level document routes must reach the ingestion backend."
  }
}

run "rejects_http_backends_without_nsg" {
  command = plan

  variables {
    operator_backend_url  = "http://192.0.2.10"
    ingestion_backend_url = "http://192.0.2.11"
  }

  expect_failures = [
    azurerm_api_management.browser_gateway[0],
  ]
}

run "plans_http_backends_with_exact_nsg" {
  command = plan

  variables {
    operator_backend_url  = "http://192.0.2.10"
    ingestion_backend_url = "http://192.0.2.11"
    backend_nsg_id        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.Network/networkSecurityGroups/nsg-example"
    backend_nsg_destination_addresses = [
      "192.0.2.10",
      "192.0.2.11",
    ]
  }

  assert {
    condition = (
      azurerm_network_security_rule.browser_gateway[0].source_address_prefix == "AzureCloud" &&
      azurerm_network_security_rule.browser_gateway[0].destination_port_range == "80" &&
      toset(azurerm_network_security_rule.browser_gateway[0].destination_address_prefixes) == toset(["192.0.2.10", "192.0.2.11"])
    )
    error_message = "HTTP backends must retain the AzureCloud-to-exact-frontends NSG boundary."
  }
}

mock_provider "azurerm" {
  mock_resource "azurerm_static_web_app" {
    defaults = {
      id                = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.Web/staticSites/stapp-fdai-dev-ea-abc123"
      default_host_name = "console.example.com"
    }
  }

  mock_resource "azurerm_api_management" {
    defaults = {
      id          = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ApiManagement/service/apim-fdai-dev-wus3-abc123"
      gateway_url = "https://gateway.example.com"
    }
  }
}

override_data {
  target = data.azurerm_resource_group.target
  values = {
    id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example"
    name     = "rg-example"
    location = "westus3"
  }
}

variables {
  resource_group_name   = "rg-example"
  gateway_location      = "westus3"
  console_location      = "eastasia"
  region_short          = "wus3"
  console_region_short  = "ea"
  resource_name_suffix  = "abc123"
  frontend_tenant_id    = "00000000-0000-0000-0000-000000000000"
  frontend_audience     = "00000000-0000-0000-0000-000000000001"
  operator_backend_url  = "https://operator.example.com"
  ingestion_backend_url = "https://ingestion.example.com"
}

run "plans_separate_console_gateway_root" {
  command = apply

  assert {
    condition = (
      output.console_static_web_app_id == "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.Web/staticSites/stapp-fdai-dev-ea-abc123" &&
      output.console_origin == "https://console.example.com" &&
      output.console_redirect_uri == output.console_origin
    )
    error_message = "The root must expose the exact Static Web App publication and Entra redirect bindings."
  }

  assert {
    condition = (
      output.browser_gateway_id == "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ApiManagement/service/apim-fdai-dev-wus3-abc123" &&
      output.operator_api_base_url == "https://gateway.example.com" &&
      output.ingestion_api_base_url == "https://gateway.example.com/ingestion"
    )
    error_message = "The root must expose the exact API Management and browser API bindings."
  }

  assert {
    condition = output.reachability_checks == {
      gateway_frontend_tenant_id          = "00000000-0000-0000-0000-000000000000"
      gateway_frontend_audience           = "00000000-0000-0000-0000-000000000001"
      console_origin                      = "https://console.example.com"
      console_static_web_app_id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.Web/staticSites/stapp-fdai-dev-ea-abc123"
      operator_health_url                 = "https://gateway.example.com/healthz"
      ingestion_health_url                = "https://gateway.example.com/ingestion/healthz"
      operator_unauthenticated_probe_url  = "https://gateway.example.com/audit"
      ingestion_unauthenticated_probe_url = "https://gateway.example.com/documents"
    }
    error_message = "Live reachability checks must use exact health and unauthenticated probe URLs."
  }

  assert {
    condition = (
      module.console.custom_hostname == "" &&
      module.browser_gateway.api_management_name == "apim-fdai-dev-wus3-abc123"
    )
    error_message = "The root must reuse the Console and browser-gateway modules with deterministic names."
  }
}

run "rejects_non_development_environment" {
  command = plan

  variables {
    environment = "prod"
  }

  expect_failures = [
    var.environment,
  ]
}

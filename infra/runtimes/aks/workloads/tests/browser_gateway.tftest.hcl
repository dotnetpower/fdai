mock_provider "azurerm" {}
mock_provider "kubernetes" {
  mock_resource "kubernetes_service_v1" {
    defaults = {
      status = [{
        load_balancer = [{
          ingress = [{ ip = "192.0.2.10" }]
        }]
      }]
    }
  }
}

variables {
  kubeconfig_path = "/unused/mock-kubeconfig"
  tenant_id       = "00000000-0000-0000-0000-000000000000"
  oidc_issuer_url = "https://example.com/oidc/"
  key_vault_name  = "example"
  browser_gateway = {
    resource_group_name  = "rg-example-dev-wus2"
    location             = "westus2"
    workload             = "example"
    environment          = "dev"
    region_short         = "wus2"
    resource_name_suffix = "a1b2c3"
    backend_nsg_id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-dev-wus2/providers/Microsoft.Network/networkSecurityGroups/nsg-example"
  }
  workloads = {
    operator-service = {
      component            = "operator"
      image                = "example.com/fdai/operator@sha256:0000000000000000000000000000000000000000000000000000000000000000"
      identity_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/operator"
      identity_client_id   = "00000000-0000-0000-0000-000000000001"
      command              = ["python", "-m", "operator"]
      replicas             = 2
      max_replicas         = 4
      cpu                  = "500m"
      memory               = "1Gi"
      port                 = 8000
      service_port         = 80
      external             = true
      readiness_path       = "/healthz"
      liveness_path        = "/healthz"
      environment          = {}
    }
    document-ingestion-api = {
      component            = "ingestion"
      image                = "example.com/fdai/ingestion@sha256:0000000000000000000000000000000000000000000000000000000000000000"
      identity_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/ingestion"
      identity_client_id   = "00000000-0000-0000-0000-000000000002"
      command              = ["python", "-m", "ingestion"]
      replicas             = 2
      max_replicas         = 4
      cpu                  = "500m"
      memory               = "1Gi"
      port                 = 8000
      service_port         = 80
      external             = true
      readiness_path       = "/healthz"
      liveness_path        = "/healthz"
      environment          = {}
    }
  }
}

run "browser_gateway_contract" {
  command = plan

  assert {
    condition = (
      azurerm_api_management.browser_gateway[0].sku_name == "Consumption_0" &&
      azurerm_api_management.browser_gateway[0].public_network_access_enabled
    )
    error_message = "The browser gateway must expose one HTTPS Consumption endpoint."
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
    condition = (
      length(azurerm_api_management_api_operation.browser_gateway) == 14 &&
      toset([for operation in azurerm_api_management_api_operation.browser_gateway : operation.method]) == toset(["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"])
    )
    error_message = "Each browser API must declare every supported HTTP method explicitly."
  }

  assert {
    condition = (
      azurerm_network_security_rule.browser_gateway[0].source_address_prefix == "Internet" &&
      azurerm_network_security_rule.browser_gateway[0].destination_port_range == "80" &&
      azurerm_network_security_rule.browser_gateway[0].network_security_group_name == "nsg-example"
    )
    error_message = "A policy-attached subnet NSG must allow only the public API frontend port."
  }

  assert {
    condition = alltrue([
      for service in kubernetes_service_v1.workload :
      service.wait_for_load_balancer == (service.spec[0].type == "LoadBalancer")
    ])
    error_message = "Only public Services must wait for their LoadBalancer address."
  }
}

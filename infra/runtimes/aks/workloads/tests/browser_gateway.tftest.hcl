mock_provider "azurerm" {
  mock_resource "azurerm_api_management" {
    defaults = {
      id          = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-dev-wus2/providers/Microsoft.ApiManagement/service/apim-example-dev-wus2-a1b2c3"
      gateway_url = "https://gateway.example.com"
    }
  }
}
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
      source_commit        = "0000000000000000000000000000000000000000"
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
      environment = {
        FDAI_API_AUDIENCE                    = "00000000-0000-0000-0000-000000000003"
        FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS = "https://console.example.com"
      }
    }
    document-ingestion-api = {
      component            = "ingestion"
      source_commit        = "0000000000000000000000000000000000000000"
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
      environment = {
        FDAI_INGESTION_CORS_ALLOW_ORIGINS = "https://console.example.com"
      }
    }
  }
}

run "browser_gateway_contract" {
  command = apply

  assert {
    condition = (
      module.browser_gateway.api_management_name == "apim-example-dev-wus2-a1b2c3" &&
      output.browser_gateway_operator_url == "https://gateway.example.com" &&
      output.browser_gateway_ingestion_url == "https://gateway.example.com/ingestion"
    )
    error_message = "The AKS workload root must reuse the browser-gateway module and expose both HTTPS routes."
  }

  assert {
    condition = (
      module.browser_gateway.backend_nsg_id == "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-dev-wus2/providers/Microsoft.Network/networkSecurityGroups/nsg-example"
    )
    error_message = "The AKS subnet NSG must allow port 80 only from the AzureCloud service tag."
  }

  assert {
    condition = alltrue([
      for service in kubernetes_service_v1.workload :
      service.wait_for_load_balancer == (service.spec[0].type == "LoadBalancer")
    ])
    error_message = "Only public Services must wait for their LoadBalancer address."
  }
}

run "browser_gateway_requires_backend_nsg_when_enabled" {
  command = plan

  variables {
    browser_gateway = {
      enabled              = true
      resource_group_name  = "rg-example-dev-wus2"
      location             = "westus2"
      workload             = "example"
      environment          = "dev"
      region_short         = "wus2"
      resource_name_suffix = "a1b2c3"
      backend_nsg_id       = ""
    }
  }

  expect_failures = [
    var.browser_gateway,
  ]
}

run "browser_gateway_tags_are_azure_safe" {
  command = plan

  variables {
    tags = {
      "fdai.io/source-commit" = "0000000000000000000000000000000000000000"
    }
  }

  assert {
    condition = (
      module.browser_gateway.tags == tomap({
        "fdai:source-commit" = "0000000000000000000000000000000000000000"
      }) &&
      alltrue([
        for key in keys(module.browser_gateway.tags) :
        length(regexall("[<>%&\\\\?/]", key)) == 0
      ])
    )
    error_message = "Azure tag names must not carry Kubernetes label-key separators."
  }

  assert {
    condition = alltrue([
      for deployment in kubernetes_deployment_v1.workload :
      deployment.metadata[0].labels["fdai.io/source-commit"] == "0000000000000000000000000000000000000000"
    ])
    error_message = "Kubernetes workload labels must keep the stable label key."
  }
}

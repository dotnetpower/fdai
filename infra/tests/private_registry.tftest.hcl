# Config contract: the image registry follows the tenant's network posture.
#
# A grep can only assert Terraform source text; this file asserts the planned
# configuration itself. `mock_provider` supplies synthetic provider responses,
# so `terraform test` runs the real plan graph with no Azure subscription, no
# credentials, and no network. Every identifier below is synthetic.
#
# Run: terraform -chdir=infra test

mock_provider "azurerm" {}
mock_provider "archive" {}

variables {
  region                     = "koreacentral"
  deploy_runner_principal_id = "00000000-0000-0000-0000-000000000001"
  tenant_id                  = "00000000-0000-0000-0000-000000000000"
  postgres_admin_login       = "fdaiadmin"
  postgres_admin_password    = "terraform-test-placeholder-value"
  core_image                 = "mcr.microsoft.com/example/fdai@sha256:0000000000000000000000000000000000000000000000000000000000000000"
}

run "premium_registry_in_a_private_tenant_gets_an_endpoint" {
  command = plan

  variables {
    enable_private_networking = true
    acr_sku                   = "Premium"
  }

  assert {
    condition     = length(module.acr_private_endpoint) == 1
    error_message = "a private-networking tenant with a Premium registry MUST plan a registry private endpoint"
  }
}

run "basic_registry_keeps_its_only_reachable_path" {
  command = plan

  variables {
    enable_private_networking = true
    acr_sku                   = "Basic"
  }

  assert {
    condition     = length(module.acr_private_endpoint) == 0
    error_message = "private link is Premium-only; a Basic registry MUST NOT plan a private endpoint"
  }
}

run "public_tenant_provisions_no_registry_endpoint" {
  command = plan

  variables {
    enable_private_networking = false
    acr_sku                   = "Premium"
  }

  assert {
    condition     = length(module.acr_private_endpoint) == 0
    error_message = "a public tenant MUST NOT provision a registry private endpoint"
  }

  assert {
    condition     = output.container_registry_name == "crfdai"
    error_message = "An empty resource_name_suffix must preserve the existing registry name."
  }
}

run "public_contributor_gets_stable_global_names_and_core_handoff" {
  command = plan

  variables {
    env                               = "dev"
    region_short                      = "krc"
    resource_name_suffix              = "a1b2c3"
    enable_llm                        = true
    llm_public_network_access_enabled = true
  }

  assert {
    condition     = output.container_registry_name == "crfdaidevkrca1b2c3"
    error_message = "A fresh contributor registry must include the explicit stable suffix."
  }

  assert {
    condition = (
      output.event_bus_kafka_bootstrap == "evhns-fdai-dev-krc-a1b2c3.servicebus.windows.net:9093" &&
      output.event_bus_operational_kafka_bootstrap == "evhns-fdai-dev-krc-ops-a1b2c3.servicebus.windows.net:9093"
    )
    error_message = "Both globally scoped Event Hubs namespaces must include the contributor suffix."
  }

  assert {
    condition = (
      nonsensitive(output.contributor_core_service_tfvars).name == "ca-fdai-dev-krc-core" &&
      nonsensitive(output.contributor_core_service_tfvars).image == var.core_image &&
      nonsensitive(output.contributor_core_service_tfvars).runtime_env == "dev" &&
      nonsensitive(output.contributor_core_service_tfvars).database.role == "fdai_core" &&
      nonsensitive(output.contributor_core_service_tfvars).event_topics.events == "fdai.change.events" &&
      nonsensitive(output.contributor_core_service_tfvars).llm.web_search_enabled == false
    )
    error_message = "The public dev platform must export a complete, shadow-safe Core service handoff."
  }
}

run "reject_malformed_resource_name_suffix" {
  command = plan

  variables {
    resource_name_suffix = "UPPER"
  }

  expect_failures = [var.resource_name_suffix]
}

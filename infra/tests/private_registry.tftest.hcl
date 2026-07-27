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
  region                  = "koreacentral"
  tenant_id               = "00000000-0000-0000-0000-000000000000"
  postgres_admin_login    = "fdaiadmin"
  postgres_admin_password = "terraform-test-placeholder-value"
  core_image              = "mcr.microsoft.com/example/fdai@sha256:0000000000000000000000000000000000000000000000000000000000000000"
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
}

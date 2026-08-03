mock_provider "azurerm" {}
mock_provider "archive" {}

variables {
  env                     = "dev"
  region                  = "koreacentral"
  region_short            = "krc"
  tenant_id               = "00000000-0000-0000-0000-000000000000"
  postgres_admin_login    = "fdaiadmin"
  postgres_admin_password = "terraform-test-placeholder-value"
  core_image              = "mcr.microsoft.com/example/fdai@sha256:0000000000000000000000000000000000000000000000000000000000000000"
}

run "design_mocks_is_an_isolated_free_static_site" {
  command = plan

  variables {
    enable_design_mocks = true
  }

  assert {
    condition     = length(module.design_mocks) == 1
    error_message = "enabling design mocks MUST plan one Static Web App"
  }

  assert {
    condition     = module.design_mocks[0].name == "stapp-fdai-design-mocks-dev-ea"
    error_message = "the design-mocks Static Web App MUST use the approved CAF name"
  }

  assert {
    condition     = module.design_mocks[0].sku_tier == "Free"
    error_message = "the design-mocks Static Web App MUST remain on the Free tier"
  }

  assert {
    condition     = module.design_mocks[0].preview_environments_enabled == false
    error_message = "design mocks MUST NOT publish pull-request preview environments"
  }
}

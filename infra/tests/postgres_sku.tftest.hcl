# The deployment profile selects the PostgreSQL Flexible Server size explicitly. Provider
# responses are synthetic; these plans call no Azure API.
# Run: terraform -chdir=infra test -filter=tests/postgres_sku.tftest.hcl

mock_provider "azurerm" {}
mock_provider "archive" {}
mock_provider "random" {}

override_data {
  target = data.azurerm_client_config.current
  values = {
    subscription_id = "00000000-0000-0000-0000-000000000000"
    tenant_id       = "00000000-0000-0000-0000-000000000000"
    object_id       = "00000000-0000-0000-0000-000000000001"
  }
}

override_module {
  target = module.resource_group
  outputs = {
    name = "rg-example"
  }
}

variables {
  region                     = "koreacentral"
  deploy_runner_principal_id = "00000000-0000-0000-0000-000000000001"
  tenant_id                  = "00000000-0000-0000-0000-000000000000"
  postgres_admin_login       = "fdaiadmin"
  postgres_admin_password    = "terraform-test-placeholder-value"
  core_image                 = "registry.example.com/fdai@sha256:0000000000000000000000000000000000000000000000000000000000000000"
}

run "unselected_size_keeps_the_day_zero_burstable_server" {
  command = plan

  plan_options {
    target = [module.state_store]
  }

  assert {
    condition     = var.postgres_sku_name == "B_Standard_B1ms"
    error_message = "An unselected size must keep the day-zero Burstable B1ms server."
  }
}

run "supported_general_purpose_size_is_accepted" {
  command = plan

  plan_options {
    target = [module.state_store]
  }

  variables {
    postgres_sku_name = "GP_Standard_D2ds_v5"
  }

  assert {
    condition     = var.postgres_sku_name == "GP_Standard_D2ds_v5"
    error_message = "A supported size must be accepted unchanged."
  }
}

run "unsupported_size_is_rejected" {
  command = plan

  plan_options {
    target = [module.state_store]
  }

  variables {
    postgres_sku_name = "GP_Standard_D64ds_v5"
  }

  expect_failures = [var.postgres_sku_name]
}

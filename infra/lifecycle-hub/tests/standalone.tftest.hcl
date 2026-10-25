mock_provider "azurerm" {}

variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"
  tenant_id       = "00000000-0000-0000-0000-000000000001"
  location        = "koreacentral"
  prefix          = "examplehub"
  tags            = { environment = "test" }
  network = {
    vnet     = "10.120.0.0/16"
    apps     = "10.120.0.0/23"
    database = "10.120.2.0/24"
    secrets  = "10.120.3.0/24"
  }
  database_admin = {
    object_id    = "00000000-0000-0000-0000-000000000002"
    display_name = "example-operator"
  }
  database = {
    sku_name                     = "B_Standard_B1ms"
    storage_mb                   = 32768
    backup_retention_days        = 7
    geo_redundant_backup_enabled = false
    zone_redundant               = false
  }
  log_retention_days = 30
  replicas           = { min = 1, max = 2 }
  registry = {
    id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.ContainerRegistry/registries/example"
    server = "registry.example.com"
  }
  image         = "registry.example.com/hub@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  ingress_cidrs = ["192.0.2.1/32"]
}

run "standalone_base" {
  command = plan
  assert {
    condition = (
      output.deployment.product == "target" &&
      output.deployment.resource_group == "rg-examplehub-target" &&
      !contains(keys(output.deployment.runtime_config), "auth") &&
      !contains(keys(output.deployment.runtime_config), "catalog")
    )
    error_message = "Customer Lifecycle Hub must plan alone without any vendor or directory bindings."
  }
}

run "standalone_app_and_migration" {
  command = plan
  variables {
    enable_apps           = true
    enable_migration_jobs = true
    secret_versions = {
      database    = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      signing_key = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }

  }
  assert {
    condition     = output.deployment.migration_job == "caj-examplehub-target-migrate"
    error_message = "This product must declare its own manual migration Job."
  }
}

run "temporary_bootstrap_without_directory_registration" {
  command = plan
  variables {
    enable_bootstrap_job = true
  }
  assert {
    condition     = output.bootstrap_job == "caj-examplehub-target-bootstrap"
    error_message = "Customer initialization must not require a vendor Hub or directory registration."
  }
}

run "different_environment_same_code" {
  command = plan
  variables {
    prefix   = "exampleprod"
    location = "westeurope"
    tags     = { environment = "production" }
    database = {
      sku_name                     = "GP_Standard_D2s_v3"
      storage_mb                   = 65536
      backup_retention_days        = 14
      geo_redundant_backup_enabled = true
      zone_redundant               = true
    }
  }

  assert {
    condition     = output.deployment.resource_group == "rg-exampleprod-target"
    error_message = "Environment values must not require a cloned Terraform source."
  }
}

run "migration_retains_existing_app" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind                  = "target"
    image                 = "registry.example.com/hub@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    app_image             = "registry.example.com/hub@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    enable_apps           = true
    enable_migration_jobs = true
    secret_versions = {
      database    = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      signing_key = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
  }
  assert {
    condition = (
      azurerm_container_app.hub["target"].template[0].container[0].image == var.app_image &&
      azurerm_container_app_job.migrate["target"].template[0].container[0].image == var.image &&
      length(azurerm_container_app_job.bootstrap) == 0
    )
    error_message = "Migration must use the candidate without activating it or recreating bootstrap."
  }
}

run "activation_uses_candidate_by_default" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind                  = "target"
    enable_apps           = true
    enable_migration_jobs = true
    secret_versions = {
      database    = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      signing_key = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
  }
  assert {
    condition = (
      var.app_image == null &&
      azurerm_container_app.hub["target"].template[0].container[0].image == var.image &&
      azurerm_container_app_job.migrate["target"].template[0].container[0].image == var.image
    )
    error_message = "Omitting the override must keep the existing single-image behavior."
  }
}

run "mutable_app_image_is_rejected" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind      = "target"
    app_image = "registry.example.com/hub:latest"
  }
  expect_failures = [var.app_image]
}

run "operator_defaults_preserve_older_runtime_config" {
  command = plan
  variables {
    operator_auth = {
      profile        = "remote-development"
      tenant_id      = "00000000-0000-0000-0000-000000000001"
      audience       = "example-api"
      spa_client_id  = "example-browser"
      operator_scope = "Hub.Access"
      operator_ids   = ["example-operator"]
    }
  }
  assert {
    condition     = !contains(keys(output.deployment.runtime_config.auth), "agent_principals")
    error_message = "Default bindings must not add fields that older Hub images reject."
  }
}

run "explicit_agent_bindings_reach_runtime" {
  command = plan
  variables {
    operator_auth = {
      profile        = "remote-development"
      tenant_id      = "00000000-0000-0000-0000-000000000001"
      audience       = "example-api"
      spa_client_id  = "example-browser"
      operator_scope = "Hub.Access"
      operator_ids   = ["example-operator"]
      agent_principals = [{
        installation_id = "installation-alpha"
        object_id       = "example-agent-object"
        client_id       = "example-agent-client"
      }]
    }
  }
  assert {
    condition = (
      length(output.deployment.runtime_config.auth.agent_principals) == 1 &&
      output.deployment.runtime_config.auth.agent_principals[0].installation_id == "installation-alpha" &&
      output.deployment.runtime_config.auth.agent_principals[0].object_id == "example-agent-object" &&
      output.deployment.runtime_config.auth.agent_principals[0].client_id == "example-agent-client"
    )
    error_message = "Independent Lifecycle Hub inputs must preserve the exact Agent binding."
  }
}

run "vendor_rejects_agent_bindings" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "release"
    operator_auth = {
      profile        = "remote-development"
      tenant_id      = "00000000-0000-0000-0000-000000000001"
      audience       = "example-api"
      spa_client_id  = "example-browser"
      operator_scope = "Hub.Access"
      operator_ids   = ["example-operator"]
      agent_principals = [{
        installation_id = "installation-alpha"
        object_id       = "example-agent-object"
        client_id       = "example-agent-client"
      }]
    }
  }
  expect_failures = [var.operator_auth]
}

run "custom_domain_propagates_to_operator_auth_origin" {
  command = plan
  variables {
    resource_group_name = "rg-example-dev-lc1"
    custom_domain = {
      hostname = "lifecycle.example.com"
    }
    operator_auth = {
      profile        = "remote-development"
      tenant_id      = "00000000-0000-0000-0000-000000000001"
      audience       = "example-api"
      spa_client_id  = "example-browser"
      operator_scope = "Hub.Access"
      operator_ids   = ["example-operator"]
    }
  }
  assert {
    condition = (
      output.deployment.resource_group == "rg-example-dev-lc1" &&
      output.deployment.origin == "https://lifecycle.example.com" &&
      output.deployment.runtime_config.auth.origin == "https://lifecycle.example.com"
    )
    error_message = "Custom domain and explicit resource group must bind the deployment output and operator_auth.origin."
  }
}

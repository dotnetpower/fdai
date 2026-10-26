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

run "development_recovery_reaches_target_runtime" {
  command = plan
  variables {
    operator_auth = {
      profile        = "remote-development"
      tenant_id      = "00000000-0000-0000-0000-000000000001"
      audience       = "example-api"
      spa_client_id  = "example-browser"
      operator_scope = "Hub.Access"
      operator_ids   = ["example-operator"]
      development_recovery = {
        profile                                   = "full-authority-development"
        installation_id                           = "installation-alpha"
        scope                                     = "rg-example-dev"
        operator_id                               = "example-operator"
        previous_identity_key_id                  = "installation-0123456789abcdef"
        replacement_identity_public_key           = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
        authorized_at                             = "2026-10-26T00:00:00Z"
        authorization_expires_at                  = "2026-11-09T00:00:00Z"
        allow_single_owner_configuration_approval = true
        reason                                    = "Recover one exact development installation."
      }
    }
  }
  assert {
    condition = (
      output.deployment.runtime_config.auth.development_recovery.installation_id == "installation-alpha" &&
      output.deployment.runtime_config.auth.development_recovery.operator_id == "example-operator" &&
      output.deployment.runtime_config.auth.development_recovery.scope == "rg-example-dev" &&
      output.deployment.runtime_config.auth.development_recovery.allow_single_owner_configuration_approval
    )
    error_message = "The target Hub must retain every protected development recovery binding."
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

run "vendor_rejects_development_recovery" {
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
      development_recovery = {
        profile                                   = "full-authority-development"
        installation_id                           = "installation-alpha"
        scope                                     = "rg-example-dev"
        operator_id                               = "example-operator"
        previous_identity_key_id                  = "installation-0123456789abcdef"
        replacement_identity_public_key           = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
        authorized_at                             = "2026-10-26T00:00:00Z"
        authorization_expires_at                  = "2026-11-09T00:00:00Z"
        allow_single_owner_configuration_approval = true
        reason                                    = "Recover one exact development installation."
      }
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

run "default_hostname_redirect_is_opt_in" {
  command = plan
  variables {
    custom_domain = {
      hostname                  = "lifecycle.example.com"
      redirect_default_hostname = true
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
    condition     = contains(keys(output.deployment.runtime_config.auth), "redirect_hosts")
    error_message = "A selected redirect must send the default hostname to the custom origin."
  }
}

run "default_hostname_redirect_is_absent_unless_selected" {
  command = plan
  variables {
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
    condition     = !contains(keys(output.deployment.runtime_config.auth), "redirect_hosts")
    error_message = "A Hub image that predates redirect_hosts must not receive the key."
  }
}

run "catalog_defaults_preserve_older_runtime_config" {
  command = plan
  variables {
    catalog = {
      url                        = "https://release.example.com/v1/catalog/export"
      token_scope                = "api://example-release/.default"
      managed_identity_client_id = "example-client"
      release_public_key         = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
    }
  }
  assert {
    condition = (
      length(keys(output.deployment.runtime_config.catalog)) == 4 &&
      !contains(keys(output.deployment.runtime_config.catalog), "access") &&
      !contains(keys(output.deployment.runtime_config.catalog), "adoption") &&
      !contains(keys(output.deployment.runtime_config.catalog), "check_interval_seconds")
    )
    error_message = "A catalog without new settings must not add keys that older Hub images reject."
  }
}

run "auto_adoption_reaches_runtime" {
  command = plan
  variables {
    catalog = {
      url                        = "https://release.example.com/v1/catalog/export"
      token_scope                = "api://example-release/.default"
      managed_identity_client_id = "example-client"
      release_public_key         = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
      access                     = "managed-identity"
      check_interval_seconds     = 900
      adoption = {
        mode                     = "auto"
        allowed_channels         = ["stable"]
        max_new_releases         = 2
        authorized_by            = "example-owner"
        authorization_expires_at = "2030-01-31T00:00:00Z"
      }
    }
  }
  assert {
    condition = (
      output.deployment.runtime_config.catalog.check_interval_seconds == 900 &&
      output.deployment.runtime_config.catalog.adoption.mode == "auto" &&
      output.deployment.runtime_config.catalog.adoption.allowed_channels[0] == "stable" &&
      output.deployment.runtime_config.catalog.adoption.max_new_releases == 2 &&
      output.deployment.runtime_config.catalog.adoption.authorized_by == "example-owner" &&
      output.deployment.runtime_config.catalog.adoption.authorization_expires_at == "2030-01-31T00:00:00Z"
    )
    error_message = "Standing authorization must reach the Hub exactly as reviewed."
  }
}

run "review_adoption_needs_no_authorization" {
  command = plan
  variables {
    catalog = {
      url                        = "https://release.example.com/v1/catalog/export"
      token_scope                = "api://example-release/.default"
      managed_identity_client_id = "example-client"
      release_public_key         = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
      adoption = {
        mode             = "review"
        allowed_channels = ["stable"]
      }
    }
  }
  assert {
    condition = (
      output.deployment.runtime_config.catalog.adoption.mode == "review" &&
      !contains(keys(output.deployment.runtime_config.catalog.adoption), "authorized_by") &&
      !contains(keys(output.deployment.runtime_config.catalog.adoption), "max_new_releases")
    )
    error_message = "Review mode must not require or invent a standing authorization."
  }
}

run "anonymous_catalog_omits_identity" {
  command = plan
  variables {
    catalog = {
      url                = "https://release.example.com/v1/catalog/export"
      release_public_key = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
      access             = "anonymous"
    }
  }
  assert {
    condition = (
      output.deployment.runtime_config.catalog.access == "anonymous" &&
      !contains(keys(output.deployment.runtime_config.catalog), "token_scope") &&
      !contains(keys(output.deployment.runtime_config.catalog), "managed_identity_client_id")
    )
    error_message = "Anonymous catalog access must not carry an identity."
  }
}

run "checks_can_be_disabled" {
  command = plan
  variables {
    catalog = {
      url                        = "https://release.example.com/v1/catalog/export"
      token_scope                = "api://example-release/.default"
      managed_identity_client_id = "example-client"
      release_public_key         = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
      check_interval_seconds     = 0
    }
  }
  assert {
    condition = (
      output.deployment.runtime_config.catalog.check_interval_seconds == 0
    )
    error_message = "Zero must be emitted so an operator can disable periodic checks."
  }
}

run "anonymous_catalog_rejects_identity" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url                        = "https://release.example.com/v1/catalog/export"
      token_scope                = "api://example-release/.default"
      managed_identity_client_id = "example-client"
      release_public_key         = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
      access                     = "anonymous"
    }
  }
  expect_failures = [var.catalog]
}

run "managed_identity_catalog_requires_identity" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url                = "https://release.example.com/v1/catalog/export"
      release_public_key = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
    }
  }
  expect_failures = [var.catalog]
}

run "auto_adoption_requires_authorization" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url                        = "https://release.example.com/v1/catalog/export"
      token_scope                = "api://example-release/.default"
      managed_identity_client_id = "example-client"
      release_public_key         = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
      adoption = {
        mode = "auto"
      }
    }
  }
  expect_failures = [var.catalog]
}

run "auto_adoption_requires_expiry" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url                        = "https://release.example.com/v1/catalog/export"
      token_scope                = "api://example-release/.default"
      managed_identity_client_id = "example-client"
      release_public_key         = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
      adoption = {
        mode          = "auto"
        authorized_by = "example-owner"
      }
    }
  }
  expect_failures = [var.catalog]
}

run "authorization_expiry_requires_timezone" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url                        = "https://release.example.com/v1/catalog/export"
      token_scope                = "api://example-release/.default"
      managed_identity_client_id = "example-client"
      release_public_key         = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
      adoption = {
        mode                     = "auto"
        authorized_by            = "example-owner"
        authorization_expires_at = "2030-01-31T00:00:00"
      }
    }
  }
  expect_failures = [var.catalog]
}

run "adoption_rejects_unknown_mode" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url                        = "https://release.example.com/v1/catalog/export"
      token_scope                = "api://example-release/.default"
      managed_identity_client_id = "example-client"
      release_public_key         = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
      adoption = {
        mode = "always"
      }
    }
  }
  expect_failures = [var.catalog]
}

run "adoption_rejects_duplicate_channels" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url                        = "https://release.example.com/v1/catalog/export"
      token_scope                = "api://example-release/.default"
      managed_identity_client_id = "example-client"
      release_public_key         = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
      adoption = {
        allowed_channels = ["stable", "stable"]
      }
    }
  }
  expect_failures = [var.catalog]
}

run "adoption_rejects_oversized_release_budget" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url                        = "https://release.example.com/v1/catalog/export"
      token_scope                = "api://example-release/.default"
      managed_identity_client_id = "example-client"
      release_public_key         = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
      adoption = {
        max_new_releases = 65
      }
    }
  }
  expect_failures = [var.catalog]
}

run "check_interval_below_five_minutes_is_rejected" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url                        = "https://release.example.com/v1/catalog/export"
      token_scope                = "api://example-release/.default"
      managed_identity_client_id = "example-client"
      release_public_key         = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
      check_interval_seconds     = 299
    }
  }
  expect_failures = [var.catalog]
}

run "check_interval_above_one_day_is_rejected" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url                        = "https://release.example.com/v1/catalog/export"
      token_scope                = "api://example-release/.default"
      managed_identity_client_id = "example-client"
      release_public_key         = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
      check_interval_seconds     = 86401
    }
  }
  expect_failures = [var.catalog]
}

run "catalog_rejects_non_export_url" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url                        = "https://release.example.com/v1/other"
      token_scope                = "api://example-release/.default"
      managed_identity_client_id = "example-client"
      release_public_key         = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
    }
  }
  expect_failures = [var.catalog]
}

run "vendor_rejects_catalog_source" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "release"
    catalog = {
      url                        = "https://release.example.com/v1/catalog/export"
      token_scope                = "api://example-release/.default"
      managed_identity_client_id = "example-client"
      release_public_key         = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
    }
  }
  expect_failures = [var.catalog]
}

run "target_rejects_public_catalog_export" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    operator_auth = {
      profile               = "remote-development"
      tenant_id             = "00000000-0000-0000-0000-000000000001"
      audience              = "example-api"
      spa_client_id         = "example-browser"
      operator_scope        = "Hub.Access"
      operator_ids          = ["example-operator"]
      public_catalog_export = true
    }
  }
  expect_failures = [var.operator_auth]
}

run "target_rejects_timestamp_renewal" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind                            = "target"
    timestamp_renewal_check_seconds = 120
  }
  expect_failures = [var.timestamp_renewal_check_seconds]
}

run "signed_roles_trust_reaches_runtime_without_a_release_key" {
  command = plan
  variables {
    catalog = {
      url    = "https://release.example.com/v1/catalog/export"
      access = "anonymous"
      trust = {
        mode           = "tuf"
        root_key_ids   = ["ed25519-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "ed25519-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "ed25519-cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"]
        root_threshold = 2
      }
    }
  }
  assert {
    condition = (
      output.deployment.runtime_config.catalog.trust.mode == "tuf" &&
      output.deployment.runtime_config.catalog.trust.root_threshold == 2 &&
      length(output.deployment.runtime_config.catalog.trust.root_key_ids) == 3 &&
      !contains(keys(output.deployment.runtime_config.catalog), "release_public_key")
    )
    error_message = "Signed-roles trust must replace the single release key in the runtime config."
  }
}

run "catalog_trust_is_one_of_key_or_roles" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url                = "https://release.example.com/v1/catalog/export"
      access             = "anonymous"
      release_public_key = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n"
      trust = {
        mode           = "tuf"
        root_key_ids   = ["ed25519-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]
        root_threshold = 1
      }
    }
  }
  expect_failures = [var.catalog]
}

run "catalog_without_any_trust_is_rejected" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url    = "https://release.example.com/v1/catalog/export"
      access = "anonymous"
    }
  }
  expect_failures = [var.catalog]
}

run "signed_roles_reject_malformed_key_ids" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url    = "https://release.example.com/v1/catalog/export"
      access = "anonymous"
      trust = {
        mode           = "tuf"
        root_key_ids   = ["hub-0123456789abcdef"]
        root_threshold = 1
      }
    }
  }
  expect_failures = [var.catalog]
}

run "signed_roles_reject_duplicate_key_ids" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url    = "https://release.example.com/v1/catalog/export"
      access = "anonymous"
      trust = {
        mode           = "tuf"
        root_key_ids   = ["ed25519-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "ed25519-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]
        root_threshold = 1
      }
    }
  }
  expect_failures = [var.catalog]
}

run "signed_roles_reject_a_threshold_above_the_key_count" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url    = "https://release.example.com/v1/catalog/export"
      access = "anonymous"
      trust = {
        mode           = "tuf"
        root_key_ids   = ["ed25519-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]
        root_threshold = 2
      }
    }
  }
  expect_failures = [var.catalog]
}

run "signed_roles_reject_a_zero_threshold_and_an_unknown_mode" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    catalog = {
      url    = "https://release.example.com/v1/catalog/export"
      access = "anonymous"
      trust = {
        mode           = "pinned"
        root_key_ids   = ["ed25519-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]
        root_threshold = 0
      }
    }
  }
  expect_failures = [var.catalog]
}

run "target_rejects_catalog_roles_serving" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind          = "target"
    catalog_roles = {}
  }
  expect_failures = [var.catalog_roles]
}

run "rebind_operation_needs_an_actor_and_reason_and_no_request_secret" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    secret_versions = {
      database    = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      signing_key = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
    operation_job = {
      operation = "rebind-catalog"
      actor     = "example-operator"
      reason    = "Move to signed catalog roles"
    }
  }
  assert {
    condition = (
      length(azurerm_container_app_job.operation) == 1 &&
      contains(azurerm_container_app_job.operation["target"].template[0].container[0].args, "--reason") &&
      !contains(azurerm_container_app_job.operation["target"].template[0].container[0].args, "--request-env") &&
      length(azurerm_role_assignment.operation_request_reader) == 0
    )
    error_message = "A binding operation reads no request secret and gets no request reader grant."
  }
}

run "bind_operation_is_accepted" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    secret_versions = {
      database    = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      signing_key = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
    operation_job = {
      operation = "bind-catalog"
      actor     = "example-operator"
      reason    = "Bind the independently approved source"
    }
  }
  assert {
    condition     = length(azurerm_container_app_job.operation) == 1
    error_message = "bind-catalog is a Lifecycle Hub operation."
  }
}

run "request_operation_still_uses_its_secret" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    secret_versions = {
      database    = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      signing_key = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
    operation_job = {
      operation              = "recompute"
      actor                  = "example-operator"
      request_secret_version = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    }
  }
  assert {
    condition = (
      contains(azurerm_container_app_job.operation["target"].template[0].container[0].args, "--request-env") &&
      length(azurerm_role_assignment.operation_request_reader) == 1
    )
    error_message = "A request operation keeps its request secret and reader grant."
  }
}

run "bind_operation_without_a_reason_is_rejected" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    operation_job = {
      operation = "rebind-catalog"
      actor     = "example-operator"
    }
  }
  expect_failures = [var.operation_job]
}

run "bind_operation_with_a_request_secret_is_rejected" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    operation_job = {
      operation              = "bind-catalog"
      actor                  = "example-operator"
      reason                 = "Bind the independently approved source"
      request_secret_version = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    }
  }
  expect_failures = [var.operation_job]
}

run "request_operation_with_a_reason_is_rejected" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    operation_job = {
      operation              = "recompute"
      actor                  = "example-operator"
      request_secret_version = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
      reason                 = "not allowed here"
    }
  }
  expect_failures = [var.operation_job]
}

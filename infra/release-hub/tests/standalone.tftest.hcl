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
      output.deployment.product == "release" &&
      output.deployment.resource_group == "rg-examplehub-release" &&
      !contains(keys(output.deployment.runtime_config), "auth") &&
      !contains(keys(output.deployment.runtime_config), "catalog")
    )
    error_message = "Vendor Release Hub must plan alone without any customer or directory bindings."
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
    condition     = output.deployment.migration_job == "caj-examplehub-release-migrate"
    error_message = "This product must declare its own manual migration Job."
  }
}

run "temporary_bootstrap_without_directory_registration" {
  command = plan
  variables {
    enable_bootstrap_job = true
  }
  assert {
    condition     = output.bootstrap_job == "caj-examplehub-release-bootstrap"
    error_message = "Bootstrap must retain the human database administrator."
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
    condition     = output.deployment.resource_group == "rg-exampleprod-release"
    error_message = "Environment values must not require a cloned Terraform source."
  }
}

run "migration_retains_existing_app" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind                  = "release"
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
      azurerm_container_app.hub["release"].template[0].container[0].image == var.app_image &&
      azurerm_container_app_job.migrate["release"].template[0].container[0].image == var.image &&
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
    kind                  = "release"
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
      azurerm_container_app.hub["release"].template[0].container[0].image == var.image &&
      azurerm_container_app_job.migrate["release"].template[0].container[0].image == var.image
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
    kind      = "release"
    app_image = "registry.example.com/hub:latest"
  }
  expect_failures = [var.app_image]
}

run "custom_domain_binds_origin_probes_and_dns_records" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind                  = "release"
    enable_apps           = true
    enable_migration_jobs = true
    secret_versions = {
      database    = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      signing_key = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
    custom_domain = {
      hostname = "hub.example.com"
      dns_zone = {
        name                = "example.com"
        resource_group_name = "rg-common"
        ttl                 = 300
      }
    }
  }
  assert {
    condition = (
      output.deployment.origin == "https://hub.example.com" &&
      output.deployment.runtime_config.origin == "https://hub.example.com" &&
      azurerm_container_app.hub["release"].template[0].container[0].readiness_probe[0].header[0].value == "hub.example.com" &&
      azurerm_container_app.hub["release"].template[0].container[0].liveness_probe[0].header[0].value == "hub.example.com" &&
      azurerm_dns_cname_record.hub_custom_domain["release"].name == "hub" &&
      azurerm_dns_cname_record.hub_custom_domain["release"].zone_name == "example.com" &&
      azurerm_dns_cname_record.hub_custom_domain["release"].resource_group_name == "rg-common" &&
      azurerm_dns_txt_record.hub_custom_domain["release"].name == "asuid.hub" &&
      azurerm_container_app_custom_domain.hub["release"].name == "hub.example.com"
    )
    error_message = "Custom domain must bind the HTTPS origin, probe Host headers, DNS records and Container App custom domain."
  }
}

run "invalid_custom_domain_zone_mismatch_is_rejected" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "release"
    custom_domain = {
      hostname = "hub.other.example.com"
      dns_zone = {
        name                = "example.com"
        resource_group_name = "rg-common"
      }
    }
  }
  expect_failures = [var.custom_domain]
}

run "defaults_preserve_older_runtime_config" {
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
    condition = (
      !contains(keys(output.deployment.runtime_config.auth), "public_catalog_export") &&
      !contains(keys(output.deployment.runtime_config), "timestamp_renewal_check_seconds")
    )
    error_message = "Default settings must not add keys that older Hub images reject."
  }
}

run "public_catalog_export_reaches_runtime" {
  command = plan
  variables {
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
  assert {
    condition = (
      output.deployment.runtime_config.auth.public_catalog_export == true
    )
    error_message = "Anonymous catalog export must be an explicit Release Hub setting."
  }
}

run "timestamp_renewal_reaches_runtime" {
  command = plan
  variables {
    timestamp_renewal_check_seconds = 120
  }
  assert {
    condition = (
      output.deployment.runtime_config.timestamp_renewal_check_seconds == 120
    )
    error_message = "Freshness renewal must reach the Release Hub when enabled."
  }
}

run "timestamp_renewal_zero_is_omitted" {
  command = plan
  variables {
    timestamp_renewal_check_seconds = 0
  }
  assert {
    condition = (
      !contains(keys(output.deployment.runtime_config), "timestamp_renewal_check_seconds")
    )
    error_message = "Disabled renewal must not add a key."
  }
}

run "timestamp_renewal_below_one_minute_is_rejected" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind                            = "release"
    timestamp_renewal_check_seconds = 59
  }
  expect_failures = [var.timestamp_renewal_check_seconds]
}

run "timestamp_renewal_above_one_hour_is_rejected" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind                            = "release"
    timestamp_renewal_check_seconds = 3601
  }
  expect_failures = [var.timestamp_renewal_check_seconds]
}

run "catalog_roles_are_omitted_by_default" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind        = "release"
    enable_apps = true
    secret_versions = {
      database    = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      signing_key = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
  }
  assert {
    condition = (
      !contains(keys(output.deployment.runtime_config), "catalog_roles") &&
      length([for e in azurerm_container_app.hub["release"].template[0].container[0].env : e.name if startswith(e.name, "FDAI_HUB_CATALOG_")]) == 0
    )
    error_message = "Without signed roles the Release Hub must add no key, secret or environment variable."
  }
}

run "catalog_roles_reach_runtime_with_separate_secret_references" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind        = "release"
    enable_apps = true
    catalog_roles = {
      timestamp_ttl_seconds = 7200
    }
    secret_versions = {
      database              = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      signing_key           = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
      catalog_snapshot_key  = "cccccccccccccccccccccccccccccccc"
      catalog_timestamp_key = "dddddddddddddddddddddddddddddddd"
    }
  }
  assert {
    condition = (
      output.deployment.runtime_config.catalog_roles.timestamp_ttl_seconds == 7200 &&
      !contains(keys(output.deployment.runtime_config.catalog_roles), "snapshot_ttl_seconds") &&
      length([for e in azurerm_container_app.hub["release"].template[0].container[0].env : e.name if e.name == "FDAI_HUB_CATALOG_SNAPSHOT_KEY"]) == 1 &&
      length([for e in azurerm_container_app.hub["release"].template[0].container[0].env : e.name if e.name == "FDAI_HUB_CATALOG_TIMESTAMP_KEY"]) == 1
    )
    error_message = "Signed roles need their own snapshot and timestamp secret references, never the development key."
  }
}

run "catalog_roles_require_both_secret_versions" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind          = "release"
    enable_apps   = true
    catalog_roles = {}
    secret_versions = {
      database             = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      signing_key          = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
      catalog_snapshot_key = "cccccccccccccccccccccccccccccccc"
    }
  }
  expect_failures = [var.secret_versions]
}

run "catalog_roles_reject_a_short_timestamp_window" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind          = "release"
    catalog_roles = { timestamp_ttl_seconds = 60 }
  }
  expect_failures = [var.catalog_roles]
}

run "catalog_roles_reject_a_snapshot_that_expires_before_the_timestamp" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind          = "release"
    catalog_roles = { timestamp_ttl_seconds = 172800, snapshot_ttl_seconds = 86400 }
  }
  expect_failures = [var.catalog_roles]
}

run "root_installation_is_a_release_operation" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind          = "release"
    catalog_roles = {}
    secret_versions = {
      database              = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      signing_key           = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
      catalog_snapshot_key  = "cccccccccccccccccccccccccccccccc"
      catalog_timestamp_key = "dddddddddddddddddddddddddddddddd"
    }
    operation_job = {
      operation              = "install-catalog-root"
      request_secret_version = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
      actor                  = "example-operator"
    }
  }
  assert {
    condition     = length(azurerm_container_app_job.operation) == 1
    error_message = "The offline-signed root is installed through the product-owned operation Job."
  }
}

run "root_installation_is_rejected_for_the_lifecycle_hub" {
  command = plan
  module {
    source = "../modules/hub-service"
  }
  variables {
    kind = "target"
    operation_job = {
      operation              = "install-catalog-root"
      request_secret_version = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
      actor                  = "example-operator"
    }
  }
  expect_failures = [var.operation_job]
}

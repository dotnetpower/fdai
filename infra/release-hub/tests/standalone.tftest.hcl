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

// Global provider-schema watcher. Root ownership isolates the Job from the
// broad compute module dependency graph while preserving its runtime contract.

locals {
  provider_schema_job_enabled    = var.provider_schema_cron_expression != ""
  provider_schema_resource_group = "rg-${var.workload}${local.full_suffix}"
  provider_schema_environment    = "cae-${var.workload}${local.full_suffix}"
  provider_schema_environment_id = join("", [
    "/subscriptions/${data.azurerm_client_config.current.subscription_id}",
    "/resourceGroups/${local.provider_schema_resource_group}",
    "/providers/Microsoft.App/managedEnvironments/${local.provider_schema_environment}",
  ])
  provider_schema_acr_login_server = (
    "cr${var.workload}${local.acr_suffix}${var.resource_name_suffix}.azurecr.io"
  )
  provider_schema_inventory_identity = (
    "id-${var.workload}${local.full_suffix}-inventory"
  )
  provider_schema_inventory_identity_id = join("", [
    "/subscriptions/${data.azurerm_client_config.current.subscription_id}",
    "/resourceGroups/${local.provider_schema_resource_group}",
    "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/${local.provider_schema_inventory_identity}",
  ])
  provider_schema_job_name = (
    length("caj-${var.workload}${local.full_suffix}-provider-schema") <= 32
    ? "caj-${var.workload}${local.full_suffix}-provider-schema"
    : "caj-${var.workload}${local.env_suffix}-provider"
  )
  provider_schema_state_store_dsn_secret_uri = join("", [
    "https://kv-${var.workload}${local.full_suffix}${local.global_name_suffix}",
    ".vault.azure.net/secrets/fdai-state-store-dsn",
  ])
  provider_schema_kafka_bootstrap = join("", [
    "evhns-${var.workload}${local.full_suffix}${local.global_name_suffix}",
    ".servicebus.windows.net:9093",
  ])
}

data "azurerm_user_assigned_identity" "provider_schema_inventory" {
  count = local.provider_schema_job_enabled ? 1 : 0

  name                = local.provider_schema_inventory_identity
  resource_group_name = local.provider_schema_resource_group
}

moved {
  from = module.compute.azurerm_container_app_job.provider_schema[0]
  to   = azurerm_container_app_job.provider_schema[0]
}

resource "azurerm_container_app_job" "provider_schema" {
  count = local.provider_schema_job_enabled ? 1 : 0

  name                         = local.provider_schema_job_name
  container_app_environment_id = local.provider_schema_environment_id
  resource_group_name          = local.provider_schema_resource_group
  location                     = var.region
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 1800
  replica_retry_limit          = 0

  identity {
    type         = "UserAssigned"
    identity_ids = [local.provider_schema_inventory_identity_id]
  }

  dynamic "registry" {
    for_each = local.provider_schema_acr_login_server == "" ? toset([]) : toset(["1"])
    content {
      server   = local.provider_schema_acr_login_server
      identity = local.provider_schema_inventory_identity_id
    }
  }

  secret {
    name                = "provider-schema-dsn"
    identity            = local.provider_schema_inventory_identity_id
    key_vault_secret_id = local.provider_schema_state_store_dsn_secret_uri
  }

  schedule_trigger_config {
    cron_expression          = var.provider_schema_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "provider-schema"
      image   = var.core_image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "-m", "fdai.delivery.provider_schema_watcher_cli"]

      env {
        name        = "FDAI_PROVIDER_SCHEMA_DSN"
        secret_name = "provider-schema-dsn"
      }

      env {
        name  = "FDAI_PROVIDER_SCHEMA_NETWORK_POLICY"
        value = "public"
      }

      env {
        name  = "FDAI_PROVIDER_SCHEMA_PRIMARY_REPO"
        value = "https://github.com/Azure/bicep-types-az.git"
      }

      env {
        name  = "FDAI_PROVIDER_SCHEMA_PRIMARY_REF"
        value = "refs/heads/main"
      }

      env {
        name  = "FDAI_PROVIDER_SCHEMA_CADENCE_SECONDS"
        value = "86400"
      }

      env {
        name  = "FDAI_PROVIDER_SCHEMA_FETCH_TIMEOUT_SECONDS"
        value = "900"
      }

      env {
        name  = "FDAI_PROVIDER_SCHEMA_MIN_TYPES"
        value = "3000"
      }

      env {
        name  = "FDAI_PROVIDER_SCHEMA_MAX_TYPES"
        value = "10000"
      }

      env {
        name  = "FDAI_PROVIDER_SCHEMA_REVIEW_COMPATIBLE"
        value = "1"
      }

      env {
        name  = "KAFKA_BOOTSTRAP_SERVERS"
        value = local.provider_schema_kafka_bootstrap
      }

      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = data.azurerm_user_assigned_identity.provider_schema_inventory[0].client_id
      }
    }
  }

  tags = local.tags
}

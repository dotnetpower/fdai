// Global provider-schema watcher. The mechanical Job resolves an immutable
// upstream revision, writes its append-only ledger to the existing private
// StateStore, and delegates strict material Drift publication to Heimdall.
resource "azurerm_container_app_job" "provider_schema" {
  count = var.provider_schema_cron_expression == "" ? 0 : 1

  name                         = var.provider_schema_job_name
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 1800
  replica_retry_limit          = 0

  identity {
    type         = "UserAssigned"
    identity_ids = [var.inventory_identity_id]
  }

  dynamic "registry" {
    for_each = var.acr_login_server == "" ? toset([]) : toset(["1"])
    content {
      server   = var.acr_login_server
      identity = var.inventory_identity_id
    }
  }

  secret {
    name                = "provider-schema-dsn"
    identity            = var.inventory_identity_id
    key_vault_secret_id = var.state_store_dsn_secret_id
  }

  schedule_trigger_config {
    cron_expression          = var.provider_schema_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "provider-schema"
      image   = var.image
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
        name  = "KAFKA_BOOTSTRAP_SERVERS"
        value = var.kafka_bootstrap_servers
      }
      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = var.inventory_identity_client_id
      }
    }
  }

  tags = var.tags
}

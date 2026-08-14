// Bounded browser-evidence retention cleanup. This Job reuses the inventory
// identity for ACR and Key Vault access and never receives executor authority.
resource "azurerm_container_app_job" "browser_evidence_cleanup" {
  count = var.browser_evidence_cleanup_cron_expression == "" ? 0 : 1

  name                         = var.browser_evidence_cleanup_job_name
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 300
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
    name                = "browser-evidence-cleanup-dsn"
    identity            = var.inventory_identity_id
    key_vault_secret_id = var.state_store_dsn_secret_id
  }

  schedule_trigger_config {
    cron_expression          = var.browser_evidence_cleanup_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "browser-evidence-cleanup"
      image   = var.image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-m", "fdai.delivery.browser_evidence_cleanup_cli"]

      env {
        name        = "FDAI_DATABASE_URL"
        secret_name = "browser-evidence-cleanup-dsn"
      }
      env {
        name  = "FDAI_BROWSER_EVIDENCE_CLEANUP_LIMIT"
        value = tostring(var.browser_evidence_cleanup_limit)
      }
    }
  }

  tags = merge(var.tags, { "fdai:component" = "browser-gc" })
}

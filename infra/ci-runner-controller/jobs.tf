# Exclusively controller-dispatched: no GitHub scaler, webhook trigger or worker PAT.
# AzureRM does not expose identitySettings/lifecycle=None for registry-only MI use.
# Read back that restriction before activation when the platform supports it; never
# substitute the controller identity. The attached worker identity is AcrPull only.
resource "azurerm_container_app_job" "worker" {
  for_each                     = local.jobs
  name                         = each.value
  resource_group_name          = azurerm_resource_group.workers.name
  location                     = var.location
  container_app_environment_id = azurerm_container_app_environment.workers.id
  replica_timeout_in_seconds   = var.replica_timeout_seconds
  replica_retry_limit          = 0
  tags                         = local.worker_tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.worker_pull.id]
  }
  registry {
    server   = var.registry_server
    identity = azurerm_user_assigned_identity.worker_pull.id
  }
  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }
  template {
    container {
      name    = "runner"
      image   = var.worker_image
      cpu     = 4
      memory  = "8Gi"
      command = ["/usr/bin/python3", "/opt/fdai-ci/broker-entrypoint.py"]
      env {
        name  = "GITHUB_REPOSITORY"
        value = var.github_repository
      }
    }
  }

  depends_on = [azurerm_role_assignment.worker_pull]
}

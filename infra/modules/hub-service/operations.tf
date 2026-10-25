resource "azurerm_container_app_job" "operation" {
  for_each                     = var.operation_job == null ? toset([]) : local.kinds
  name                         = "caj-${var.prefix}-${each.key}-operation"
  location                     = var.location
  resource_group_name          = local.foundation[each.key].resource_group
  container_app_environment_id = local.foundation[each.key].environment_id
  replica_timeout_in_seconds   = 300
  replica_retry_limit          = 0
  workload_profile_name        = "Consumption"
  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }
  identity {
    type         = "UserAssigned"
    identity_ids = [local.foundation[each.key].identity_id]
  }
  registry {
    server   = var.registry.server
    identity = local.foundation[each.key].identity_id
  }
  secret {
    name                = "database-url"
    identity            = local.foundation[each.key].identity_id
    key_vault_secret_id = "${local.foundation[each.key].vault_uri}secrets/hub-database-url/${var.secret_versions.database}"
  }
  secret {
    name                = "development-signing-key"
    identity            = local.foundation[each.key].identity_id
    key_vault_secret_id = "${local.foundation[each.key].vault_uri}secrets/development-signing-key/${var.secret_versions.signing_key}"
  }
  secret {
    name                = "operation-request"
    identity            = local.foundation[each.key].identity_id
    key_vault_secret_id = "${local.foundation[each.key].vault_uri}secrets/hub-operation-request/${try(var.operation_job.request_secret_version, "")}"
  }
  dynamic "secret" {
    for_each = local.catalog_role_secrets
    content {
      name                = secret.key
      identity            = local.foundation[each.key].identity_id
      key_vault_secret_id = "${local.foundation[each.key].vault_uri}secrets/${secret.key}/${secret.value.version}"
    }
  }
  template {
    container {
      name    = "operation"
      image   = var.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "-m", "fdai_lifecycle_hub.remote"]
      args = [
        try(var.operation_job.operation, ""),
        "--actor",
        try(var.operation_job.actor, ""),
        "--request-env",
        "FDAI_HUB_OPERATION_REQUEST",
      ]
      env {
        name  = "FDAI_HUB_REMOTE_CONFIG"
        value = jsonencode(local.configs[each.key])
      }
      env {
        name        = each.key == "release" ? "FDAI_RELEASE_HUB_DATABASE_URL" : "FDAI_LIFECYCLE_HUB_DATABASE_URL"
        secret_name = "database-url"
      }
      env {
        name        = "FDAI_HUB_DEVELOPMENT_SIGNING_KEY"
        secret_name = "development-signing-key"
      }
      env {
        name        = "FDAI_HUB_OPERATION_REQUEST"
        secret_name = "operation-request"
      }
      dynamic "env" {
        for_each = local.catalog_role_secrets
        content {
          name        = env.value.env
          secret_name = env.key
        }
      }
      env {
        name  = "FDAI_HUB_MANAGED_IDENTITY_CLIENT_ID"
        value = local.foundation[each.key].identity_client_id
      }
    }
  }
  depends_on = [
    azurerm_role_assignment.registry_reader,
    azurerm_role_assignment.secret_reader,
    azurerm_role_assignment.operation_request_reader,
    azurerm_private_endpoint.vault,
    azurerm_private_dns_zone_virtual_network_link.vault,
  ]
  lifecycle {
    prevent_destroy = true
  }
}

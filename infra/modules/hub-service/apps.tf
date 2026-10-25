locals {
  origins = {
    for kind in local.kinds : kind => "https://ca-${var.prefix}-${kind}.${azurerm_container_app_environment.hub[kind].default_domain}"
  }
  foundation = {
    for kind in local.kinds : kind => {
      resource_group     = azurerm_resource_group.hub[kind].name
      environment_id     = azurerm_container_app_environment.hub[kind].id
      identity_id        = azurerm_user_assigned_identity.hub[kind].id
      identity_object_id = azurerm_user_assigned_identity.hub[kind].principal_id
      identity_client_id = azurerm_user_assigned_identity.hub[kind].client_id
      vault_id           = azurerm_key_vault.hub[kind].id
      vault_uri          = azurerm_key_vault.hub[kind].vault_uri
    }
  }
  # Unset optional attributes are omitted so images that predate a key still parse the config.
  catalog_adoption = merge([
    for adoption in [try(var.catalog.adoption, null)] :
    { for key, value in adoption : key => value if value != null }
    if adoption != null
  ]...)
  catalog_config = merge([
    for catalog in [var.catalog] : merge(
      { for key, value in catalog : key => value if value != null && key != "adoption" },
      { for key, value in { adoption = local.catalog_adoption } : key => value if length(value) > 0 },
    )
    if catalog != null
  ]...)
  configs = {
    for kind in local.kinds : kind => merge(
      { kind = kind, key_epoch = 1 },
      var.operator_auth == null ? { origin = local.origins[kind] } : {},
      var.operator_auth == null ? {} : {
        auth = merge(
          { for key, value in var.operator_auth : key => value if !contains(["agent_principals", "public_catalog_export"], key) },
          { origin = local.origins[kind] },
          length(var.operator_auth.agent_principals) == 0 ? {} : { agent_principals = var.operator_auth.agent_principals },
          var.operator_auth.public_catalog_export ? { public_catalog_export = true } : {},
        )
      },
      kind == "target" && var.catalog != null ? { catalog = local.catalog_config } : {},
      kind == "release" && var.timestamp_renewal_check_seconds > 0 ? { timestamp_renewal_check_seconds = var.timestamp_renewal_check_seconds } : {},
    )
  }
}

resource "azurerm_role_assignment" "registry_reader" {
  for_each             = local.kinds
  scope                = var.registry.id
  role_definition_name = "AcrPull"
  principal_id         = local.foundation[each.key].identity_object_id
  principal_type       = "ServicePrincipal"
  lifecycle {
    prevent_destroy = true
  }
}
resource "azurerm_role_assignment" "secret_reader" {
  for_each = {
    for pair in setproduct(local.kinds, toset(["development-signing-key", "hub-database-url"])) :
    "${pair[0]}-${pair[1]}" => { kind = pair[0], secret = pair[1] }
  }
  scope                = "${local.foundation[each.value.kind].vault_id}/secrets/${each.value.secret}"
  role_definition_name = "Key Vault Secrets User"
  principal_id         = local.foundation[each.value.kind].identity_object_id
  principal_type       = "ServicePrincipal"
  lifecycle {
    prevent_destroy = true
  }
}
resource "azurerm_role_assignment" "operation_request_reader" {
  for_each             = var.operation_job == null ? toset([]) : local.kinds
  scope                = "${local.foundation[each.key].vault_id}/secrets/hub-operation-request"
  role_definition_name = "Key Vault Secrets User"
  principal_id         = local.foundation[each.key].identity_object_id
  principal_type       = "ServicePrincipal"
  lifecycle {
    prevent_destroy = true
  }
}
resource "azurerm_container_app" "hub" {
  for_each                     = var.enable_apps ? local.kinds : toset([])
  name                         = "ca-${var.prefix}-${each.key}"
  resource_group_name          = local.foundation[each.key].resource_group
  container_app_environment_id = local.foundation[each.key].environment_id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  identity {
    type         = "UserAssigned"
    identity_ids = [local.foundation[each.key].identity_id]
  }
  registry {
    server   = var.registry.server
    identity = local.foundation[each.key].identity_id
  }
  secret {
    name                = "development-signing-key"
    identity            = local.foundation[each.key].identity_id
    key_vault_secret_id = "${local.foundation[each.key].vault_uri}secrets/development-signing-key/${var.secret_versions.signing_key}"
  }
  secret {
    name                = "database-url"
    identity            = local.foundation[each.key].identity_id
    key_vault_secret_id = "${local.foundation[each.key].vault_uri}secrets/hub-database-url/${var.secret_versions.database}"
  }
  ingress {
    external_enabled           = true
    allow_insecure_connections = false
    target_port                = 8080
    transport                  = "http"
    dynamic "ip_security_restriction" {
      for_each = var.ingress_cidrs
      content {
        name             = "allow-${substr(sha256(ip_security_restriction.value), 0, 12)}"
        action           = "Allow"
        ip_address_range = ip_security_restriction.value
      }
    }
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
  template {
    min_replicas = var.replicas.min
    max_replicas = var.replicas.max
    container {
      name   = "hub"
      image  = var.app_image == null ? var.image : var.app_image
      cpu    = 0.5
      memory = "1Gi"
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
        name  = "FDAI_HUB_MANAGED_IDENTITY_CLIENT_ID"
        value = local.foundation[each.key].identity_client_id
      }
      readiness_probe {
        transport = "HTTP"
        port      = 8080
        path      = "/readyz"
        header {
          name  = "Host"
          value = replace(local.origins[each.key], "https://", "")
        }
      }
      liveness_probe {
        transport = "HTTP"
        port      = 8080
        path      = "/healthz"
        header {
          name  = "Host"
          value = replace(local.origins[each.key], "https://", "")
        }
      }
    }
  }
  depends_on = [
    azurerm_role_assignment.registry_reader, azurerm_role_assignment.secret_reader,
    azurerm_private_endpoint.vault,
    azurerm_private_dns_zone_virtual_network_link.vault,
    azurerm_postgresql_flexible_server_configuration.log_connections,
    azurerm_postgresql_flexible_server_configuration.log_checkpoints,
    azurerm_postgresql_flexible_server_configuration.connection_throttle,
    azurerm_postgresql_flexible_server_configuration.tls_floor,
  ]
  lifecycle {
    prevent_destroy = true
  }
}

output "deployment" {
  value = merge(local.foundation[var.kind], {
    product        = var.kind
    origin         = local.origins[var.kind]
    database_host  = azurerm_postgresql_flexible_server.hub[var.kind].fqdn
    database_name  = azurerm_postgresql_flexible_server_database.hub[var.kind].name
    identity_name  = azurerm_user_assigned_identity.hub[var.kind].name
    runtime_config = local.configs[var.kind]
    migration_job  = var.enable_migration_jobs ? azurerm_container_app_job.migrate[var.kind].name : null
    operation_job  = var.operation_job == null ? null : azurerm_container_app_job.operation[var.kind].name
  })
}

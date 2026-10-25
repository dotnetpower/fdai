locals {
  default_hostnames = {
    for kind in local.kinds : kind => "ca-${var.prefix}-${kind}.${azurerm_container_app_environment.hub[kind].default_domain}"
  }
  hostnames = {
    for kind in local.kinds : kind => var.custom_domain == null ? local.default_hostnames[kind] : var.custom_domain.hostname
  }
  origins = {
    for kind in local.kinds : kind => "https://${local.hostnames[kind]}"
  }
  custom_domain_record_name = (
    var.custom_domain != null && var.custom_domain.dns_zone != null
    ? trimsuffix(var.custom_domain.hostname, ".${var.custom_domain.dns_zone.name}")
    : null
  )
  custom_domain_dns_kinds = (
    var.enable_apps && var.custom_domain != null && var.custom_domain.dns_zone != null
    ? local.kinds
    : toset([])
  )
  custom_domain_kinds = (
    var.enable_apps && var.custom_domain != null
    ? local.kinds
    : toset([])
  )
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
  catalog_role_secrets = var.catalog_roles == null ? {} : {
    "catalog-snapshot-key"  = { env = "FDAI_HUB_CATALOG_SNAPSHOT_KEY", version = var.secret_versions.catalog_snapshot_key }
    "catalog-timestamp-key" = { env = "FDAI_HUB_CATALOG_TIMESTAMP_KEY", version = var.secret_versions.catalog_timestamp_key }
  }
  configs = {
    for kind in local.kinds : kind => merge(
      { kind = kind, key_epoch = 1 },
      var.operator_auth == null ? { origin = local.origins[kind] } : {},
      var.operator_auth == null ? {} : {
        auth = merge(
          { for key, value in var.operator_auth : key => value if !contains(["agent_principals", "public_catalog_export"], key) },
          { origin = local.origins[kind] },
          try(var.custom_domain.redirect_default_hostname, false) ? { redirect_hosts = [local.default_hostnames[kind]] } : {},
          length(var.operator_auth.agent_principals) == 0 ? {} : { agent_principals = var.operator_auth.agent_principals },
          var.operator_auth.public_catalog_export ? { public_catalog_export = true } : {},
        )
      },
      kind == "target" && var.catalog != null ? { catalog = local.catalog_config } : {},
      kind == "release" && var.catalog_roles != null ? { catalog_roles = { for key, value in var.catalog_roles : key => value if value != null } } : {},
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
    for pair in setproduct(local.kinds, toset(concat(["development-signing-key", "hub-database-url"], keys(local.catalog_role_secrets)))) :
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
  for_each             = local.operation_uses_request ? local.kinds : toset([])
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
  dynamic "secret" {
    for_each = local.catalog_role_secrets
    content {
      name                = secret.key
      identity            = local.foundation[each.key].identity_id
      key_vault_secret_id = "${local.foundation[each.key].vault_uri}secrets/${secret.key}/${secret.value.version}"
    }
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

resource "azurerm_dns_cname_record" "hub_custom_domain" {
  for_each            = local.custom_domain_dns_kinds
  name                = local.custom_domain_record_name
  zone_name           = var.custom_domain.dns_zone.name
  resource_group_name = var.custom_domain.dns_zone.resource_group_name
  ttl                 = var.custom_domain.dns_zone.ttl
  record              = local.default_hostnames[each.key]
}
resource "azurerm_dns_txt_record" "hub_custom_domain" {
  for_each            = local.custom_domain_dns_kinds
  name                = "asuid.${local.custom_domain_record_name}"
  zone_name           = var.custom_domain.dns_zone.name
  resource_group_name = var.custom_domain.dns_zone.resource_group_name
  ttl                 = var.custom_domain.dns_zone.ttl
  record {
    value = azurerm_container_app.hub[each.key].custom_domain_verification_id
  }
}
resource "azurerm_container_app_custom_domain" "hub" {
  for_each                                 = local.custom_domain_kinds
  name                                     = var.custom_domain.hostname
  container_app_id                         = azurerm_container_app.hub[each.key].id
  certificate_binding_type                 = var.custom_domain.certificate_binding_type
  container_app_environment_certificate_id = var.custom_domain.certificate_id
  depends_on = [
    azurerm_dns_cname_record.hub_custom_domain,
    azurerm_dns_txt_record.hub_custom_domain,
  ]
  lifecycle {
    prevent_destroy = true
    ignore_changes = [
      certificate_binding_type,
      container_app_environment_certificate_id,
    ]
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

locals {
  origins = {
    for kind in local.kinds : kind => "https://ca-${var.prefix}-${kind}.${azurerm_container_app_environment.hub[kind].default_domain}"
  }
  scope_ids = { for kind in local.kinds : kind => uuidv5("dns", "${var.prefix}.${kind}.Hub.Access") }
  read_role = uuidv5("dns", "${var.prefix}.Catalog.Read")
  # Unset optional attributes are omitted so images that predate a key still parse the config.
  catalog_adoption = merge([
    for adoption in [var.catalog_adoption] :
    { for key, value in adoption : key => value if value != null }
    if adoption != null
  ]...)
  configs = {
    for kind in local.kinds : kind => merge({
      kind = kind
      auth = {
        profile           = "remote-development"
        tenant_id         = var.tenant_id
        audience          = azuread_application.api[kind].client_id
        origin            = local.origins[kind]
        spa_client_id     = azuread_application.browser[kind].client_id
        operator_scope    = "Hub.Access"
        operator_ids      = var.operator_object_ids
        service_object_id = kind == "release" ? azurerm_user_assigned_identity.hub["target"].principal_id : null
        service_client_id = kind == "release" ? azurerm_user_assigned_identity.hub["target"].client_id : null
        service_role      = "Catalog.Read"
      }
      catalog = kind == "target" ? merge({
        url                        = "${local.origins["release"]}/v1/catalog/export"
        token_scope                = "api://${azuread_application.api["release"].client_id}/.default"
        managed_identity_client_id = azurerm_user_assigned_identity.hub["target"].client_id
        },
        var.release_public_key == null ? {} : { release_public_key = var.release_public_key },
        var.catalog_trust == null ? {} : { trust = var.catalog_trust },
        var.catalog_check_interval_seconds == null ? {} : { check_interval_seconds = var.catalog_check_interval_seconds },
        length(local.catalog_adoption) == 0 ? {} : { adoption = local.catalog_adoption },
      ) : null
      key_epoch = 1
      },
      kind == "release" && var.catalog_roles != null ? { catalog_roles = { for key, value in var.catalog_roles : key => value if value != null } } : {},
      kind == "release" && var.timestamp_renewal_check_seconds > 0 ? { timestamp_renewal_check_seconds = var.timestamp_renewal_check_seconds } : {},
    )
  }
  # Separate online snapshot and timestamp key references, served by the release Hub only.
  catalog_role_secrets = {
    for kind in local.kinds : kind => kind == "release" && var.catalog_roles != null ? {
      "catalog-snapshot-key"  = { env = "FDAI_HUB_CATALOG_SNAPSHOT_KEY", version = try(var.secret_versions[kind].catalog_snapshot_key, "") }
      "catalog-timestamp-key" = { env = "FDAI_HUB_CATALOG_TIMESTAMP_KEY", version = try(var.secret_versions[kind].catalog_timestamp_key, "") }
    } : {}
  }
}

resource "azuread_application" "api" {
  for_each     = local.kinds
  display_name = "${var.prefix}-${each.key}-api"
  api {
    requested_access_token_version = 2
    oauth2_permission_scope {
      id                         = local.scope_ids[each.key]
      value                      = "Hub.Access"
      type                       = "Admin"
      admin_consent_display_name = "Operate development Hub"
      admin_consent_description  = "Access this Hub as an explicitly allowed human operator."
    }
  }
  app_role {
    id                   = local.read_role
    value                = "Catalog.Read"
    display_name         = "Read approved catalog export"
    description          = "Read export only; no publication or customer-side authority."
    allowed_member_types = ["Application"]
  }
  optional_claims {
    access_token {
      name = "idtyp"
    }
  }
}
resource "azuread_application_identifier_uri" "api" {
  for_each       = local.kinds
  application_id = azuread_application.api[each.key].id
  identifier_uri = "api://${azuread_application.api[each.key].client_id}"
}
resource "azuread_service_principal" "api" {
  for_each  = local.kinds
  client_id = azuread_application.api[each.key].client_id
}
resource "azuread_application" "browser" {
  for_each     = local.kinds
  display_name = "${var.prefix}-${each.key}-operator"
  single_page_application {
    redirect_uris = [local.origins[each.key]]
  }
  required_resource_access {
    resource_app_id = azuread_application.api[each.key].client_id
    resource_access {
      id   = local.scope_ids[each.key]
      type = "Scope"
    }
  }
}
resource "azuread_service_principal" "browser" {
  for_each  = local.kinds
  client_id = azuread_application.browser[each.key].client_id
}
resource "azuread_service_principal_delegated_permission_grant" "operator" {
  for_each                             = local.kinds
  service_principal_object_id          = azuread_service_principal.browser[each.key].object_id
  resource_service_principal_object_id = azuread_service_principal.api[each.key].object_id
  claim_values                         = ["Hub.Access"]
}
resource "azuread_app_role_assignment" "catalog_reader" {
  app_role_id         = local.read_role
  principal_object_id = azurerm_user_assigned_identity.hub["target"].principal_id
  resource_object_id  = azuread_service_principal.api["release"].object_id
}
resource "azurerm_role_assignment" "registry_reader" {
  for_each             = local.kinds
  scope                = var.registry.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.hub[each.key].principal_id
  principal_type       = "ServicePrincipal"
}
resource "azurerm_role_assignment" "secret_reader" {
  for_each = {
    for pair in flatten([
      for kind in local.kinds : [
        for secret in concat(["development-signing-key", "hub-database-url"], keys(local.catalog_role_secrets[kind])) : { kind = kind, secret = secret }
      ]
    ]) : "${pair.kind}-${pair.secret}" => pair
  }
  scope                = "${azurerm_key_vault.hub[each.value.kind].id}/secrets/${each.value.secret}"
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.hub[each.value.kind].principal_id
  principal_type       = "ServicePrincipal"
}
resource "azurerm_container_app" "hub" {
  for_each                     = var.enable_apps ? local.kinds : toset([])
  name                         = "ca-${var.prefix}-${each.key}"
  resource_group_name          = azurerm_resource_group.hub[each.key].name
  container_app_environment_id = azurerm_container_app_environment.hub[each.key].id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.hub[each.key].id]
  }
  registry {
    server   = var.registry.server
    identity = azurerm_user_assigned_identity.hub[each.key].id
  }
  secret {
    name                = "development-signing-key"
    identity            = azurerm_user_assigned_identity.hub[each.key].id
    key_vault_secret_id = "${azurerm_key_vault.hub[each.key].vault_uri}secrets/development-signing-key/${var.secret_versions[each.key].signing_key}"
  }
  secret {
    name                = "database-url"
    identity            = azurerm_user_assigned_identity.hub[each.key].id
    key_vault_secret_id = "${azurerm_key_vault.hub[each.key].vault_uri}secrets/hub-database-url/${var.secret_versions[each.key].database}"
  }
  dynamic "secret" {
    for_each = local.catalog_role_secrets[each.key]
    content {
      name                = secret.key
      identity            = azurerm_user_assigned_identity.hub[each.key].id
      key_vault_secret_id = "${azurerm_key_vault.hub[each.key].vault_uri}secrets/${secret.key}/${secret.value.version}"
    }
  }
  ingress {
    external_enabled           = true
    allow_insecure_connections = false
    target_port                = 8080
    transport                  = "http"
    dynamic "ip_security_restriction" {
      for_each = each.key == "release" ? setunion(var.operator_cidrs, toset(["${azurerm_public_ip.egress["target"].ip_address}/32"])) : var.operator_cidrs
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
    min_replicas = 1
    max_replicas = 2
    container {
      name   = "hub"
      image  = var.images[each.key]
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
        for_each = local.catalog_role_secrets[each.key]
        content {
          name        = env.value.env
          secret_name = env.key
        }
      }
      env {
        name  = "FDAI_HUB_MANAGED_IDENTITY_CLIENT_ID"
        value = azurerm_user_assigned_identity.hub[each.key].client_id
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
    azuread_app_role_assignment.catalog_reader,
    azurerm_postgresql_flexible_server_configuration.log_connections,
    azurerm_postgresql_flexible_server_configuration.log_checkpoints,
    azurerm_postgresql_flexible_server_configuration.connection_throttle,
    azurerm_postgresql_flexible_server_configuration.tls_floor,
  ]
}

output "boundaries" {
  value = {
    for kind in local.kinds : kind => {
      resource_group     = azurerm_resource_group.hub[kind].name
      identity_object_id = azurerm_user_assigned_identity.hub[kind].principal_id
      identity_name      = azurerm_user_assigned_identity.hub[kind].name
      database_host      = azurerm_postgresql_flexible_server.hub[kind].fqdn
      database_name      = azurerm_postgresql_flexible_server_database.hub[kind].name
      vault_uri          = azurerm_key_vault.hub[kind].vault_uri
      origin             = local.origins[kind]
      runtime_config     = local.configs[kind]
    }
  }
  description = "Private deployment values; retain outside the repository. No keys, tokens or database passwords."
}

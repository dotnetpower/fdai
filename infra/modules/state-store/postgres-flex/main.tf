resource "azurerm_postgresql_flexible_server" "primary" {
  name                          = var.name
  resource_group_name           = var.resource_group_name
  location                      = var.location
  version                       = var.postgres_version
  sku_name                      = var.sku_name
  storage_mb                    = var.storage_mb
  administrator_login           = var.administrator_login
  administrator_password        = var.administrator_password
  backup_retention_days         = var.backup_retention_days
  geo_redundant_backup_enabled  = var.geo_redundant_backup_enabled
  public_network_access_enabled = var.public_network_access_enabled
  delegated_subnet_id           = var.delegated_subnet_id
  private_dns_zone_id           = var.private_dns_zone_id

  # AAD auth is enabled alongside password auth so a fork can rotate the
  # bootstrap admin to a Managed-Identity-only connection without a
  # server rebuild (add an `azurerm_postgresql_flexible_server_active_directory_administrator`
  # resource then disable `password_auth_enabled` in a follow-up apply).
  # Until then the DSN in outputs.tf carries the admin password; rotate it
  # by re-applying with a new `administrator_password` and let Container
  # Apps roll to a new revision to pick up the refreshed Key Vault secret.
  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = true
    tenant_id                     = var.tenant_id
  }

  tags = var.tags

  lifecycle {
    # Zone is auto-assigned by Azure on the first apply and MUST NOT be
    # rewritten on subsequent applies - Postgres Flex only allows zone
    # swaps paired with a `standby_availability_zone` change (HA), which
    # this single-zone day-zero config does not use.
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_database" "primary" {
  name      = var.database_name
  server_id = azurerm_postgresql_flexible_server.primary.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# ---------------------------------------------------------------------------
# Firewall - allow Azure services (Container Apps outbound) to reach the
# server.
#
# Postgres Flex with `public_network_access_enabled = true` (provider
# default) accepts connections ONLY from IPs that match a firewall rule.
# Without this rule the Container App we wire in `infra/main.tf` fails
# every `_build_state_store` / `_build_operator_memory_store` /
# `_build_pattern_library` call at connection time - a silent degradation
# to in-memory fallback in `src/fdai/__main__.py`, which looks like the
# app works but has no persistence.
#
# `0.0.0.0` (start = end) is Azure's documented "AllowAllAzureServices"
# sentinel: it opens the server to any Microsoft-owned outbound IP, which
# covers every Container Apps replica in this subscription without pinning
# a specific address range that would drift when the platform reassigns.
#
# Prod hardening (post day-zero): add a delegated subnet on the Container
# Apps environment, set `delegated_subnet_id` on the server, and remove
# this rule so the server never sees a public IP. Documented in
# `docs/roadmap/deployment/deploy-and-onboard.md`.
# ---------------------------------------------------------------------------
resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure_services" {
  count            = var.allow_azure_services_firewall ? 1 : 0
  name             = "AllowAllAzureServices"
  server_id        = azurerm_postgresql_flexible_server.primary.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# pgvector extension enabled via server-side azure.extensions configuration
# (Azure Database for PostgreSQL supports 'vector' as of PostgreSQL 16).
resource "azurerm_postgresql_flexible_server_configuration" "vector_extension" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.primary.id
  value     = "VECTOR"
}


output "id" {
  description = "Server resource id."
  value       = azurerm_postgresql_flexible_server.primary.id
}

output "fqdn" {
  description = "Fully qualified domain name."
  value       = azurerm_postgresql_flexible_server.primary.fqdn
}

output "name" {
  description = "Server name."
  value       = azurerm_postgresql_flexible_server.primary.name
}

output "database_name" {
  description = "Application database name."
  value       = azurerm_postgresql_flexible_server_database.primary.name
}

# ---------------------------------------------------------------------------
# Application DSN.
#
# The platform root publishes this DSN for legacy jobs. Independent services
# add role-scoped secret references at their service roots.
#
# Marked `sensitive` because it embeds the bootstrap admin password. In
# production, forks rotate to AAD auth and swap this DSN for a token-based
# one; the shape (postgres connection URI) stays identical.
# ---------------------------------------------------------------------------
output "application_dsn" {
  description = "Postgres connection URI for the application database (sensitive; contains bootstrap admin password). Login + password are URL-encoded so a password containing `@` / `:` / `/` / `?` / `#` / `%` does not corrupt the URI."
  value       = "postgresql://${urlencode(var.administrator_login)}:${urlencode(var.administrator_password)}@${azurerm_postgresql_flexible_server.primary.fqdn}:5432/${var.database_name}?sslmode=require"
  sensitive   = true
}

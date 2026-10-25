variable "subscription_id" { type = string }
variable "tenant_id" { type = string }
variable "location" { type = string }
variable "prefix" { type = string }
variable "tags" { type = map(string) }
variable "network" {
  type = object({ vnet = string, apps = string, database = string, secrets = string })
}
variable "database_admin" {
  type = object({ object_id = string, display_name = string })
}
variable "database" {
  type = object({
    sku_name                     = string
    storage_mb                   = number
    backup_retention_days        = number
    geo_redundant_backup_enabled = bool
    zone_redundant               = bool
  })
}
variable "log_retention_days" { type = number }
variable "registry" { type = object({ id = string, server = string }) }
variable "image" { type = string }
variable "app_image" {
  type        = string
  default     = null
  description = "Retain the approved serving digest during migration; null uses image."
}
variable "ingress_cidrs" { type = set(string) }
variable "replicas" { type = object({ min = number, max = number }) }
variable "operator_auth" {
  type = object({
    profile           = string
    tenant_id         = string
    audience          = string
    spa_client_id     = string
    operator_scope    = string
    operator_ids      = set(string)
    service_object_id = optional(string)
    service_client_id = optional(string)
    service_role      = optional(string, "Catalog.Read")
    agent_principals = optional(list(object({
      installation_id = string
      object_id       = string
      client_id       = string
    })), [])
  })
  default = null
}
variable "enable_apps" {
  type    = bool
  default = false
}
variable "enable_bootstrap_job" {
  type    = bool
  default = false
}
variable "enable_migration_jobs" {
  type    = bool
  default = false
}
variable "operation_job" {
  type = object({
    operation              = string
    request_secret_version = string
    actor                  = string
  })
  default = null
}
variable "secret_versions" {
  type    = object({ database = optional(string), signing_key = optional(string) })
  default = {}
}
variable "catalog" {
  type = object({
    url                        = string
    token_scope                = string
    managed_identity_client_id = string
    release_public_key         = string
  })
  default = null
}

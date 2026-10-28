variable "subscription_id" { type = string }
variable "tenant_id" { type = string }
variable "location" { type = string }
variable "prefix" { type = string }
variable "resource_group_name" {
  type    = string
  default = null
}
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
variable "custom_domain" {
  type = object({
    hostname                  = string
    certificate_binding_type  = optional(string)
    certificate_id            = optional(string)
    redirect_default_hostname = optional(bool, false)
    dns_zone = optional(object({
      name                = string
      resource_group_name = string
      ttl                 = optional(number, 300)
    }))
  })
  default = null
}
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
    development_recovery = optional(object({
      profile                                   = string
      installation_id                           = string
      scope                                     = string
      operator_id                               = string
      previous_identity_key_id                  = string
      replacement_identity_public_key           = string
      authorized_at                             = string
      authorization_expires_at                  = string
      allow_single_owner_configuration_approval = bool
      reason                                    = string
    }))
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
    actor                  = string
    request_secret_version = optional(string)
    reason                 = optional(string)
  })
  default = null
}
variable "secret_versions" {
  type = object({
    database              = optional(string)
    signing_key           = optional(string)
    catalog_snapshot_key  = optional(string)
    catalog_timestamp_key = optional(string)
  })
  default = {}
}
variable "catalog" {
  type = object({
    url                        = string
    access                     = optional(string)
    token_scope                = optional(string)
    managed_identity_client_id = optional(string)
    release_public_key         = optional(string)
    trust = optional(object({
      mode           = string
      root_key_ids   = list(string)
      root_threshold = number
    }))
    check_interval_seconds = optional(number)
    adoption = optional(object({
      mode                     = optional(string)
      allowed_channels         = optional(list(string))
      max_new_releases         = optional(number)
      authorized_by            = optional(string)
      authorization_expires_at = optional(string)
    }))
  })
  default     = null
  description = "Pull-only catalog source and adoption policy; the hub-service module validates every field."
}

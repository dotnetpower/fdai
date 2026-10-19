terraform {
  required_version = ">= 1.9, < 2.0"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
  }
}

variable "kind" {
  type = string
  validation {
    condition     = contains(["release", "target"], var.kind)
    error_message = "The product root must select exactly one Hub kind."
  }
}
variable "prefix" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{3,10}$", var.prefix))
    error_message = "Use 4-11 lowercase letters/digits beginning with a letter."
  }
}
variable "tenant_id" {
  type        = string
  description = "Azure PostgreSQL and Key Vault service identity tenant, not browser login."
}
variable "location" {
  type = string
}
variable "tags" {
  type = map(string)
}
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
variable "log_retention_days" {
  type = number
}
variable "registry" {
  type = object({ id = string, server = string })
}
variable "image" {
  type = string
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.image))
    error_message = "Use the independently verified digest-pinned image for this product."
  }
}
variable "app_image" {
  type        = string
  default     = null
  description = "Optional digest-pinned serving image retained while image migrates the database. Null uses image."
  validation {
    condition     = var.app_image == null ? true : can(regex("^[^[:space:]@]+@sha256:[0-9a-f]{64}$", var.app_image))
    error_message = "Use an independently approved digest-pinned app image, or null to serve image."
  }
}
variable "ingress_cidrs" {
  type = set(string)
  validation {
    condition = length(var.ingress_cidrs) > 0 && alltrue([
      for cidr in var.ingress_cidrs : can(cidrhost(cidr, 0)) && !endswith(cidr, "/0")
    ])
    error_message = "Provide explicitly approved bounded ingress CIDRs."
  }
}
variable "replicas" {
  type = object({ min = number, max = number })
  validation {
    condition     = var.replicas.min >= 1 && var.replicas.max >= var.replicas.min
    error_message = "Keep at least one serving replica and a bounded maximum."
  }
}
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
  })
  default = null
  validation {
    condition = var.operator_auth == null ? true : (
      var.operator_auth.profile == "remote-development" &&
      length(var.operator_auth.operator_ids) > 0 &&
      var.operator_auth.audience != "" && var.operator_auth.spa_client_id != "" &&
      (var.kind == "release" || var.operator_auth.service_object_id == null)
    )
    error_message = "Supply complete verified operator bindings; Lifecycle Hub cannot admit a vendor service identity."
  }
}
variable "catalog" {
  type = object({
    url                        = string
    token_scope                = string
    managed_identity_client_id = string
    release_public_key         = string
  })
  default = null
  validation {
    condition     = var.catalog == null || var.kind == "target"
    error_message = "Only Lifecycle Hub can optionally consume an explicitly approved catalog."
  }
}
variable "enable_apps" {
  type    = bool
  default = false
}
variable "enable_bootstrap_job" {
  type        = bool
  default     = false
  description = "Temporary one-shot initialization identity, grants and manual Job. Remove after verified initialization."
}
variable "enable_migration_jobs" {
  type    = bool
  default = false
}
variable "secret_versions" {
  type    = object({ database = optional(string), signing_key = optional(string) })
  default = {}
  validation {
    condition = !(var.enable_apps || var.enable_migration_jobs) || (
      can(regex("^[0-9a-fA-F]{32}$", var.secret_versions.database)) &&
      (!var.enable_apps || can(regex("^[0-9a-fA-F]{32}$", var.secret_versions.signing_key)))
    )
    error_message = "Migration requires the DB secret version; serving also requires the signing-key version."
  }
}

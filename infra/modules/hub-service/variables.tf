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
variable "resource_group_name" {
  type        = string
  default     = null
  description = "Optional explicit resource group name; null uses rg-<prefix>-<kind>."
  validation {
    condition     = var.resource_group_name == null ? true : can(regex("^[A-Za-z0-9._()-]{1,90}$", var.resource_group_name))
    error_message = "Use a valid Azure resource group name, or null for rg-<prefix>-<kind>."
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
variable "custom_domain" {
  type = object({
    hostname                 = string
    certificate_binding_type = optional(string)
    certificate_id           = optional(string)
    dns_zone = optional(object({
      name                = string
      resource_group_name = string
      ttl                 = optional(number, 300)
    }))
  })
  default     = null
  description = "Optional custom HTTPS hostname, DNS records and certificate binding for the Hub Container App."
  validation {
    condition = var.custom_domain == null ? true : (
      length(var.custom_domain.hostname) <= 253 &&
      can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$", var.custom_domain.hostname)) &&
      !endswith(var.custom_domain.hostname, ".azurecontainerapps.io") &&
      (var.custom_domain.certificate_binding_type == null || contains(["Disabled", "SniEnabled"], var.custom_domain.certificate_binding_type)) &&
      (var.custom_domain.certificate_id == null || trimspace(var.custom_domain.certificate_id) != "") &&
      (var.custom_domain.certificate_binding_type != "Disabled" || var.custom_domain.certificate_id == null) &&
      (var.custom_domain.dns_zone == null ? true : (
        can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$", var.custom_domain.dns_zone.name)) &&
        trimspace(var.custom_domain.dns_zone.resource_group_name) != "" &&
        var.custom_domain.dns_zone.ttl >= 60 &&
        var.custom_domain.dns_zone.ttl <= 86400 &&
        endswith(var.custom_domain.hostname, ".${var.custom_domain.dns_zone.name}") &&
        can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", trimsuffix(var.custom_domain.hostname, ".${var.custom_domain.dns_zone.name}")))
      ))
    )
    error_message = "Use a lowercase subdomain hostname (not .azurecontainerapps.io); when dns_zone is set, hostname must be a direct single-label subdomain of dns_zone.name."
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
    # Release Hub only: serve the signed, content-free catalog export without a bearer token.
    public_catalog_export = optional(bool, false)
    agent_principals = optional(list(object({
      installation_id = string
      object_id       = string
      client_id       = string
    })), [])
  })
  default = null
  validation {
    condition = var.operator_auth == null ? true : (
      var.operator_auth.profile == "remote-development" &&
      length(var.operator_auth.operator_ids) > 0 &&
      var.operator_auth.audience != "" && var.operator_auth.spa_client_id != "" &&
      (var.kind == "release" || var.operator_auth.service_object_id == null) &&
      (var.kind == "target" || length(var.operator_auth.agent_principals) == 0)
    )
    error_message = "Supply complete verified operator bindings; Lifecycle Hub cannot admit a vendor service identity and Release Hub cannot admit Agents."
  }
  validation {
    condition     = var.operator_auth == null ? true : (var.kind == "release" || !var.operator_auth.public_catalog_export)
    error_message = "Only the Release Hub can serve the signed catalog export without a bearer token."
  }
}
variable "timestamp_renewal_check_seconds" {
  type        = number
  default     = 0
  description = "Release Hub only: interval for automatic freshness renewal of already published content. 0 disables it."
  validation {
    condition = var.timestamp_renewal_check_seconds == floor(var.timestamp_renewal_check_seconds) && (
      var.timestamp_renewal_check_seconds == 0 ||
      (var.timestamp_renewal_check_seconds >= 60 && var.timestamp_renewal_check_seconds <= 3600)
    )
    error_message = "Use 0 to disable renewal, or a whole number of seconds from 60 through 3600."
  }
  validation {
    condition     = var.timestamp_renewal_check_seconds == 0 || var.kind == "release"
    error_message = "Only the Release Hub renews the freshness of published content."
  }
}
variable "catalog" {
  type = object({
    url                        = string
    access                     = optional(string)
    token_scope                = optional(string)
    managed_identity_client_id = optional(string)
    release_public_key         = string
    check_interval_seconds     = optional(number)
    adoption = optional(object({
      mode                     = optional(string)
      allowed_channels         = optional(list(string))
      max_new_releases         = optional(number)
      authorized_by            = optional(string)
      authorization_expires_at = optional(string)
    }))
  })
  default     = null
  description = "Lifecycle Hub pull-only catalog source. Unset optional attributes are omitted from the Hub configuration."
  validation {
    condition     = var.catalog == null || var.kind == "target"
    error_message = "Only Lifecycle Hub can optionally consume an explicitly approved catalog."
  }
  validation {
    condition = var.catalog == null ? true : (
      can(regex("^https://[^/?#@:]+(:443)?/v1/catalog/export$", var.catalog.url)) &&
      contains(["managed-identity", "anonymous"], coalesce(var.catalog.access, "managed-identity"))
    )
    error_message = "Use one HTTPS /v1/catalog/export URL and access of managed-identity or anonymous."
  }
  validation {
    condition = var.catalog == null ? true : (
      coalesce(var.catalog.access, "managed-identity") == "anonymous" ? (
        var.catalog.token_scope == null && var.catalog.managed_identity_client_id == null
        ) : (
        try(trimspace(var.catalog.token_scope) != "", false) &&
        try(endswith(var.catalog.token_scope, "/.default"), false) &&
        try(trimspace(var.catalog.managed_identity_client_id) != "", false)
      )
    )
    error_message = "Managed-identity access requires token_scope ending in /.default and managed_identity_client_id; anonymous access must omit both."
  }
  validation {
    condition = try(var.catalog.check_interval_seconds, null) == null ? true : (
      var.catalog.check_interval_seconds == floor(var.catalog.check_interval_seconds) && (
        var.catalog.check_interval_seconds == 0 ||
        (var.catalog.check_interval_seconds >= 300 && var.catalog.check_interval_seconds <= 86400)
      )
    )
    error_message = "Use check_interval_seconds of 0 to disable checks, or a whole number from 300 through 86400."
  }
  validation {
    condition = try(var.catalog.adoption, null) == null ? true : (
      contains(["review", "auto"], coalesce(var.catalog.adoption.mode, "review")) &&
      alltrue([
        for name in coalesce(var.catalog.adoption.allowed_channels, []) :
        can(regex("^[A-Za-z][A-Za-z0-9_-]{0,63}$", name))
      ]) &&
      length(toset(coalesce(var.catalog.adoption.allowed_channels, []))) == length(coalesce(var.catalog.adoption.allowed_channels, [])) &&
      (
        var.catalog.adoption.max_new_releases == null ? true : (
          var.catalog.adoption.max_new_releases == floor(var.catalog.adoption.max_new_releases) &&
          var.catalog.adoption.max_new_releases >= 0 && var.catalog.adoption.max_new_releases <= 64
        )
      )
    )
    error_message = "Adoption needs mode review or auto, unique canonical channel names, and max_new_releases from 0 through 64."
  }
  validation {
    condition = try(var.catalog.adoption, null) == null ? true : (
      var.catalog.adoption.authorized_by == null ? true : (
        trimspace(var.catalog.adoption.authorized_by) != "" && length(var.catalog.adoption.authorized_by) <= 160
      )
    )
    error_message = "authorized_by must be a non-blank attribution of at most 160 characters."
  }
  validation {
    condition = try(var.catalog.adoption, null) == null ? true : (
      var.catalog.adoption.authorization_expires_at == null ? true : (
        can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]+)?([Zz]|[+-][0-9]{2}:[0-9]{2})$", var.catalog.adoption.authorization_expires_at)) &&
        can(timeadd(var.catalog.adoption.authorization_expires_at, "0s"))
      )
    )
    error_message = "authorization_expires_at must be an ISO-8601 timestamp with an explicit timezone, such as 2027-01-31T00:00:00Z."
  }
  validation {
    condition = try(var.catalog.adoption, null) == null ? true : (
      coalesce(var.catalog.adoption.mode, "review") != "auto" || (
        try(trimspace(var.catalog.adoption.authorized_by) != "", false) &&
        var.catalog.adoption.authorization_expires_at != null
      )
    )
    error_message = "Automatic adoption requires both authorized_by and authorization_expires_at."
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
variable "operation_job" {
  type = object({
    operation              = string
    request_secret_version = string
    actor                  = string
  })
  default = null
  validation {
    condition = var.operation_job == null ? true : (
      contains(
        var.kind == "release" ? ["publish-release"] : ["import-catalog", "recompute"],
        var.operation_job.operation,
      ) &&
      trimspace(var.operation_job.request_secret_version) != "" &&
      trimspace(var.operation_job.actor) != ""
    )
    error_message = "Choose one product-owned operation with an exact request secret version and attributed actor."
  }
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

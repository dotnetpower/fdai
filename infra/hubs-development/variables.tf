variable "subscription_id" {
  type = string
}
variable "tenant_id" {
  type = string
}
variable "location" {
  type = string
}
variable "prefix" {
  type        = string
  description = "Unique synthetic deployment prefix, also used for globally unique vault and database names."
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{3,10}$", var.prefix))
    error_message = "Use 4-11 lowercase ASCII letters/digits beginning with a letter."
  }
}
variable "operator_object_ids" {
  type = set(string)
  validation {
    condition     = length(var.operator_object_ids) > 0
    error_message = "Explicit operator object IDs are required."
  }
}
variable "operator_cidrs" {
  type = set(string)
  validation {
    condition = length(var.operator_cidrs) > 0 && alltrue([
      for cidr in var.operator_cidrs : can(cidrhost(cidr, 0)) && !endswith(cidr, "/0")
    ])
    error_message = "Provide approved operator source CIDRs; unrestricted ingress is not accepted."
  }
}
variable "database_admin" {
  type = object({ object_id = string, display_name = string })
}
variable "registry" {
  type        = object({ id = string, server = string })
  description = "Existing approved image registry. This root never builds or publishes artifacts."
}
variable "images" {
  type = map(string)
  validation {
    condition = alltrue([
      for kind in ["release", "target"] : can(regex("@sha256:[0-9a-f]{64}$", var.images[kind]))
    ])
    error_message = "Supply independently built and verified digest-pinned release and target images."
  }
}
variable "release_public_key" {
  type        = string
  default     = null
  description = "Independently approved DEVELOPMENT Ed25519 public PEM. Not a production root ceremony. Name exactly one of this or catalog_trust."
  validation {
    condition     = var.release_public_key == null ? true : startswith(var.release_public_key, "-----BEGIN PUBLIC KEY-----")
    error_message = "Supply a separately verified public key, never a private key."
  }
  validation {
    condition     = (var.release_public_key == null) != (var.catalog_trust == null)
    error_message = "Name exactly one catalog trust: release_public_key or catalog_trust."
  }
}
variable "catalog_trust" {
  type = object({
    mode           = string
    root_key_ids   = list(string)
    root_threshold = number
  })
  default     = null
  description = "Signed TUF catalog roles: the pinned initial root's offline key ids and threshold. Replaces release_public_key."
  validation {
    condition = var.catalog_trust == null ? true : (
      var.catalog_trust.mode == "tuf" &&
      length(var.catalog_trust.root_key_ids) >= 1 &&
      length(var.catalog_trust.root_key_ids) <= 16 &&
      alltrue([for id in var.catalog_trust.root_key_ids : can(regex("^ed25519-[0-9a-f]{64}$", id))]) &&
      length(toset(var.catalog_trust.root_key_ids)) == length(var.catalog_trust.root_key_ids) &&
      var.catalog_trust.root_threshold == floor(var.catalog_trust.root_threshold) &&
      var.catalog_trust.root_threshold >= 1 &&
      var.catalog_trust.root_threshold <= length(var.catalog_trust.root_key_ids)
    )
    error_message = "Catalog trust mode tuf needs 1 to 16 unique ed25519 root key ids and a whole threshold from 1 through the number of keys."
  }
}
variable "catalog_roles" {
  type = object({
    timestamp_ttl_seconds = optional(number)
    snapshot_ttl_seconds  = optional(number)
  })
  default     = null
  description = "Release Hub serves signed TUF snapshot and timestamp metadata. Needs the catalog_snapshot_key and catalog_timestamp_key secret versions for the release Hub."
  validation {
    condition = try(var.catalog_roles.timestamp_ttl_seconds, null) == null ? true : (
      var.catalog_roles.timestamp_ttl_seconds == floor(var.catalog_roles.timestamp_ttl_seconds) &&
      var.catalog_roles.timestamp_ttl_seconds >= 3600 && var.catalog_roles.timestamp_ttl_seconds <= 604800
    )
    error_message = "Use a whole timestamp validity from 3600 through 604800 seconds."
  }
  validation {
    condition = try(var.catalog_roles.snapshot_ttl_seconds, null) == null ? true : (
      var.catalog_roles.snapshot_ttl_seconds == floor(var.catalog_roles.snapshot_ttl_seconds) &&
      var.catalog_roles.snapshot_ttl_seconds >= 3600 && var.catalog_roles.snapshot_ttl_seconds <= 5184000
    )
    error_message = "Use a whole snapshot validity from 3600 through 5184000 seconds."
  }
  validation {
    condition = var.catalog_roles == null ? true : (
      coalesce(var.catalog_roles.snapshot_ttl_seconds, 604800) >= coalesce(var.catalog_roles.timestamp_ttl_seconds, 86400)
    )
    error_message = "The snapshot validity must outlast the timestamp validity."
  }
}
variable "catalog_check_interval_seconds" {
  type        = number
  default     = null
  description = "Lifecycle Hub catalog check interval. Null keeps the Hub default; 0 disables checks; otherwise 300-86400."
  validation {
    condition = var.catalog_check_interval_seconds == null ? true : (
      var.catalog_check_interval_seconds == floor(var.catalog_check_interval_seconds) && (
        var.catalog_check_interval_seconds == 0 ||
        (var.catalog_check_interval_seconds >= 300 && var.catalog_check_interval_seconds <= 86400)
      )
    )
    error_message = "Use 0 to disable catalog checks, or a whole number of seconds from 300 through 86400."
  }
}
variable "catalog_adoption" {
  type = object({
    mode                     = optional(string)
    allowed_channels         = optional(list(string))
    max_new_releases         = optional(number)
    authorized_by            = optional(string)
    authorization_expires_at = optional(string)
  })
  default     = null
  description = "Lifecycle Hub adoption policy. Null keeps review mode. Automatic mode needs an attributed, expiring authorization."
  validation {
    condition = var.catalog_adoption == null ? true : (
      contains(["review", "auto"], coalesce(var.catalog_adoption.mode, "review")) &&
      alltrue([
        for name in coalesce(var.catalog_adoption.allowed_channels, []) :
        can(regex("^[A-Za-z][A-Za-z0-9_-]{0,63}$", name))
      ]) &&
      length(toset(coalesce(var.catalog_adoption.allowed_channels, []))) == length(coalesce(var.catalog_adoption.allowed_channels, [])) &&
      (
        var.catalog_adoption.max_new_releases == null ? true : (
          var.catalog_adoption.max_new_releases == floor(var.catalog_adoption.max_new_releases) &&
          var.catalog_adoption.max_new_releases >= 0 && var.catalog_adoption.max_new_releases <= 64
        )
      )
    )
    error_message = "Adoption needs mode review or auto, unique canonical channel names, and max_new_releases from 0 through 64."
  }
  validation {
    condition = var.catalog_adoption == null ? true : (
      (var.catalog_adoption.authorized_by == null ? true : (
        trimspace(var.catalog_adoption.authorized_by) != "" && length(var.catalog_adoption.authorized_by) <= 160
      )) &&
      (var.catalog_adoption.authorization_expires_at == null ? true : (
        can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]+)?([Zz]|[+-][0-9]{2}:[0-9]{2})$", var.catalog_adoption.authorization_expires_at)) &&
        can(timeadd(var.catalog_adoption.authorization_expires_at, "0s"))
      ))
    )
    error_message = "authorized_by must be non-blank (at most 160 characters) and authorization_expires_at must be an ISO-8601 timestamp with an explicit timezone."
  }
  validation {
    condition = var.catalog_adoption == null ? true : (
      coalesce(var.catalog_adoption.mode, "review") != "auto" || (
        try(trimspace(var.catalog_adoption.authorized_by) != "", false) &&
        var.catalog_adoption.authorization_expires_at != null
      )
    )
    error_message = "Automatic adoption requires both authorized_by and authorization_expires_at."
  }
}
variable "timestamp_renewal_check_seconds" {
  type        = number
  default     = 0
  description = "Release Hub automatic freshness renewal of published content. 0 disables it; otherwise 60-3600."
  validation {
    condition = var.timestamp_renewal_check_seconds == floor(var.timestamp_renewal_check_seconds) && (
      var.timestamp_renewal_check_seconds == 0 ||
      (var.timestamp_renewal_check_seconds >= 60 && var.timestamp_renewal_check_seconds <= 3600)
    )
    error_message = "Use 0 to disable renewal, or a whole number of seconds from 60 through 3600."
  }
}
variable "enable_apps" {
  type        = bool
  default     = false
  description = "Enable only after per-Hub DB roles, signing-key secrets and explicit migrations exist."
}
variable "enable_migration_jobs" {
  type        = bool
  default     = false
  description = "Create manual-only migration jobs after private secret and DB-role provisioning."
}
variable "secret_versions" {
  type = map(object({
    signing_key           = string
    database              = string
    catalog_snapshot_key  = optional(string)
    catalog_timestamp_key = optional(string)
  }))
  default     = {}
  description = "Version IDs only, after independent safe provisioning. Never supply secret values to Terraform."
  validation {
    condition = var.catalog_roles == null || !var.enable_apps || (
      can(regex("^[0-9a-fA-F]{32}$", try(var.secret_versions["release"].catalog_snapshot_key, ""))) &&
      can(regex("^[0-9a-fA-F]{32}$", try(var.secret_versions["release"].catalog_timestamp_key, "")))
    )
    error_message = "Serving signed catalog roles requires separate snapshot-key and timestamp-key secret versions for the release Hub."
  }
}

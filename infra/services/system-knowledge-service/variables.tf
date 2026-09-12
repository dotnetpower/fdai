variable "enabled" {
  description = "Explicit protected transition for the complete independent service."
  type        = bool
  default     = false
}

variable "name" {
  description = "System Knowledge Service Container App name."
  type        = string
}

variable "bot_name" {
  description = "Dedicated Azure Bot resource name."
  type        = string
}

variable "image" {
  description = "Promoted System Knowledge Service OCI image pinned by digest."
  type        = string
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.image))
    error_message = "image must be pinned by a lowercase SHA-256 digest."
  }
}

variable "source_revision" {
  description = "Exact FDAI source revision embedded in the packaged knowledge catalog."
  type        = string
  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.source_revision))
    error_message = "source_revision must be a lowercase 40-character Git object id."
  }
}

variable "platform" {
  description = "Existing private FDAI platform resources used by the independent service."
  type = object({
    resource_group_name          = string
    location                     = string
    container_app_environment_id = string
    acr_login_server             = string
    acr_id                       = string
    key_vault_id                 = string
    claim_storage_account_id     = string
    claim_storage_blob_endpoint  = string
  })
}

variable "teams" {
  description = "Deployment-owned Teams transport, destinations, and trust roots."
  type = object({
    transport               = string
    tenant_id               = string
    team_ids                = list(string)
    channel_ids             = list(string)
    allowed_service_urls    = optional(list(string), [])
    jwks_url                = optional(string, "")
    principal_map_secret_id = string
    outgoing_hmac_secret_id = optional(string)
  })
  sensitive = true
  validation {
    condition = (
      contains(["bot_framework", "outgoing_webhook"], var.teams.transport) &&
      trimspace(var.teams.tenant_id) != "" &&
      length(var.teams.team_ids) > 0 &&
      length(var.teams.team_ids) <= 100 &&
      length(var.teams.team_ids) == length(distinct(var.teams.team_ids)) &&
      length(var.teams.channel_ids) > 0 &&
      length(var.teams.channel_ids) <= 100 &&
      length(var.teams.channel_ids) == length(distinct(var.teams.channel_ids)) &&
      startswith(var.teams.principal_map_secret_id, "https://") &&
      (
        var.teams.transport == "bot_framework"
        ? (
          length(var.teams.allowed_service_urls) > 0 &&
          length(var.teams.allowed_service_urls) <= 32 &&
          length(var.teams.allowed_service_urls) == length(distinct(var.teams.allowed_service_urls)) &&
          startswith(var.teams.jwks_url, "https://") &&
          var.teams.outgoing_hmac_secret_id == null
        )
        : (
          length(var.teams.team_ids) == 1 &&
          length(var.teams.allowed_service_urls) == 0 &&
          var.teams.jwks_url == "" &&
          (
            var.teams.outgoing_hmac_secret_id == null
            || startswith(var.teams.outgoing_hmac_secret_id, "https://")
          )
        )
      )
    )
    error_message = "teams must contain one valid transport with bounded destinations and matching trust references."
  }
}

variable "claim_store" {
  description = "Existing private Blob account and service-owned claim container."
  type = object({
    container_name = string
  })
  default = {
    container_name = "system-knowledge-claims"
  }
  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$", var.claim_store.container_name))
    error_message = "claim_store.container_name must be a valid private Blob container name."
  }
}

variable "health" {
  description = "System Knowledge Service HTTP health contract."
  type = object({
    port                    = number
    liveness_path           = string
    readiness_path          = string
    startup_path            = optional(string)
    interval_seconds        = optional(number, 30)
    timeout_seconds         = optional(number, 3)
    failure_count_threshold = optional(number, 3)
    startup_failure_count   = optional(number, 60)
  })
  default = {
    port           = 8015
    liveness_path  = "/health/live"
    readiness_path = "/health/ready"
    startup_path   = "/health/ready"
  }
}

variable "rollback" {
  description = "Revision rollback contract consumed by protected deployment."
  type = object({
    strategy                 = string
    previous_image           = string
    max_unavailable_replicas = optional(number, 0)
  })
  validation {
    condition = (
      contains(["previous-revision", "image-redeploy"], var.rollback.strategy) &&
      can(regex("@sha256:[0-9a-f]{64}$", var.rollback.previous_image))
    )
    error_message = "rollback must name an allowed strategy and digest-pinned previous image."
  }
}

variable "runtime_env" {
  description = "Deployment environment, independent of authority."
  type        = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.runtime_env)
    error_message = "runtime_env must be dev, staging, or prod."
  }
}

variable "scaling" {
  description = "Single-replica ceiling retained until distributed claim evidence is validated."
  type = object({
    min_replicas = number
    max_replicas = number
    cpu          = number
    memory       = string
  })
  default = {
    min_replicas = 1
    max_replicas = 1
    cpu          = 0.5
    memory       = "1Gi"
  }
  validation {
    condition     = var.scaling.min_replicas == 1 && var.scaling.max_replicas == 1
    error_message = "System Knowledge Service must retain exactly one replica before promotion."
  }
}

variable "tags" {
  description = "Deployment-supplied generic resource tags."
  type        = map(string)
  default     = {}
}

variable "name" {
  description = "Code-security worker Container App name."
  type        = string
}

variable "platform" {
  description = "Shared platform outputs supplied by the platform state owner."
  type = object({
    resource_group_name          = string
    container_app_environment_id = string
    acr_login_server             = string
    kafka_bootstrap_servers      = string
  })

  validation {
    condition     = trimspace(var.platform.kafka_bootstrap_servers) != ""
    error_message = "platform.kafka_bootstrap_servers must bind the deployed event transport."
  }
}

variable "image" {
  description = "Digest-pinned code-security scanner image."
  type        = string

  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.image))
    error_message = "image must be pinned by sha256 digest."
  }
}

variable "identity" {
  description = "Non-executor worker identity used for image pull and Key Vault references."
  type        = object({ resource_id = string, client_id = string })

  validation {
    condition = (
      trimspace(var.identity.resource_id) != "" &&
      trimspace(var.identity.client_id) != ""
    )
    error_message = "identity must bind one non-executor managed identity."
  }
}

variable "database" {
  description = "Restricted code-security worker database binding."
  type        = object({ dsn_secret_id = string, host = string, role = string })
  sensitive   = true

  validation {
    condition = (
      trimspace(var.database.dsn_secret_id) != "" &&
      trimspace(var.database.host) != "" &&
      var.database.role == "fdai_code_security_worker"
    )
    error_message = "database must bind a DSN secret, host, and fdai_code_security_worker role."
  }
}

variable "github" {
  description = "Read-only GitHub App or token secret reference used for repository acquisition."
  type = object({
    app_client_id             = optional(string, "")
    app_installation_id       = optional(string, "")
    app_private_key_secret_id = optional(string, "")
    token_secret_id           = optional(string, "")
  })
  sensitive = true

  validation {
    condition = (
      (
        trimspace(var.github.app_client_id) != "" &&
        trimspace(var.github.app_installation_id) != "" &&
        trimspace(var.github.app_private_key_secret_id) != "" &&
        trimspace(var.github.token_secret_id) == ""
        ) || (
        trimspace(var.github.app_client_id) == "" &&
        trimspace(var.github.app_installation_id) == "" &&
        trimspace(var.github.app_private_key_secret_id) == "" &&
        trimspace(var.github.token_secret_id) != ""
      )
    )
    error_message = "github must bind either one complete GitHub App reference or one token secret reference."
  }
}

variable "cache" {
  description = "Existing Container Apps environment storage containing the offline scanner cache."
  type = object({
    storage_name = string
    path         = optional(string, "/cache")
  })

  validation {
    condition = (
      trimspace(var.cache.storage_name) != "" &&
      (var.cache.path == "/cache" || startswith(var.cache.path, "/cache/")) &&
      !strcontains(var.cache.path, "..")
    )
    error_message = "cache requires an existing storage binding and a non-traversing path beneath /cache."
  }
}

variable "runtime_env" {
  description = "Deployment environment, independent of worker authority."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.runtime_env)
    error_message = "runtime_env must be dev, staging, or prod."
  }
}

variable "worker" {
  description = "Bounded serialized worker intervals and batch limits."
  type = object({
    request_interval_seconds  = optional(number, 5)
    schedule_interval_seconds = optional(number, 300)
    max_requests              = optional(number, 20)
    max_repositories          = optional(number, 5)
  })
  default = {}

  validation {
    condition = (
      var.worker.request_interval_seconds >= 1 &&
      var.worker.request_interval_seconds <= 60 &&
      var.worker.schedule_interval_seconds >= 60 &&
      var.worker.schedule_interval_seconds <= 86400 &&
      var.worker.max_requests >= 1 &&
      var.worker.max_requests <= 20 &&
      var.worker.max_repositories >= 1 &&
      var.worker.max_repositories <= 20
    )
    error_message = "worker intervals and batch limits must remain within the CLI bounds."
  }
}

variable "resources" {
  description = "Fixed single-replica worker resources."
  type        = object({ cpu = number, memory = string })
  default     = { cpu = 2, memory = "4Gi" }
}

variable "tags" {
  description = "Deployment-supplied generic resource tags."
  type        = map(string)
  default     = {}
}

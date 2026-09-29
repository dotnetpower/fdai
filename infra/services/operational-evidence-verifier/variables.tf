variable "name" {
  description = "Operational evidence verifier Container App name."
  type        = string
  validation {
    condition     = can(regex("-evidence-verifier$", var.name))
    error_message = "Operational evidence verifier name must end with -evidence-verifier."
  }
}

variable "platform" {
  description = "Shared platform outputs supplied by the platform state owner."
  type = object({
    resource_group_name          = string
    container_app_environment_id = string
    acr_login_server             = string
    acr_resource_id              = string
  })
}

variable "image" {
  description = "Promoted verifier-capable Core OCI image."
  type        = string
}

variable "identity" {
  description = "Dedicated verifier workload identity."
  type = object({
    resource_id  = string
    client_id    = string
    principal_id = string
  })
  validation {
    condition     = alltrue([for value in values(var.identity) : trimspace(value) != ""])
    error_message = "The verifier requires one dedicated identity resource, client, and principal id."
  }
}

variable "database" {
  description = "Role-scoped verifier proof-store DSN secret reference."
  type        = object({ dsn_secret_id = string, dsn_secret_scope = string, host = string, role = string })
  sensitive   = true
  validation {
    condition     = trimspace(var.database.host) != "" && trimspace(var.database.role) != ""
    error_message = "database.host and database.role are required."
  }
}

variable "registries" {
  description = "Pinned operational evidence trust and grant registries."
  type = object({
    trust_path = string
    trust_pin  = string
    grant_path = string
    grant_pin  = string
  })
  validation {
    condition     = alltrue([for value in values(var.registries) : trimspace(value) != ""])
    error_message = "Every operational evidence registry path and pin is required."
  }
}

variable "anchors_json" {
  description = "Deployment-owned anchor binding JSON."
  type        = string
  sensitive   = true
  validation {
    condition     = can(jsondecode(var.anchors_json))
    error_message = "anchors_json must be valid JSON."
  }
}

variable "executor_anchors" {
  description = "Explicit executor-class principals used by verifier preflight."
  type = object({
    core_runtime_executor           = string
    isolated_executor               = string
    dev_operations_gateway_executor = string
    vertical_effect_executors       = set(string)
    deploy_runner                   = string
  })
  validation {
    condition = (
      trimspace(var.executor_anchors.core_runtime_executor) != "" &&
      trimspace(var.executor_anchors.isolated_executor) != "" &&
      trimspace(var.executor_anchors.dev_operations_gateway_executor) != "" &&
      trimspace(var.executor_anchors.deploy_runner) != "" &&
      length(var.executor_anchors.vertical_effect_executors) > 0 &&
      length(distinct(concat([
        var.executor_anchors.core_runtime_executor,
        var.executor_anchors.isolated_executor,
        var.executor_anchors.dev_operations_gateway_executor,
        var.executor_anchors.deploy_runner,
      ], tolist(var.executor_anchors.vertical_effect_executors)))) == 4 + length(var.executor_anchors.vertical_effect_executors)
    )
    error_message = "Every executor-class anchor must be explicit and distinct."
  }
}

variable "caller_auth" {
  description = "Short-lived Entra token validation contract for the registered producer workload."
  type        = object({ issuer = string, audience = string, jwks_json = string })
  sensitive   = true
  validation {
    condition     = startswith(var.caller_auth.issuer, "https://") && trimspace(var.caller_auth.audience) != "" && can(jsondecode(var.caller_auth.jwks_json))
    error_message = "caller_auth requires HTTPS issuer, audience, and JWKS JSON."
  }
}

variable "own_role_readback" {
  description = "Scopes used for startup own-role readback."
  type = object({
    scopes = set(string)
  })
  validation {
    condition     = length(var.own_role_readback.scopes) > 0
    error_message = "Own-role readback requires at least one observed scope."
  }
}

variable "health" {
  description = "Verifier HTTP readiness contract."
  type = object({
    port                    = number
    liveness_path           = optional(string)
    readiness_path          = string
    startup_path            = optional(string)
    interval_seconds        = optional(number, 30)
    timeout_seconds         = optional(number, 3)
    failure_count_threshold = optional(number, 3)
    startup_failure_count   = optional(number, 30)
  })
  default = { port = 8791, liveness_path = null, readiness_path = "/v1/operational-evidence/readiness", startup_path = "/v1/operational-evidence/readiness" }
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
  description = "Verifier replica and resource limits."
  type        = object({ min_replicas = number, max_replicas = number, cpu = number, memory = string })
  default     = { min_replicas = 1, max_replicas = 1, cpu = 0.25, memory = "0.5Gi" }
  validation {
    condition     = var.scaling.min_replicas == 1 && var.scaling.max_replicas == 1
    error_message = "The verifier requires exactly one replica until insert-only concurrency is proven."
  }
}

variable "tags" {
  description = "Deployment-supplied generic resource tags."
  type        = map(string)
  default     = {}
}

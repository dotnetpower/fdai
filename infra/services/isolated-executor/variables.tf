variable "name" {
  description = "Isolated Executor Container App name."
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
}
variable "image" {
  description = "Promoted isolated Executor OCI image."
  type        = string
}
variable "identity" {
  description = "Transport and cutover-only action identities supplied by the identity state owner."
  type = object({
    transport_resource_id  = string
    transport_client_id    = string
    change_resource_id     = string
    change_client_id       = string
    resilience_resource_id = string
    resilience_client_id   = string
    finops_resource_id     = string
    finops_client_id       = string
  })
  validation {
    condition = alltrue([
      for value in values(var.identity) : trimspace(value) != ""
    ])
    error_message = "Executor identity inputs require transport and all three vertical resource and client IDs."
  }
}
variable "event_topics" {
  description = "Versioned Executor transport entities."
  type        = object({ command = string, receipt = string, dlq_suffix = string })
}
variable "database" {
  description = "Role-scoped Executor database secret reference."
  type        = object({ dsn_secret_id = string, role = string })
  sensitive   = true
}
variable "health" {
  description = "Executor internal health contract."
  type = object({
    port                    = number
    liveness_path           = string
    readiness_path          = string
    startup_path            = optional(string)
    interval_seconds        = optional(number, 30)
    timeout_seconds         = optional(number, 3)
    failure_count_threshold = optional(number, 3)
    startup_failure_count   = optional(number, 30)
  })
  default = { port = 8000, liveness_path = "/live", readiness_path = "/ready", startup_path = "/live" }
}
variable "rollback" {
  description = "Authority-aware rollback contract consumed by the deployment orchestrator."
  type = object({
    strategy                 = string
    previous_image           = string
    authority_fallback       = string
    max_unavailable_replicas = optional(number, 0)
  })
  validation {
    condition     = contains(["previous-revision", "image-redeploy"], var.rollback.strategy) && var.rollback.authority_fallback == "core-in-process"
    error_message = "Executor rollback requires a supported revision strategy and the core-in-process authority fallback."
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
variable "authority" {
  description = "Explicit isolated-authority cutover inputs."
  type = object({
    cutover                         = bool
    dev_operations_gateway_url      = string
    dev_operations_gateway_audience = string
  })
  validation {
    condition = !var.authority.cutover || (
      var.authority.dev_operations_gateway_url != "" &&
      var.authority.dev_operations_gateway_audience != ""
    )
    error_message = "Authority cutover requires the governed gateway URL and audience."
  }
}
variable "scaling" {
  description = "Executor replica and resource limits."
  type        = object({ min_replicas = number, max_replicas = number, cpu = number, memory = string })
  default     = { min_replicas = 1, max_replicas = 1, cpu = 0.25, memory = "0.5Gi" }
  validation {
    condition     = var.scaling.min_replicas == 1 && var.scaling.max_replicas == 1
    error_message = "Isolated Executor requires exactly one replica until partition-safe concurrency is proven."
  }
}
variable "tags" {
  description = "Deployment-supplied generic resource tags."
  type        = map(string)
  default     = {}
}

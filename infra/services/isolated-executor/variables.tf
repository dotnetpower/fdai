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
  type        = object({ dsn_secret_id = string, host = string, role = string })
  sensitive   = true
  validation {
    condition     = trimspace(var.database.host) != ""
    error_message = "database.host must contain the non-secret PostgreSQL endpoint identity."
  }
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
    legacy_unbound_transition       = optional(bool, false)
    dev_operations_gateway_url      = string
    dev_operations_gateway_audience = string
  })
  validation {
    condition = (
      !var.authority.legacy_unbound_transition || var.authority.cutover
      ) && (
      !var.authority.cutover || (
        var.authority.dev_operations_gateway_url != "" &&
        var.authority.dev_operations_gateway_audience != ""
      )
    )
    error_message = "Authority cutover requires the governed gateway, and legacy transition requires cutover."
  }
}
variable "kubernetes_direct_api" {
  description = "Optional exact Kubernetes API binding using an attached Thor identity and public CA only."
  type = object({
    api_server         = string
    cluster_ref        = string
    audience           = string
    ca_pem             = string
    allowed_namespaces = set(string)
  })
  default = null
  validation {
    condition = var.kubernetes_direct_api == null ? true : (
      var.authority.cutover &&
      can(regex("^https://[A-Za-z0-9.-]+(:[0-9]+)?/?$", var.kubernetes_direct_api.api_server)) &&
      length(trimspace(var.kubernetes_direct_api.cluster_ref)) > 0 &&
      length(var.kubernetes_direct_api.cluster_ref) <= 1024 &&
      length(trimspace(var.kubernetes_direct_api.audience)) > 0 &&
      length(var.kubernetes_direct_api.audience) <= 512 &&
      length(var.kubernetes_direct_api.ca_pem) <= 65536 &&
      startswith(trimspace(var.kubernetes_direct_api.ca_pem), "-----BEGIN CERTIFICATE-----") &&
      endswith(trimspace(var.kubernetes_direct_api.ca_pem), "-----END CERTIFICATE-----") &&
      !strcontains(var.kubernetes_direct_api.ca_pem, "PRIVATE KEY") &&
      length(var.kubernetes_direct_api.allowed_namespaces) > 0 &&
      length(var.kubernetes_direct_api.allowed_namespaces) <= 32 &&
      alltrue([for namespace in var.kubernetes_direct_api.allowed_namespaces : can(regex("^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$", namespace))])
    )
    error_message = "Kubernetes binding requires existing authority cutover, exact HTTPS origin, public CA, and bounded explicit namespaces."
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

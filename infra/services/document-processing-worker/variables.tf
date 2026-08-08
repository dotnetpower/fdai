variable "name" {
  description = "Document processing worker Container App name."
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
  description = "Promoted document processing worker OCI image."
  type        = string
}
variable "identity" {
  description = "Worker workload identity outputs supplied by the identity state owner."
  type        = object({ resource_id = string, client_id = string })
}
variable "event_topics" {
  description = "Event Hub entities consumed and published by the worker."
  type        = object({ pipeline_stages = string, pantheon_objects = string })
}
variable "database" {
  description = "Role-scoped worker database secret reference."
  type        = object({ dsn_secret_id = string, role = string })
  sensitive   = true
}
variable "document_store" {
  description = "Shared document storage outputs supplied by the platform state owner."
  type = object({
    account_name        = string
    account_url         = string
    source_file_system  = string
    derived_file_system = string
  })
}
variable "health" {
  description = "Worker internal health contract."
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
  description = "Revision rollback contract consumed by the deployment orchestrator."
  type        = object({ strategy = string, previous_image = string, max_unavailable_replicas = optional(number, 0) })
  validation {
    condition     = contains(["previous-revision", "image-redeploy"], var.rollback.strategy)
    error_message = "rollback.strategy must be previous-revision or image-redeploy."
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
variable "embedding" {
  description = "Embedding provider contract used by the document worker."
  type        = object({ endpoint = string, deployment = string })
}
variable "scaling" {
  description = "Worker replica and resource limits."
  type        = object({ min_replicas = number, max_replicas = number, cpu = number, memory = string })
  default     = { min_replicas = 1, max_replicas = 2, cpu = 1, memory = "2Gi" }
}
variable "tags" {
  description = "Deployment-supplied generic resource tags."
  type        = map(string)
  default     = {}
}

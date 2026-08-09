variable "name" {
  description = "Core control-plane Container App name."
  type        = string
}

variable "platform" {
  description = "Shared platform outputs supplied by the platform state owner."
  type = object({
    resource_group_name                 = string
    container_app_environment_id        = string
    acr_login_server                    = string
    kafka_bootstrap_servers             = string
    operational_kafka_bootstrap_servers = optional(string, "")
  })
}

variable "image" {
  description = "Promoted Core OCI image. Pin by digest for protected environments."
  type        = string
}

variable "bootstrap" {
  description = "Required provider and PostgreSQL coordinates consumed by the Core bootstrap."
  type = object({
    azure_tenant_id       = string
    azure_subscription_id = string
    azure_region          = string
    postgres_host         = string
    postgres_database     = string
  })
}

variable "identity" {
  description = "Service-owned workload identity outputs supplied by the identity state owner."
  type = object({
    resource_id        = string
    client_id          = string
    extra_resource_ids = optional(list(string), [])
  })
}

variable "event_topics" {
  description = "Event Hub entity names owned by the shared event-bus state."
  type = object({
    events           = string
    executor_command = string
    executor_receipt = string
    startup_probe    = optional(string, "runtime.startup.probe")
  })
}

variable "database" {
  description = "Role-scoped database secret reference supplied by the state-store state owner."
  type = object({
    dsn_secret_id = string
    role          = string
  })
  sensitive = true
}

variable "health" {
  description = "Internal health probe contract."
  type = object({
    port                    = number
    liveness_path           = string
    readiness_path          = string
    interval_seconds        = optional(number, 30)
    timeout_seconds         = optional(number, 3)
    failure_count_threshold = optional(number, 3)
  })
  default = {
    port           = 8080
    liveness_path  = "/live"
    readiness_path = "/ready"
  }
}

variable "rollback" {
  description = "Revision rollback contract consumed by the deployment orchestrator."
  type = object({
    strategy                 = string
    previous_image           = string
    max_unavailable_replicas = optional(number, 0)
  })

  validation {
    condition     = contains(["previous-revision", "image-redeploy"], var.rollback.strategy)
    error_message = "rollback.strategy must be previous-revision or image-redeploy."
  }
}

variable "runtime_env" {
  description = "Deployment environment, independent of authority and execution venue."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.runtime_env)
    error_message = "runtime_env must be dev, staging, or prod."
  }
}

variable "scaling" {
  description = "Replica and resource limits for the Core service."
  type = object({
    min_replicas = number
    max_replicas = number
    cpu          = number
    memory       = string
  })
  default = {
    min_replicas = 1
    max_replicas = 3
    cpu          = 0.5
    memory       = "1Gi"
  }

  validation {
    condition     = var.scaling.min_replicas >= 1 && var.scaling.max_replicas >= var.scaling.min_replicas
    error_message = "Core requires at least one replica until a credential-free Kafka scaler is proven."
  }
}

variable "tags" {
  description = "Deployment-supplied generic resource tags."
  type        = map(string)
  default     = {}
}

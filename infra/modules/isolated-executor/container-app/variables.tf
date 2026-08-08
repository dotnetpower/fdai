variable "name" {
  description = "Internal isolated Executor Container App name."
  type        = string
}

variable "container_app_environment_id" {
  description = "Shared Container Apps Environment resource id."
  type        = string
}

variable "resource_group_name" {
  description = "Enclosing resource group."
  type        = string
}

variable "image" {
  description = "Independent isolated Executor service image. The removed monolith runtime image is unsupported."
  type        = string
}

variable "service_entrypoint" {
  description = "Python console entry point declared by the independent isolated Executor distribution."
  type        = string
  default     = ""

  validation {
    condition = contains([
      "",
      "fdai-isolated-executor-service",
    ], var.service_entrypoint)
    error_message = "service_entrypoint must be fdai-isolated-executor-service from the independent distribution."
  }
}

variable "service_distribution" {
  description = "Distribution packaged into the supplied independent service image."
  type        = string
  default     = ""

  validation {
    condition = contains([
      "",
      "fdai-isolated-executor-service",
    ], var.service_distribution)
    error_message = "service_distribution must be fdai-isolated-executor-service."
  }
}

variable "identity_id" {
  description = "Dedicated shadow transport UAMI resource id."
  type        = string
}

variable "identity_client_id" {
  description = "Dedicated shadow transport UAMI client id."
  type        = string
}

variable "extra_identity_ids" {
  description = "Additional action-scoped identities attached only after authority cutover."
  type        = list(string)
  default     = []
}

variable "change_identity_client_id" {
  description = "Change Safety identity client id attached after authority cutover."
  type        = string
  default     = ""
}

variable "resilience_identity_client_id" {
  description = "Resilience identity client id attached after authority cutover."
  type        = string
  default     = ""
}

variable "finops_identity_client_id" {
  description = "Cost Governance identity client id attached after authority cutover."
  type        = string
  default     = ""
}

variable "authority_cutover" {
  description = "Enable guarded direct-API effects in the isolated Executor."
  type        = bool
  default     = false
}

variable "dev_operations_gateway_url" {
  description = "HTTPS origin for the governed development operations gateway."
  type        = string
  default     = ""
}

variable "dev_operations_gateway_audience" {
  description = "Entra audience for the governed development operations gateway."
  type        = string
  default     = ""
}

variable "state_store_dsn_secret_id" {
  description = "Key Vault secret id for the durable PostgreSQL state DSN."
  type        = string
  sensitive   = true
}

variable "kafka_bootstrap_servers" {
  description = "Event Hubs Kafka endpoint containing Executor command and receipt entities."
  type        = string
}

variable "command_topic" {
  description = "Versioned Executor command topic."
  type        = string
  default     = "object.executor-command"
}

variable "receipt_topic" {
  description = "Terminal shadow receipt topic."
  type        = string
  default     = "object.executor-receipt"
}

variable "dlq_suffix" {
  description = "Dead-letter suffix shared with the Event Hubs module."
  type        = string
  default     = ".dlq"
}

variable "runtime_env" {
  description = "Deployment environment label, independent of process venue and authority."
  type        = string
}

variable "acr_login_server" {
  description = "Private ACR login server. Empty uses anonymous image pull."
  type        = string
  default     = ""
}

variable "health_port" {
  description = "Internal liveness and readiness probe port."
  type        = number
  default     = 8000

  validation {
    condition     = var.health_port >= 1 && var.health_port <= 65535
    error_message = "health_port MUST be between 1 and 65535."
  }
}

variable "min_replicas" {
  description = "Minimum shadow replicas. Keep one until a credential-free Kafka scaler is proven."
  type        = number
  default     = 1
}

variable "max_replicas" {
  description = "Maximum shadow replicas."
  type        = number
  default     = 1
}

variable "cpu" {
  description = "CPU cores per shadow replica."
  type        = number
  default     = 0.25
}

variable "memory" {
  description = "Memory per shadow replica."
  type        = string
  default     = "0.5Gi"
}

variable "tags" {
  description = "Resource tags."
  type        = map(string)
  default     = {}
}

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
  description = "FDAI runtime image containing the fdai-isolated-executor entry point."
  type        = string
}

variable "identity_id" {
  description = "Dedicated shadow transport UAMI resource id."
  type        = string
}

variable "identity_client_id" {
  description = "Dedicated shadow transport UAMI client id."
  type        = string
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

variable "name" { type = string }
variable "worker_name" { type = string }
variable "migrate_job_name" { type = string }
variable "container_app_environment_id" { type = string }
variable "location" { type = string }
variable "resource_group_name" { type = string }
variable "image" { type = string }
variable "clamav_image" { type = string }
variable "identity_id" { type = string }
variable "identity_client_id" { type = string }
variable "database_dsn_secret_id" { type = string }
variable "api_database_role" {
  type    = string
  default = "fdai_ingestion_api"
}
variable "worker_identity_id" {
  type    = string
  default = ""
}
variable "worker_identity_client_id" {
  type    = string
  default = ""
}
variable "migration_identity_id" { type = string }
variable "migration_identity_client_id" { type = string }
variable "worker_database_dsn_secret_id" {
  type    = string
  default = ""
}
variable "migration_database_dsn_secret_id" { type = string }
variable "cohost_worker" {
  type    = bool
  default = false
}
variable "stewardship_governance_enabled" { type = bool }
variable "gitops_owner" { type = string }
variable "gitops_repo" { type = string }
variable "gitops_token_secret_id" {
  type      = string
  sensitive = true
}
variable "github_webhook_secret_id" {
  type      = string
  sensitive = true
}
variable "chatops_webhook_url_secret_id" {
  type      = string
  sensitive = true
}
variable "stewardship_maintainers" { type = string }
variable "stewardship_agent_bindings" { type = map(string) }
variable "entra_tenant_id" { type = string }
variable "api_audience" { type = string }
variable "rbac_readers_group_id" { type = string }
variable "rbac_contributors_group_id" { type = string }
variable "rbac_approvers_group_id" { type = string }
variable "rbac_owners_group_id" { type = string }
variable "rbac_break_glass_group_id" { type = string }
variable "cors_allow_origins" { type = string }
variable "adls_account_name" { type = string }
variable "adls_account_url" { type = string }
variable "adls_source_file_system" { type = string }
variable "adls_derived_file_system" { type = string }
variable "embedding_endpoint" { type = string }
variable "embedding_deployment" { type = string }
variable "ocr_endpoint" { type = string }
variable "ocr_operation_timeout_seconds" {
  type    = number
  default = 180

  validation {
    condition     = var.ocr_operation_timeout_seconds > 0 && var.ocr_operation_timeout_seconds <= 1800
    error_message = "ocr_operation_timeout_seconds must be in (0, 1800]."
  }
}
variable "kafka_bootstrap_servers" { type = string }
variable "document_event_topic" { type = string }
variable "runtime_env" { type = string }
variable "document_collections" { type = string }

variable "embedding_dim" {
  type    = number
  default = 384
}

variable "max_file_size_bytes" {
  type    = number
  default = 26214400
}

variable "max_batch_count" {
  type    = number
  default = 10
}

variable "chunk_max_chars" {
  type    = number
  default = 1200
}

variable "chunk_overlap" {
  type    = number
  default = 150
}

variable "indexing_stage_timeout_seconds" {
  type    = number
  default = 90

  validation {
    condition     = var.indexing_stage_timeout_seconds > 0
    error_message = "indexing_stage_timeout_seconds must be positive."
  }
}

variable "policy_version" {
  type    = string
  default = "prod-policy-v1"
}

variable "min_replicas" {
  type    = number
  default = 1
}

variable "max_replicas" {
  type    = number
  default = 1
}

variable "gateway_cpu" {
  type    = number
  default = 1
}

variable "gateway_memory" {
  type    = string
  default = "2Gi"
}

variable "worker_min_replicas" {
  type    = number
  default = 1

  validation {
    condition     = var.worker_min_replicas >= 1
    error_message = "worker_min_replicas must remain at least 1 until a Kafka wake-up scaler is verified."
  }
}

variable "worker_max_replicas" {
  type    = number
  default = 1

  validation {
    condition     = var.worker_max_replicas >= 1 && var.worker_max_replicas >= var.worker_min_replicas
    error_message = "worker_max_replicas must be positive and at least worker_min_replicas."
  }
}

variable "worker_cpu" {
  type    = number
  default = 1

  validation {
    condition     = var.worker_cpu > 0
    error_message = "worker_cpu must be positive."
  }
}

variable "worker_memory" {
  type    = string
  default = "2Gi"
}

variable "clamav_cpu" {
  type    = number
  default = 1.5
}

variable "clamav_memory" {
  type    = string
  default = "3Gi"
}

variable "acr_login_server" {
  type    = string
  default = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}

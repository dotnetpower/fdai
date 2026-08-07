variable "name" { type = string }
variable "platform" { type = object({ resource_group_name = string, container_app_environment_id = string, acr_login_server = string, kafka_bootstrap_servers = string }) }
variable "image" { type = string }
variable "identity" { type = object({ resource_id = string, client_id = string }) }
variable "event_topics" { type = object({ pipeline_stages = string }) }
variable "database" {
  type      = object({ dsn_secret_id = string, role = string })
  sensitive = true
}
variable "document_store" { type = object({ account_name = string, account_url = string, source_file_system = string }) }
variable "health" { type = object({ port = number, liveness_path = string, readiness_path = string, startup_path = optional(string), interval_seconds = optional(number, 30), timeout_seconds = optional(number, 3), failure_count_threshold = optional(number, 3), startup_failure_count = optional(number, 30) }) }
variable "rollback" { type = object({ strategy = string, previous_image = string, max_unavailable_replicas = optional(number, 0) }) }
variable "runtime_env" { type = string }
variable "auth" { type = object({ tenant_id = string, api_audience = string }) }
variable "cors_allow_origins" { type = string }
variable "scaling" { type = object({ min_replicas = number, max_replicas = number, cpu = number, memory = string }) }
variable "tags" { type = map(string) }

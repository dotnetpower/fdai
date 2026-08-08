variable "name" { type = string }
variable "platform" { type = object({ resource_group_name = string, container_app_environment_id = string, acr_login_server = string, kafka_bootstrap_servers = string }) }
variable "image" { type = string }
variable "identity" { type = object({ runtime_resource_id = string, runtime_client_id = string, command_resource_id = string, command_client_id = string }) }
variable "event_topics" { type = object({ events = string }) }
variable "database" {
  type      = object({ dsn_secret_id = string, role = string })
  sensitive = true
}
variable "health" { type = object({ port = number, liveness_path = string, readiness_path = string, startup_path = optional(string), interval_seconds = optional(number, 30), timeout_seconds = optional(number, 3), failure_count_threshold = optional(number, 3), startup_failure_count = optional(number, 30) }) }
variable "rollback" { type = object({ strategy = string, previous_image = string, max_unavailable_replicas = optional(number, 0) }) }
variable "runtime_env" { type = string }
variable "auth" { type = object({ tenant_id = string, api_audience = string }) }
variable "rbac" { type = object({ readers_group_id = string, contributors_group_id = string, approvers_group_id = string, owners_group_id = string, break_glass_group_id = string }) }
variable "cors_allow_origins" { type = string }
variable "scaling" { type = object({ min_replicas = number, max_replicas = number, cpu = number, memory = string }) }
variable "tags" { type = map(string) }

variable "name" { type = string }
variable "platform" { type = object({ resource_group_name = string, container_app_environment_id = string, acr_login_server = string, kafka_bootstrap_servers = string }) }
variable "image" { type = string }
variable "identity" { type = object({ transport_resource_id = string, transport_client_id = string, action_resource_ids = optional(list(string), []) }) }
variable "event_topics" { type = object({ command = string, receipt = string, dlq_suffix = string }) }
variable "database" {
  type      = object({ dsn_secret_id = string, role = string })
  sensitive = true
}
variable "health" { type = object({ port = number, liveness_path = string, readiness_path = string, startup_path = optional(string), interval_seconds = optional(number, 30), timeout_seconds = optional(number, 3), failure_count_threshold = optional(number, 3), startup_failure_count = optional(number, 30) }) }
variable "rollback" { type = object({ strategy = string, previous_image = string, authority_fallback = string, max_unavailable_replicas = optional(number, 0) }) }
variable "runtime_env" { type = string }
variable "authority" { type = object({ cutover = bool, dev_operations_gateway_url = string, dev_operations_gateway_audience = string }) }
variable "scaling" { type = object({ min_replicas = number, max_replicas = number, cpu = number, memory = string }) }
variable "tags" { type = map(string) }

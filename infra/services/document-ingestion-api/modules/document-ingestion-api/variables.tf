variable "name" { type = string }
variable "platform" { type = object({ resource_group_name = string, container_app_environment_id = string, acr_login_server = string, kafka_bootstrap_servers = string }) }
variable "image" { type = string }
variable "identity" { type = object({ resource_id = string, client_id = string }) }
variable "event_topics" { type = object({ pipeline_stages = string }) }
variable "database" {
  type      = object({ dsn_secret_id = string, host = optional(string, ""), role = string })
  sensitive = true
}
variable "document_store" { type = object({ account_name = string, account_url = string, source_file_system = string }) }
variable "health" { type = object({ port = number, liveness_path = string, readiness_path = string, startup_path = optional(string), interval_seconds = optional(number, 30), timeout_seconds = optional(number, 3), failure_count_threshold = optional(number, 3), startup_failure_count = optional(number, 30) }) }
variable "rollback" { type = object({ strategy = string, previous_image = string, max_unavailable_replicas = optional(number, 0) }) }
variable "runtime_env" { type = string }
variable "auth" { type = object({ tenant_id = string, api_audience = string }) }
variable "rbac" { type = object({ readers_group_id = string, contributors_group_id = string, approvers_group_id = string, owners_group_id = string, break_glass_group_id = string }) }
variable "embedding" { type = object({ endpoint = string, deployment = string }) }
variable "cors_allow_origins" { type = string }
variable "sharepoint_connector" {
  type = object({
    enabled                = bool
    connector_id           = string
    target_tenant_id       = string
    client_id              = string
    site_id                = string
    drive_id               = string
    collection_id          = string
    access_descriptor_ref  = string
    reader_groups          = optional(string, "")
    retention_policy       = string
    purposes               = optional(string, "knowledge_base")
    download_host_suffixes = optional(string, ".sharepoint.com")
  })
}
variable "scaling" { type = object({ min_replicas = number, max_replicas = number, cpu = number, memory = string }) }
variable "tags" { type = map(string) }

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
variable "stewardship_gitops" {
  type = object({
    enabled                   = optional(bool, false)
    owner                     = optional(string, "")
    repo                      = optional(string, "")
    auth_mode                 = optional(string, "")
    token_secret_id           = optional(string, "")
    app_client_id             = optional(string, "")
    app_installation_id       = optional(string, "")
    app_private_key_secret_id = optional(string, "")
    webhook_secret_id         = optional(string, "")
  })
  sensitive = true
}
variable "scaling" { type = object({ min_replicas = number, max_replicas = number, cpu = number, memory = string }) }
variable "channel_intake" {
  type = object({
    enabled                    = optional(bool, false)
    name                       = optional(string, "")
    principal_scopes_secret_id = optional(string, "")
    edge_client_id             = optional(string, "")
    collection_id              = optional(string, "")
    access_descriptor_ref      = optional(string, "")
    reader_groups              = optional(string, "")
    retention_policy           = optional(string, "")
    max_content_bytes          = optional(number, 26214400)
    health = optional(object({
      port                    = number
      liveness_path           = string
      readiness_path          = string
      startup_path            = optional(string)
      interval_seconds        = optional(number, 30)
      timeout_seconds         = optional(number, 3)
      failure_count_threshold = optional(number, 3)
      startup_failure_count   = optional(number, 30)
      }), {
      port                    = 8000
      liveness_path           = "/health/live"
      readiness_path          = "/health/ready"
      startup_path            = "/health/ready"
      interval_seconds        = 15
      timeout_seconds         = 3
      failure_count_threshold = 3
      startup_failure_count   = 30
    })
    scaling = optional(object({ min_replicas = number, max_replicas = number, cpu = number, memory = string }), {
      min_replicas = 1
      max_replicas = 2
      cpu          = 0.5
      memory       = "1Gi"
    })
  })
  default = {}
}
variable "tags" { type = map(string) }

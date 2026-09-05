variable "name" {
  description = "Document ingestion API Container App name."
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
  description = "Promoted document ingestion API OCI image."
  type        = string
}
variable "identity" {
  description = "API workload identity outputs supplied by the identity state owner."
  type        = object({ resource_id = string, client_id = string })
}
variable "event_topics" {
  description = "Event Hub entities used by the ingestion API."
  type        = object({ pipeline_stages = string })
}
variable "database" {
  description = "Role-scoped ingestion API database secret reference."
  type        = object({ dsn_secret_id = string, host = string, role = string })
  sensitive   = true
  validation {
    condition     = trimspace(var.database.host) != ""
    error_message = "database.host must contain the non-secret PostgreSQL endpoint identity."
  }
}
variable "document_store" {
  description = "Shared document storage outputs supplied by the platform state owner."
  type = object({
    account_name       = string
    account_url        = string
    source_file_system = string
  })
}
variable "health" {
  description = "Ingestion API HTTP health contract."
  type = object({
    port                    = number
    liveness_path           = optional(string)
    readiness_path          = string
    startup_path            = optional(string)
    interval_seconds        = optional(number, 30)
    timeout_seconds         = optional(number, 3)
    failure_count_threshold = optional(number, 3)
    startup_failure_count   = optional(number, 30)
  })
  default = { port = 8000, liveness_path = null, readiness_path = "/healthz", startup_path = null }
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
variable "auth" {
  description = "Entra application contract for authenticated document intake."
  type        = object({ tenant_id = string, api_audience = string })
}
variable "rbac" {
  description = "Distinct Entra App Role group identifiers for document intake."
  type = object({
    readers_group_id      = string
    contributors_group_id = string
    approvers_group_id    = string
    owners_group_id       = string
    break_glass_group_id  = string
  })
}
variable "embedding" {
  description = "Embedding provider contract used for document indexing requests."
  type        = object({ endpoint = string, deployment = string })
}
variable "cors_allow_origins" {
  description = "Comma-separated explicit console origins."
  type        = string
}
variable "sharepoint_connector" {
  description = "FDAI-native cross-tenant SharePoint connector binding."
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
  default = {
    enabled               = false
    connector_id          = ""
    target_tenant_id      = ""
    client_id             = ""
    site_id               = ""
    drive_id              = ""
    collection_id         = ""
    access_descriptor_ref = ""
    retention_policy      = ""
  }
  validation {
    condition = !var.sharepoint_connector.enabled || alltrue([
      trimspace(var.sharepoint_connector.connector_id) != "",
      trimspace(var.sharepoint_connector.target_tenant_id) != "",
      trimspace(var.sharepoint_connector.client_id) != "",
      trimspace(var.sharepoint_connector.site_id) != "",
      trimspace(var.sharepoint_connector.drive_id) != "",
      trimspace(var.sharepoint_connector.collection_id) != "",
      trimspace(var.sharepoint_connector.access_descriptor_ref) != "",
      trimspace(var.sharepoint_connector.retention_policy) != "",
    ])
    error_message = "Enabled SharePoint connector requires complete identity, source, and document-policy bindings."
  }
}
variable "scaling" {
  description = "API replica and resource limits."
  type        = object({ min_replicas = number, max_replicas = number, cpu = number, memory = string })
  default     = { min_replicas = 1, max_replicas = 2, cpu = 0.5, memory = "1Gi" }
}
variable "tags" {
  description = "Deployment-supplied generic resource tags."
  type        = map(string)
  default     = {}
}

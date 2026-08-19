variable "name" {
  description = "Operator service Container App name."
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
  description = "Promoted Operator service OCI image."
  type        = string
}
variable "identity" {
  description = "Read and command workload identities supplied by the identity state owner."
  type = object({
    runtime_resource_id = string
    runtime_client_id   = string
    command_resource_id = string
    command_client_id   = string
    edge_resource_id    = optional(string, "")
    edge_client_id      = optional(string, "")
  })
}
variable "channel_edge" {
  description = "Optional standalone public channel edge in the Operator distribution. Provider secrets and principal mappings are Key Vault references."
  type = object({
    enabled                       = bool
    name                          = string
    slack_enabled                 = bool
    teams_enabled                 = bool
    principal_scopes_secret_id    = string
    slack_signing_secret_id       = string
    slack_bot_token_secret_id     = string
    slack_team_id                 = string
    slack_principal_map_secret_id = string
    teams_application_id          = string
    teams_tenant_id               = string
    teams_principal_map_secret_id = string
    teams_allowed_service_urls    = string
    teams_jwks_url                = string
    health = object({
      port                    = number
      liveness_path           = string
      readiness_path          = string
      startup_path            = optional(string)
      interval_seconds        = optional(number, 30)
      timeout_seconds         = optional(number, 3)
      failure_count_threshold = optional(number, 3)
      startup_failure_count   = optional(number, 30)
    })
    scaling = object({
      min_replicas = number
      max_replicas = number
      cpu          = number
      memory       = string
    })
  })
  default = {
    enabled                       = false
    name                          = ""
    slack_enabled                 = false
    teams_enabled                 = false
    principal_scopes_secret_id    = ""
    slack_signing_secret_id       = ""
    slack_bot_token_secret_id     = ""
    slack_team_id                 = ""
    slack_principal_map_secret_id = ""
    teams_application_id          = ""
    teams_tenant_id               = ""
    teams_principal_map_secret_id = ""
    teams_allowed_service_urls    = ""
    teams_jwks_url                = ""
    health = {
      port                    = 8014
      liveness_path           = "/health/live"
      readiness_path          = "/health/ready"
      startup_path            = "/health/ready"
      interval_seconds        = 15
      timeout_seconds         = 3
      failure_count_threshold = 3
      startup_failure_count   = 30
    }
    scaling = { min_replicas = 1, max_replicas = 2, cpu = 0.5, memory = "1Gi" }
  }
  validation {
    condition = !var.channel_edge.enabled || (
      var.channel_edge.name != "" &&
      (var.channel_edge.slack_enabled || var.channel_edge.teams_enabled) &&
      var.channel_edge.principal_scopes_secret_id != "" &&
      (!var.channel_edge.slack_enabled || (
        var.channel_edge.slack_signing_secret_id != "" &&
        var.channel_edge.slack_bot_token_secret_id != "" &&
        var.channel_edge.slack_team_id != "" &&
        var.channel_edge.slack_principal_map_secret_id != ""
      )) &&
      (!var.channel_edge.teams_enabled || (
        var.channel_edge.teams_application_id != "" &&
        var.channel_edge.teams_tenant_id != "" &&
        var.channel_edge.teams_principal_map_secret_id != "" &&
        can(jsondecode(var.channel_edge.teams_allowed_service_urls)) &&
        startswith(var.channel_edge.teams_jwks_url, "https://")
      ))
    )
    error_message = "Enabled channel_edge requires at least one complete Slack or Teams provider contract plus principal scopes."
  }
}
variable "event_topics" {
  description = "Event Hub entities used for typed operator requests."
  type = object({
    events               = string
    semantic_requests    = optional(string, "")
    semantic_projections = optional(string, "")
    semantic_physical    = optional(string, "aw.pantheon.objects")
  })
}
variable "database" {
  description = "Role-scoped Operator database secret reference."
  type        = object({ dsn_secret_id = string, role = string })
  sensitive   = true
}
variable "health" {
  description = "Operator HTTP health contract."
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
  description = "Entra application contract for the Operator HTTPS boundary."
  type        = object({ tenant_id = string, api_audience = string })
}
variable "rbac" {
  description = "Distinct Entra App Role group identifiers for the Operator boundary."
  type = object({
    readers_group_id      = string
    contributors_group_id = string
    approvers_group_id    = string
    owners_group_id       = string
    break_glass_group_id  = string
  })
}
variable "cors_allow_origins" {
  description = "Comma-separated explicit console origins."
  type        = string
}
variable "scaling" {
  description = "Operator replica and resource limits."
  type        = object({ min_replicas = number, max_replicas = number, cpu = number, memory = string })
  default     = { min_replicas = 1, max_replicas = 1, cpu = 0.5, memory = "1Gi" }
}
variable "tags" {
  description = "Deployment-supplied generic resource tags."
  type        = map(string)
  default     = {}
}

variable "name" { type = string }
variable "platform" { type = object({ resource_group_name = string, container_app_environment_id = string, acr_login_server = string, kafka_bootstrap_servers = string }) }
variable "image" { type = string }
variable "identity" { type = object({ runtime_resource_id = string, runtime_client_id = string, command_resource_id = string, command_client_id = string, edge_resource_id = optional(string, ""), edge_client_id = optional(string, "") }) }
variable "event_topics" {
  type = object({
    events                         = string
    semantic_requests              = optional(string, "")
    semantic_projections           = optional(string, "")
    semantic_physical              = optional(string, "fdai.pantheon.objects")
    read_investigation_requests    = optional(string, "")
    incident_intervention_requests = optional(string, "operator.incident-intervention.requests")
    read_investigation_completions = optional(string, "core.read-investigation.completions")
    hil_decisions                  = optional(string, "fdai.hil.decisions")
    notification_receipts          = optional(string, "fdai.notifications.delivery-receipts")
  })
}
variable "database" {
  type      = object({ dsn_secret_id = string, host = optional(string, ""), role = string })
  sensitive = true
}
variable "health" { type = object({ port = number, liveness_path = string, readiness_path = string, startup_path = optional(string), interval_seconds = optional(number, 30), timeout_seconds = optional(number, 3), failure_count_threshold = optional(number, 3), startup_failure_count = optional(number, 30) }) }
variable "rollback" { type = object({ strategy = string, previous_image = string, max_unavailable_replicas = optional(number, 0) }) }
variable "runtime_env" { type = string }
variable "auth" { type = object({ tenant_id = string, api_audience = string }) }
variable "rbac" { type = object({ readers_group_id = string, contributors_group_id = string, approvers_group_id = string, owners_group_id = string, break_glass_group_id = string }) }
variable "cors_allow_origins" { type = string }
variable "notification_receipt_secret_id" {
  type      = string
  sensitive = true
  default   = ""
}
variable "scaling" { type = object({ min_replicas = number, max_replicas = number, cpu = number, memory = string }) }
variable "channel_edge" {
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
      port = number, liveness_path = string, readiness_path = string, startup_path = optional(string), interval_seconds = optional(number, 30), timeout_seconds = optional(number, 3), failure_count_threshold = optional(number, 3), startup_failure_count = optional(number, 30)
    })
    scaling = object({ min_replicas = number, max_replicas = number, cpu = number, memory = string })
  })
}
variable "hil_callback" {
  type = object({
    enabled                       = bool
    signing_secret_id             = string
    teams_application_id          = string
    teams_tenant_id               = string
    teams_approval_team_id        = string
    teams_approval_channel_id     = string
    teams_allowed_service_urls    = string
    teams_jwks_url                = string
    teams_principal_map_secret_id = string
    slack_team_id                 = string
    slack_principal_map_secret_id = string
  })
}
variable "tags" { type = map(string) }

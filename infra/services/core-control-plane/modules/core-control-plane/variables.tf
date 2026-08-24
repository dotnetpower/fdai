variable "name" { type = string }
variable "platform" {
  type = object({
    resource_group_name                 = string
    container_app_environment_id        = string
    acr_login_server                    = string
    kafka_bootstrap_servers             = string
    operational_kafka_bootstrap_servers = optional(string, "")
  })
}
variable "image" { type = string }
variable "bootstrap" {
  type = object({
    azure_tenant_id       = string
    azure_subscription_id = string
    azure_region          = string
    postgres_database     = string
  })
}
variable "identity" {
  type = object({
    resource_id        = string
    client_id          = string
    extra_resource_ids = optional(list(string), [])
  })
}
variable "event_topics" {
  type = object({
    canary                         = optional(string, "fdai.control.canary")
    events                         = string
    executor_command               = string
    executor_receipt               = string
    hil_decisions                  = optional(string, "fdai.hil.decisions")
    inventory_raw                  = optional(string, "fdai.inventory.raw")
    pipeline_stages                = optional(string, "fdai.pipeline.stages")
    startup_probe                  = optional(string, "runtime.startup.probe")
    semantic_requests              = optional(string, "operator.semantic-turn.requests")
    semantic_projections           = optional(string, "core.semantic-turn.projections")
    semantic_physical              = optional(string, "fdai.pantheon.objects")
    read_investigation_requests    = optional(string, "operator.read-investigation.requests")
    incident_intervention_requests = optional(string, "operator.incident-intervention.requests")
  })
}
variable "database" {
  type = object({
    dsn_secret_id = string
    host          = optional(string, "")
    role          = string
  })
  sensitive = true
}
variable "health" {
  type = object({
    port                    = number
    liveness_path           = string
    readiness_path          = string
    startup_path            = optional(string)
    interval_seconds        = optional(number, 30)
    timeout_seconds         = optional(number, 3)
    failure_count_threshold = optional(number, 3)
    startup_failure_count   = optional(number, 30)
  })
}
variable "rollback" {
  type = object({
    strategy                 = string
    previous_image           = string
    max_unavailable_replicas = optional(number, 0)
  })
}
variable "runtime_env" { type = string }
variable "startup_readiness" {
  type = object({
    kafka_settle_seconds  = number
    probe_timeout_seconds = number
    phase_timeout_seconds = number
  })
}
variable "llm" {
  type = object({
    endpoint                   = string
    web_search_enabled         = optional(bool, false)
    web_search_allowed_domains = optional(list(string), [])
    web_search_max_results     = optional(number, 8)
    web_search_timeout_seconds = optional(number, 45)
    resolved_models_digest     = optional(string, "")
  })
}
variable "scaling" {
  type = object({
    min_replicas = number
    max_replicas = number
    cpu          = number
    memory       = string
  })
}
variable "tags" { type = map(string) }

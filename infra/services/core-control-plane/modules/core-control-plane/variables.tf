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
    model_endpoints            = optional(map(string), {})
    web_search_enabled         = optional(bool, false)
    web_search_allowed_domains = optional(list(string), [])
    web_search_max_results     = optional(number, 8)
    web_search_timeout_seconds = optional(number, 45)
    resolved_models_digest     = optional(string, "")
  })
}

variable "observation_context" {
  description = "Optional deployment-owned signed context for Heimdall executed-action observations."
  type = object({
    enabled                     = optional(bool, false)
    signing_seed_secret_id      = optional(string, "")
    executor_credential_lineage = optional(string, "")
    source_credential_lineage   = optional(string, "")
  })
  default = {}
}

variable "configuration_drift" {
  description = "Optional scope-pinned read-only Azure Resource Graph configuration drift binding."
  type = object({
    enabled             = optional(bool, false)
    baseline_path       = optional(string, "")
    baseline_version    = optional(string, "")
    baseline_sha256     = optional(string, "")
    scope               = optional(string, "")
    subscription_scopes = optional(list(string), [])
    attribute_paths     = optional(list(string), [])
    arg_endpoint        = optional(string, "https://management.azure.com")
  })
  default = {}

  validation {
    condition = !var.configuration_drift.enabled || (
      trimspace(var.configuration_drift.baseline_path) != "" &&
      trimspace(var.configuration_drift.baseline_version) != "" &&
      can(regex("^[0-9a-f]{64}$", var.configuration_drift.baseline_sha256)) &&
      trimspace(var.configuration_drift.scope) != "" &&
      length(var.configuration_drift.subscription_scopes) >= 1 &&
      length(var.configuration_drift.subscription_scopes) <= 256 &&
      var.configuration_drift.subscription_scopes == sort(distinct(var.configuration_drift.subscription_scopes)) &&
      length(var.configuration_drift.attribute_paths) >= 1 &&
      length(var.configuration_drift.attribute_paths) <= 64 &&
      var.configuration_drift.attribute_paths == sort(distinct(var.configuration_drift.attribute_paths)) &&
      alltrue([
        for path in var.configuration_drift.attribute_paths :
        can(regex("^[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z][A-Za-z0-9_]*)*$", path))
      ]) &&
      contains([
        "https://management.azure.com",
        "https://management.azure.us",
        "https://management.chinacloudapi.cn",
        "https://management.microsoftazure.de",
      ], trimsuffix(trimspace(var.configuration_drift.arg_endpoint), "/"))
    )
    error_message = "Enabled configuration_drift requires a baseline identity, 1-256 ordered unique subscriptions, 1-64 ordered unique scalar attribute paths, and an approved Azure management origin."
  }
}

variable "diagnostic_ingest" {
  description = "Optional Azure diagnostic Event Hub Kafka ingestion binding."
  type = object({
    enabled           = optional(bool, false)
    bootstrap_servers = optional(string, "")
    topic             = optional(string, "")
    metric_whitelist  = optional(list(string), [])
    consumer_group_id = optional(string, "fdai-diagnostic-normalizer")
  })
  default = {}

  validation {
    condition = !var.diagnostic_ingest.enabled || (
      trimspace(var.diagnostic_ingest.bootstrap_servers) != "" &&
      trimspace(var.diagnostic_ingest.topic) != "" &&
      length(var.diagnostic_ingest.metric_whitelist) >= 1 &&
      length(var.diagnostic_ingest.metric_whitelist) <= 256 &&
      var.diagnostic_ingest.metric_whitelist == sort(distinct(var.diagnostic_ingest.metric_whitelist)) &&
      trimspace(var.diagnostic_ingest.consumer_group_id) != ""
    )
    error_message = "Enabled diagnostic_ingest requires Kafka bootstrap servers, a topic, 1-256 ordered unique metric names, and a consumer group."
  }
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

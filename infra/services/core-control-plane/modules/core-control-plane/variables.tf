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
variable "decision_evidence_container_url" {
  type    = string
  default = ""
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

variable "runtime_call_evidence" {
  type = object({
    caller_resource_id = optional(string, "")
    target_resource_id = optional(string, "")
  })
  default = {}
}

variable "rca_reader_identity" {
  type = object({
    resource_id = optional(string, "")
    client_id   = optional(string, "")
  })
  default = {}
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
    notification_receipts          = optional(string, "fdai.notifications.delivery-receipts")
  })
}

variable "teams_notification_binding" {
  type = object({
    enabled            = optional(bool, false)
    channel_id         = optional(string, "teams-ops")
    trust_tiers        = optional(list(string), ["a2_operational_alert"])
    endpoint_secret_id = optional(string, "")
  })
  default = {}
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

variable "teams_approval_destination" {
  type = object({
    team_id              = string
    channel_id           = string
    activity_url         = string
    identity_resource_id = string
    identity_client_id   = string
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

variable "license" {
  description = "Optional versionless Key Vault reference and non-secret bindings for a signed capability license."
  type = object({
    token_secret_id   = optional(string, "")
    image_digest      = optional(string, "")
    deployment_digest = optional(string, "")
    token_revision    = optional(string, "")
  })
  default = {}

  validation {
    condition = (
      trimspace(var.license.token_secret_id) == "" &&
      trimspace(var.license.image_digest) == "" &&
      trimspace(var.license.deployment_digest) == "" &&
      trimspace(var.license.token_revision) == ""
      ) || (
      can(regex("^https://[^/]+/secrets/[^/]+$", trimspace(var.license.token_secret_id))) &&
      can(regex("^[0-9a-f]{64}$", trimspace(var.license.image_digest))) &&
      can(regex("^[0-9a-f]{64}$", trimspace(var.license.deployment_digest))) &&
      can(regex("^[0-9a-f]{64}$", trimspace(var.license.token_revision)))
    )
    error_message = "license must be empty or contain one versionless HTTPS Key Vault secret id and three lowercase SHA-256 digests."
  }
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
variable "stewardship_audit_interval_seconds" { type = number }
variable "handover_knowledge_interval_seconds" { type = number }
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

variable "governed_rca" {
  type = object({
    enabled                   = optional(bool, false)
    document_dsn_secret_id    = optional(string, "")
    collection_id             = optional(string, "")
    allowed_access_refs       = optional(list(string), [])
    actor_groups              = optional(list(string), [])
    freshness_ceiling_seconds = optional(number, 86400)
  })
  default   = {}
  sensitive = true
}

variable "configuration_drift" {
  description = "Optional scope-pinned read-only Azure Resource Graph configuration drift binding."
  type = object({
    enabled             = optional(bool, false)
    baseline_url        = optional(string, "")
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
      can(regex(
        "^https://[^/]+/[^/]+/configuration-baselines/[0-9a-f]{64}\\.json$",
        trimspace(var.configuration_drift.baseline_url),
      )) &&
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
  sensitive = true
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

variable "operating_intent_source" {
  description = "Deployment-owned six-type operating-intent source binding: source path, exact pinned revision, whole-document sha256 content digest (provenance included), exact expected instance counts for ServiceObjective, RecoveryObjective, CostObjective, ArchitectureConstraint, Ownership, and ChangeWindow, the rollout generation that fences admission writes across a rolling deployment, and the bounded revalidation interval that keeps admission current after startup."
  type = object({
    enabled              = optional(bool, false)
    path                 = optional(string, "")
    revision             = optional(string, "")
    sha256               = optional(string, "")
    expected_counts_json = optional(string, "")
    generation           = optional(number, 1)
    revalidate_seconds   = optional(number, 0)
  })
  default = {}

  validation {
    condition = !var.operating_intent_source.enabled || (
      trimspace(var.operating_intent_source.path) != "" &&
      trimspace(var.operating_intent_source.revision) != "" &&
      can(regex("^sha256:[0-9a-f]{64}$", var.operating_intent_source.sha256))
    )
    error_message = "Enabled operating_intent_source requires a source path, an exact pinned revision, and a sha256: content digest."
  }

  validation {
    condition = var.operating_intent_source.revalidate_seconds == 0 || (
      var.operating_intent_source.revalidate_seconds == floor(var.operating_intent_source.revalidate_seconds) &&
      var.operating_intent_source.revalidate_seconds >= 1 &&
      var.operating_intent_source.revalidate_seconds <= 28800
    )
    error_message = "operating_intent_source.revalidate_seconds MUST be an integer between 1 and 28800 seconds, or 0 to keep the runtime default."
  }

  validation {
    condition = (
      var.operating_intent_source.generation == floor(var.operating_intent_source.generation) &&
      var.operating_intent_source.generation >= 1
    )
    error_message = "operating_intent_source.generation MUST be an integer of 1 or more."
  }
}

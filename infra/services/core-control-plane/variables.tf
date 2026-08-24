variable "name" {
  description = "Core control-plane Container App name."
  type        = string
}

variable "platform" {
  description = "Shared platform outputs supplied by the platform state owner."
  type = object({
    resource_group_name                 = string
    container_app_environment_id        = string
    acr_login_server                    = string
    kafka_bootstrap_servers             = string
    operational_kafka_bootstrap_servers = optional(string, "")
  })
}

variable "image" {
  description = "Promoted Core OCI image. Pin by digest for protected environments."
  type        = string
}

variable "bootstrap" {
  description = "Required provider and PostgreSQL coordinates consumed by the Core bootstrap."
  type = object({
    azure_tenant_id       = string
    azure_subscription_id = string
    azure_region          = string
    postgres_host         = string
    postgres_database     = string
  })
}

variable "identity" {
  description = "Service-owned workload identity outputs supplied by the identity state owner."
  type = object({
    resource_id        = string
    client_id          = string
    extra_resource_ids = optional(list(string), [])
  })
}

variable "event_topics" {
  description = "Event Hub entity names owned by the shared event-bus state."
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
  description = "Role-scoped database secret reference supplied by the state-store state owner."
  type = object({
    dsn_secret_id = string
    host          = string
    role          = string
  })
  sensitive = true
  validation {
    condition     = trimspace(var.database.host) != ""
    error_message = "database.host must contain the non-secret PostgreSQL endpoint identity."
  }
}

variable "health" {
  description = "Internal health probe contract."
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
  default = {
    port           = 8080
    liveness_path  = "/live"
    readiness_path = "/ready"
    # The runtime opens this port only after startup readiness runs its four phases,
    # each bounded by phase_timeout_seconds, so the startup budget must exceed 4 x 75s.
    startup_path          = "/live"
    startup_failure_count = 90
  }
}

variable "rollback" {
  description = "Revision rollback contract consumed by the deployment orchestrator."
  type = object({
    strategy                 = string
    previous_image           = string
    max_unavailable_replicas = optional(number, 0)
  })

  validation {
    condition     = contains(["previous-revision", "image-redeploy"], var.rollback.strategy)
    error_message = "rollback.strategy must be previous-revision or image-redeploy."
  }
}

variable "runtime_env" {
  description = "Deployment environment, independent of authority and execution venue."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.runtime_env)
    error_message = "runtime_env must be dev, staging, or prod."
  }
}

variable "startup_readiness" {
  description = "Bounded Event Hubs consumer-settle and startup probe deadlines."
  type = object({
    kafka_settle_seconds  = number
    probe_timeout_seconds = number
    phase_timeout_seconds = number
  })
  default = {
    kafka_settle_seconds  = 12
    probe_timeout_seconds = 30
    phase_timeout_seconds = 75
  }

  validation {
    condition = (
      var.startup_readiness.kafka_settle_seconds >= 0 &&
      var.startup_readiness.probe_timeout_seconds > var.startup_readiness.kafka_settle_seconds &&
      var.startup_readiness.phase_timeout_seconds > var.startup_readiness.probe_timeout_seconds * 2
    )
    error_message = "startup_readiness requires non-negative settle time, a larger probe timeout, and phase headroom beyond both default retry attempts."
  }
}

variable "llm" {
  description = "Attested Core model endpoint and controlled external-information egress settings."
  type = object({
    endpoint                   = string
    web_search_enabled         = optional(bool, false)
    web_search_allowed_domains = optional(list(string), [])
    web_search_max_results     = optional(number, 8)
    web_search_timeout_seconds = optional(number, 45)
    resolved_models_digest     = optional(string, "")
  })

  validation {
    condition = can(regex(
      "^https://[^/?#]+/?$",
      trimspace(var.llm.endpoint)
    ))
    error_message = "llm.endpoint must be an HTTPS origin without a path, query, or fragment."
  }

  validation {
    condition = (
      length(var.llm.web_search_allowed_domains) <= 100 &&
      alltrue([
        for domain in var.llm.web_search_allowed_domains :
        can(regex("^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$", domain))
      ]) &&
      (!var.llm.web_search_enabled || length(var.llm.web_search_allowed_domains) > 0) &&
      var.llm.web_search_max_results >= 1 &&
      var.llm.web_search_max_results <= 20 &&
      var.llm.web_search_timeout_seconds >= 0.1 &&
      var.llm.web_search_timeout_seconds <= 90
    )
    error_message = "Enabled web search requires 1-100 valid hosts, max_results in [1, 20], and timeout_seconds in [0.1, 90]."
  }

  validation {
    condition = (
      var.llm.resolved_models_digest == "" ||
      can(regex("^[0-9a-f]{64}$", var.llm.resolved_models_digest))
    )
    error_message = "llm.resolved_models_digest must be empty or a lowercase SHA-256 digest."
  }
}

variable "scaling" {
  description = "Replica and resource limits for the Core service."
  type = object({
    min_replicas = number
    max_replicas = number
    cpu          = number
    memory       = string
  })
  default = {
    min_replicas = 1
    max_replicas = 3
    cpu          = 0.5
    memory       = "1Gi"
  }

  validation {
    condition     = var.scaling.min_replicas >= 1 && var.scaling.max_replicas >= var.scaling.min_replicas
    error_message = "Core requires at least one replica until a credential-free Kafka scaler is proven."
  }
}

variable "tags" {
  description = "Deployment-supplied generic resource tags."
  type        = map(string)
  default     = {}
}

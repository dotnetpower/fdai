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

variable "rca_reader_identity" {
  description = "Optional read-only Azure identity for Activity Log-backed T1 RCA."
  type = object({
    resource_id = optional(string, "")
    client_id   = optional(string, "")
  })
  default = {}

  validation {
    condition = (
      (trimspace(var.rca_reader_identity.resource_id) == "") ==
      (trimspace(var.rca_reader_identity.client_id) == "")
    )
    error_message = "rca_reader_identity resource_id and client_id must be configured together."
  }
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
    notification_receipts          = optional(string, "fdai.notifications.delivery-receipts")
  })
}

variable "teams_notification_binding" {
  description = "Explicit A2/A4 Teams Workflows activation. Saving an endpoint never activates delivery; this input does."
  type = object({
    enabled            = optional(bool, false)
    channel_id         = optional(string, "teams-ops")
    trust_tiers        = optional(list(string), ["a2_operational_alert"])
    endpoint_secret_id = optional(string, "")
  })
  default = {}
  validation {
    condition = !var.teams_notification_binding.enabled || (
      trimspace(var.teams_notification_binding.channel_id) != "" &&
      trimspace(var.teams_notification_binding.endpoint_secret_id) != "" &&
      length(var.teams_notification_binding.trust_tiers) > 0
    )
    error_message = "An activated Teams notification binding requires a channel id, an endpoint secret id, and at least one trust tier."
  }
  validation {
    condition = length(setsubtract(
      toset(var.teams_notification_binding.trust_tiers),
      toset(["a2_operational_alert", "a4_digest"]),
    )) == 0
    error_message = "A Teams Workflows notification binding may only carry a2_operational_alert or a4_digest; A1 approvals require the authenticated Bot path."
  }
}

variable "teams_approval_destination" {
  description = "Optional group-connected Teams destination and Bot activity endpoint for A1."
  type = object({
    team_id      = string
    channel_id   = string
    activity_url = string
  })
  default = {
    team_id      = ""
    channel_id   = ""
    activity_url = ""
  }
  validation {
    condition = length(compact([
      var.teams_approval_destination.team_id,
      var.teams_approval_destination.channel_id,
      var.teams_approval_destination.activity_url,
      ])) == 0 || (
      length(compact([
        var.teams_approval_destination.team_id,
        var.teams_approval_destination.channel_id,
        var.teams_approval_destination.activity_url,
      ])) == 3 &&
      startswith(var.teams_approval_destination.activity_url, "https://")
    )
    error_message = "Teams approval team_id, channel_id, and HTTPS activity_url must be configured together."
  }
}

variable "stewardship_gitops" {
  description = "Platform-owned Key Vault reference and target for review-only stewardship PRs."
  type = object({
    enabled         = optional(bool, false)
    owner           = optional(string, "")
    repo            = optional(string, "")
    token_secret_id = optional(string, "")
  })
  default   = {}
  sensitive = true

  validation {
    condition = !var.stewardship_gitops.enabled || (
      trimspace(var.stewardship_gitops.owner) != "" &&
      trimspace(var.stewardship_gitops.repo) != "" &&
      trimspace(var.stewardship_gitops.token_secret_id) != ""
    )
    error_message = "Enabled stewardship GitOps requires owner, repo, and token_secret_id."
  }
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

variable "stewardship_audit_interval_seconds" {
  description = "Interval for scheduled steward and maintainer Entra liveness checks."
  type        = number
  default     = 3600

  validation {
    condition     = var.stewardship_audit_interval_seconds >= 60
    error_message = "stewardship_audit_interval_seconds MUST be >= 60."
  }
}

variable "handover_knowledge_interval_seconds" {
  description = "Interval for restart-safe handover gap and candidate event production."
  type        = number
  default     = 60

  validation {
    condition     = var.handover_knowledge_interval_seconds >= 10
    error_message = "handover_knowledge_interval_seconds MUST be >= 10."
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
    model_endpoints            = optional(map(string), {})
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
      length(var.llm.model_endpoints) <= 16 &&
      alltrue([
        for reference, endpoint in var.llm.model_endpoints :
        (
          startswith(reference, "azure-openai:") &&
          can(regex(
            "^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$",
            trimprefix(reference, "azure-openai:")
          )) &&
          lower(trimsuffix(trimspace(endpoint), "/")) == "https://${trimprefix(reference, "azure-openai:")}.openai.azure.com"
          ) || (
          startswith(reference, "azure-foundry:") &&
          can(regex(
            "^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$",
            trimprefix(reference, "azure-foundry:")
          )) &&
          lower(trimsuffix(trimspace(endpoint), "/")) == "https://${trimprefix(reference, "azure-foundry:")}.services.ai.azure.com"
        )
      ])
    )
    error_message = "llm.model_endpoints must contain at most 16 exact account-qualified Azure OpenAI or Foundry HTTPS origins."
  }

  validation {
    condition = (
      length(var.llm.model_endpoints) == 0 ||
      contains(
        [for endpoint in values(var.llm.model_endpoints) : lower(trimsuffix(trimspace(endpoint), "/"))],
        lower(trimsuffix(trimspace(var.llm.endpoint), "/"))
      )
    )
    error_message = "llm.model_endpoints must include the primary llm.endpoint origin when provided."
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

variable "observation_context" {
  description = "Optional deployment-owned signed context for Heimdall executed-action observations."
  type = object({
    enabled                     = optional(bool, false)
    signing_seed_secret_id      = optional(string, "")
    executor_credential_lineage = optional(string, "")
    source_credential_lineage   = optional(string, "")
  })
  default = {}

  validation {
    condition = !var.observation_context.enabled || (
      can(regex("^https://[^/]+/secrets/[^/]+(/[^/]+)?$", var.observation_context.signing_seed_secret_id)) &&
      trimspace(var.observation_context.executor_credential_lineage) != "" &&
      trimspace(var.observation_context.source_credential_lineage) != "" &&
      lower(trimspace(var.observation_context.executor_credential_lineage)) != lower(trimspace(var.observation_context.source_credential_lineage))
    )
    error_message = "Enabled observation_context requires a Key Vault secret id and distinct executor and source credential lineages."
  }
}

variable "governed_rca" {
  description = "Optional principal-scoped governed document evidence for automated Incident RCA."
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

  validation {
    condition = !var.governed_rca.enabled || (
      trimspace(var.governed_rca.document_dsn_secret_id) != "" &&
      trimspace(var.governed_rca.collection_id) != "" &&
      length(var.governed_rca.allowed_access_refs) >= 1 &&
      length(var.governed_rca.allowed_access_refs) <= 64 &&
      var.governed_rca.allowed_access_refs == sort(distinct(var.governed_rca.allowed_access_refs)) &&
      alltrue([for value in var.governed_rca.allowed_access_refs : trimspace(value) != ""]) &&
      length(var.governed_rca.actor_groups) >= 1 &&
      length(var.governed_rca.actor_groups) <= 64 &&
      var.governed_rca.actor_groups == sort(distinct(var.governed_rca.actor_groups)) &&
      alltrue([for value in var.governed_rca.actor_groups : trimspace(value) != ""]) &&
      var.governed_rca.freshness_ceiling_seconds >= 60 &&
      var.governed_rca.freshness_ceiling_seconds <= 604800 &&
      floor(var.governed_rca.freshness_ceiling_seconds) == var.governed_rca.freshness_ceiling_seconds
    )
    error_message = "Enabled governed_rca requires a read-only DSN secret, collection, 1-64 ordered unique access refs and groups, and a freshness ceiling in [60, 604800]."
  }
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

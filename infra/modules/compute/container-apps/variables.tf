variable "env_name" {
  description = "Container Apps environment name (CAF: cae-<workload>[-env][-region])."
  type        = string
}

variable "infrastructure_subnet_id" {
  description = "Delegated subnet the Container App Environment binds for VNet integration (private-networking tenants). Null keeps the environment on the Azure-managed public network."
  type        = string
  default     = null
}

variable "core_app_name" {
  description = "Container App name for the unified core (CAF: ca-<workload>[-env][-region]-core)."
  type        = string
}

variable "core_job_name_prefix" {
  description = "Compact CAF prefix used only when a Core-derived Container Apps Job name would exceed 32 characters."
  type        = string
  default     = ""
}

variable "oob_job_name" {
  description = "Container Apps Job name for out-of-band scheduled probes (CAF: caj-<workload>[-env][-region]-oob)."
  type        = string
}

variable "rule_watcher_job_name" {
  description = "Container Apps Job name for the rule-catalog source watcher (CAF: caj-<workload>[-env][-region]-rule-watcher)."
  type        = string
}

variable "provider_schema_job_name" {
  description = "Container Apps Job name for global provider-schema drift accounting."
  type        = string
}

variable "browser_evidence_cleanup_job_name" {
  description = "Container Apps Job name for browser-evidence retention cleanup (CAF: caj-<workload>[-env][-region]-browser-gc)."
  type        = string
}

variable "rule_watcher_cron_expression" {
  description = "Cron for the rule watcher job. Daily at 03:00 UTC; the CLI filters by manifest cadence so weekly / monthly sources fire from the same job."
  type        = string
  default     = "0 3 * * *"
}

variable "provider_schema_cron_expression" {
  description = "UTC cron for global provider-schema refresh. Empty disables the Job."
  type        = string
  default     = ""
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Enclosing resource group."
  type        = string
}

variable "log_workspace_id" {
  description = "Log Analytics workspace resource id (Container Apps binds here)."
  type        = string
}

variable "executor_identity_id" {
  description = "User-assigned MI resource id used by both the app and the job."
  type        = string
}

variable "executor_identity_client_id" {
  description = "Client id selecting the executor when multiple user-assigned identities are attached."
  type        = string
}

variable "scheduler_identity_id" {
  description = "Dedicated non-executor scheduler Job Managed Identity resource id."
  type        = string
  default     = ""
}

variable "scheduler_identity_client_id" {
  description = "Client id selecting the dedicated scheduler Job identity."
  type        = string
  default     = ""
}

variable "dr_drill_identity_id" {
  description = "Dedicated DB-DR Job Managed Identity resource id."
  type        = string
  default     = ""
}

variable "dr_drill_identity_client_id" {
  description = "Client id selecting the dedicated DB-DR Job identity."
  type        = string
  default     = ""
}

variable "change_identity_client_id" {
  description = "Client id of the attached Change Safety execution identity."
  type        = string
}

variable "resilience_identity_client_id" {
  description = "Client id of the attached Resilience execution identity."
  type        = string
}

variable "finops_identity_client_id" {
  description = "Client id of the attached Cost Governance execution identity."
  type        = string
}

variable "isolated_executor_authority_cutover" {
  description = "Route Core direct-API execution over the isolated Executor command transport."
  type        = bool
  default     = false
}

variable "startup_kafka_settle_seconds" {
  description = "Seconds allowed for the startup probe consumer to join before publishing."
  type        = number
}

variable "startup_probe_timeout_seconds" {
  description = "Per-probe startup readiness deadline in seconds."
  type        = number
}

variable "startup_phase_timeout_seconds" {
  description = "Per-phase startup readiness deadline in seconds."
  type        = number
}

variable "inventory_identity_id" {
  description = "Dedicated read-only user-assigned MI resource id for inventory discovery."
  type        = string
}

variable "inventory_identity_client_id" {
  description = "Client id of the dedicated inventory managed identity."
  type        = string
}

variable "canary_identity_id" {
  description = "Dedicated canary publisher UAMI resource id."
  type        = string
}

variable "canary_identity_client_id" {
  description = "Client id of the dedicated canary publisher UAMI."
  type        = string
}

variable "canary_topic" {
  description = "Dedicated Event Hubs topic consumed only by the trusted canary path."
  type        = string
}

variable "operational_kafka_bootstrap_servers" {
  description = "Kafka endpoint for isolated raw inventory and canary traffic."
  type        = string
}

variable "canary_cron_expression" {
  description = "Cron for the full-loop synthetic canary. Empty disables the job."
  type        = string
  default     = "*/5 * * * *"
}

variable "ohl_evidence_enabled" {
  description = "Whether to provision the manual OHL scale-out proposal Job."
  type        = bool
  default     = false
}

variable "ohl_evidence_identity_id" {
  description = "Dedicated proposal-only OHL publisher UAMI resource id."
  type        = string
  default     = ""
}

variable "ohl_evidence_identity_client_id" {
  description = "Client id of the dedicated proposal-only OHL publisher UAMI."
  type        = string
  default     = ""
}

variable "ohl_evidence_target_resource_id" {
  description = "Exact dedicated VMSS resource id bound to the OHL proposal Job."
  type        = string
  default     = ""
}

variable "ohl_evidence_campaign_id" {
  description = "Retry-stable campaign id bound to the OHL proposal Job."
  type        = string
  default     = ""
}

variable "ohl_evidence_initiator_principal_id" {
  description = "Human initiator object id recorded on the OHL operator request."
  type        = string
  default     = ""
}

variable "inventory_dsn_secret_id" {
  description = "Key Vault secret id containing the inventory snapshot PostgreSQL DSN."
  type        = string
  sensitive   = true
}

variable "inventory_cron_expression" {
  description = "Cron for inventory due checks and failed-attempt retries. Empty disables the job."
  type        = string
  default     = ""
}

variable "inventory_kubernetes_api_server" {
  description = "Credential-free HTTPS AKS API endpoint for optional runtime topology inventory."
  type        = string
  default     = ""
}

variable "inventory_kubernetes_cluster_ref" {
  description = "Exact AKS cluster ARM id bound to runtime topology inventory."
  type        = string
  default     = ""
}

variable "inventory_kubernetes_ca_pem" {
  description = "Public CA PEM used to verify the configured AKS API endpoint."
  type        = string
  default     = ""
}

variable "inventory_kubernetes_audience" {
  description = "Deployment-supplied audience for the short-lived AKS workload identity token."
  type        = string
  default     = ""
}

variable "browser_evidence_cleanup_cron_expression" {
  description = "Cron for browser-evidence retention cleanup. Empty disables the Job."
  type        = string
  default     = ""
}

variable "browser_evidence_cleanup_limit" {
  description = "Maximum expired browser-evidence artifacts removed by one scheduled run."
  type        = number
  default     = 100

  validation {
    condition     = var.browser_evidence_cleanup_limit >= 1 && var.browser_evidence_cleanup_limit <= 500 && floor(var.browser_evidence_cleanup_limit) == var.browser_evidence_cleanup_limit
    error_message = "browser_evidence_cleanup_limit must be an integer in [1, 500]."
  }
}

variable "observation_campaign_cron_expression" {
  description = "Cron for the due-checked observation campaign. Empty disables the job."
  type        = string
  default     = ""
}

variable "inventory_sources" {
  description = "Ordered inventory source fallback list."
  type        = string
  default     = "arg,arm"
}

variable "inventory_freshness_seconds" {
  description = "Inventory freshness budget in seconds."
  type        = number
  default     = 86400
}

variable "inventory_reconciliation_interval_seconds" {
  description = "Minimum successful snapshot age before a routine full reconciliation."
  type        = number
  default     = 21600
}

variable "inventory_change_min_interval_seconds" {
  description = "Floor between change-triggered reconciliations."
  type        = number
  default     = 120
}

variable "inventory_progress_deadline_seconds" {
  description = "Re-arming no-progress deadline for one inventory source attempt."
  type        = number
  default     = 900
}

variable "inventory_attempt_deadline_seconds" {
  description = "Absolute wall-clock ceiling for one inventory source attempt."
  type        = number
  default     = 1500
}

variable "inventory_arg_requests_per_second" {
  description = "Sustained Azure Resource Graph request budget shared by one scan."
  type        = number
  default     = 3
}

variable "extra_identity_ids" {
  description = <<-EOT
    Additional user-assigned MI resource ids to attach alongside the
    executor MI. Populate with the per-vertical MIs (change / resilience /
    finops) from `infra/main.tf` when a fork wires vertical-specific
    delivery adapters that need to `assume` those identities. Empty by
    default so upstream stays single-MI.
  EOT
  type        = list(string)
  default     = []
}

variable "email_endpoint" {
  description = "ACS Email endpoint. Empty leaves email notification adapters disabled."
  type        = string
  default     = ""
}

variable "email_sender_address" {
  description = "Verified ACS Email sender address."
  type        = string
  default     = ""
}

variable "email_recipient_addresses_json" {
  description = "JSON array of A2/A4 notification recipient addresses."
  type        = string
  default     = "[]"
}

variable "notification_identity_client_id" {
  description = "Client id selecting the dedicated notification UAMI."
  type        = string
  default     = ""
}

variable "console_base_url" {
  description = "Public HTTPS origin of the read-only console used for notification evidence links."
  type        = string
  default     = ""
}

variable "image" {
  description = "Container image reference. Pin by digest in prod."
  type        = string
}

variable "acr_login_server" {
  description = <<-EOT
    Login server host of the private ACR that holds `var.image`
    (e.g. "crfdaidev.azurecr.io"). When non-empty, a `registry {}`
    block is attached to the Container App and image pull authenticates
    via the executor MI (which the root module grants `AcrPull` on).
    Leave empty only when the supplied FDAI image is publicly readable.
  EOT
  type        = string
  default     = ""
}

variable "oob_cpu" {
  description = "CPU quota for the out-of-band scheduled probes container (typically half of core)."
  type        = number
  default     = 0.25

  validation {
    condition     = var.oob_cpu >= 0.25 && var.oob_cpu <= 4.0
    error_message = "oob_cpu must be between 0.25 and 4.0."
  }
}

variable "oob_memory" {
  description = "Memory quota for the out-of-band container."
  type        = string
  default     = "0.5Gi"

  validation {
    condition     = can(regex("^[0-9]+(\\.[0-9]+)?Gi$", var.oob_memory))
    error_message = "oob_memory must be a Container Apps value like `0.5Gi`."
  }
}

# ---------------------------------------------------------------------------
# Persistence DSN (Key Vault-backed).
#
# Legacy scheduled jobs use the platform StateStore DSN. Independent runtime
# services receive role-scoped database references from service-owned roots.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Core-config env vars.
#
# `EnvVarConfigProvider` in `src/fdai/shared/config/provider.py` REQUIRES
# these to be set at startup or the process raises `ConfigError` and
# refuses to boot (see `_ENV_VAR_MAP`). Without them the Container App
# would crash-loop, so they are wired here as plain (non-secret) env
# entries with sensible defaults where the schema permits.
# ---------------------------------------------------------------------------
variable "azure_tenant_id" {
  description = "Entra tenant id (`AZURE_TENANT_ID` in the runtime config)."
  type        = string
}

variable "azure_subscription_id" {
  description = "Enclosing subscription id (`AZURE_SUBSCRIPTION_ID`)."
  type        = string
}

variable "azure_resource_group" {
  description = "Target resource group (`AZURE_RESOURCE_GROUP`); non-secret."
  type        = string
}

variable "azure_region" {
  description = "Azure region short name (`AZURE_REGION`)."
  type        = string
}

variable "kafka_bootstrap_servers" {
  description = "Event Hubs Kafka endpoint (`KAFKA_BOOTSTRAP_SERVERS`) - `<ns>.servicebus.windows.net:9093`."
  type        = string
}

variable "kafka_topic_events" {
  description = "Primary event-ingest topic (`KAFKA_TOPIC_EVENTS`)."
  type        = string
  default     = "fdai.change.events"
}

variable "semantic_turn_request_topic" {
  description = "Existing Kafka topic carrying bounded semantic-turn requests. Empty disables semantic turn consumption."
  type        = string
  default     = ""
}

variable "semantic_turn_projection_topic" {
  description = "Existing Kafka topic carrying semantic-turn terminal projections. Empty disables semantic turn consumption."
  type        = string
  default     = ""
}

variable "semantic_turn_physical_topic" {
  description = "Physical Event Hub carrying multiplexed semantic-turn logical topics."
  type        = string
  default     = ""
}

variable "read_investigation_request_topic" {
  description = "Logical read-investigation request topic multiplexed over the semantic physical Event Hub."
  type        = string
  default     = ""
}

variable "postgres_host" {
  description = "Postgres Flexible Server FQDN (`POSTGRES_HOST`) - non-secret label used for the startup log summary."
  type        = string
}

variable "postgres_database" {
  description = "Postgres database name (`POSTGRES_DATABASE`) - non-secret label."
  type        = string
}

variable "runtime_env" {
  description = "`RUNTIME_ENV` - one of `dev` / `staging` / `prod`."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.runtime_env)
    error_message = "runtime_env must be dev, staging, or prod."
  }
}

variable "autonomy_mode_default" {
  description = "`AUTONOMY_MODE_DEFAULT` - MUST default to `shadow` per coding-conventions."
  type        = string
  default     = "shadow"

  validation {
    condition     = contains(["shadow", "enforce"], var.autonomy_mode_default)
    error_message = "autonomy_mode_default must be shadow or enforce."
  }
}

variable "dev_operations_gateway_url" {
  description = "Development operations Function App HTTPS origin. Empty disables the runtime DirectApiExecutor binding."
  type        = string
  default     = ""
}

variable "dev_operations_gateway_audience" {
  description = "Microsoft Entra audience requested by the core executor when calling the development operations gateway."
  type        = string
  default     = ""
}

variable "monitor_workspace_customer_id" {
  description = <<-EOT
    Log Analytics workspace **customer GUID** (from
    ``module.log_analytics.workspace_customer_id`` - the
    ``azurerm_log_analytics_workspace.workspace_id`` attribute, NOT the
    ARM resource id). When non-empty, wires the ``FDAI_MONITOR_WORKSPACE_ID``
    env var so ``wire_azure_container`` auto-binds
    ``AzureMonitorLogsMetricProvider`` at startup instead of leaving
    ``container.metric_provider`` as the upstream ``NoopMetricProvider``
    default. Empty (default) keeps the no-op adapter, matching the
    dev-mode parity contract for local-fake runs. Non-secret (it is a
    workspace identifier, not an ingestion key), so wired as a plain env
    entry rather than through a Container App secret.
  EOT
  type        = string
  default     = ""
}

variable "case_history_container_url" {
  description = "Private HTTPS Blob container URL for FDAI_CASE_HISTORY_CONTAINER_URL."
  type        = string
  default     = ""
}

variable "case_history_identity_client_id" {
  description = "Client id of the dedicated case-history managed identity."
  type        = string
  default     = ""
}

variable "case_history_retention_days" {
  description = "Active case-history retention in days."
  type        = number
  default     = 30
}

variable "case_history_deletion_days" {
  description = "Case-history deletion due offset in days."
  type        = number
  default     = 60
}

variable "rule_catalog_snapshot_container_url" {
  description = "Durable private Blob container URL for the rule-watcher job's mirrored source snapshots (FDAI_RULE_CATALOG_SNAPSHOT_CONTAINER_URL). Empty disables the durable-mirror stage."
  type        = string
  default     = ""
}

variable "gitops_owner" {
  description = "GitHub owner (org or user) the rule-watcher's review-only collection PR targets (FDAI_GITOPS_OWNER). Empty disables PR publication."
  type        = string
  default     = ""
}

variable "gitops_repo" {
  description = "GitHub repository the rule-watcher's review-only collection PR targets (FDAI_GITOPS_REPO)."
  type        = string
  default     = ""
}

variable "gitops_token_secret_id" {
  description = "Key Vault secret resource id for the GitHub token the rule-watcher job uses to open review-only collection PRs (FDAI_GITOPS_TOKEN). A secret reference only - never a literal token value; empty disables PR publication."
  type        = string
  default     = ""
  sensitive   = true
}

variable "state_store_dsn_secret_id" {
  description = "Key Vault secret resource id backing FDAI_STATE_STORE_DSN. Empty = fall back to in-memory."
  type        = string
  default     = ""
  sensitive   = true
}

variable "tags" {
  description = "Tags."
  type        = map(string)
  default     = {}
}

variable "vm_task_enabled" {
  description = "Bind the governed VM task ToolExecutor in the core app."
  type        = bool
  default     = false
}

variable "vm_task_enforce" {
  description = "Allow promoted VM tasks to run after risk gate and Owner HIL."
  type        = bool
  default     = false
}

variable "vm_task_run_as_user" {
  description = "Non-root Linux account configured on VM task hosts."
  type        = string
  default     = "fdai-task"
}

variable "vm_task_root" {
  description = "Private guest task root configured on VM task hosts."
  type        = string
  default     = "/var/lib/fdai/tasks"
}


# ---------------------------------------------------------------------------
# Scheduler tick job (opt-in; see docs/internals/sre-agent-gap-analysis.md P2-6).
# ---------------------------------------------------------------------------

variable "scheduler_cron_expression" {
  description = "Cron for the scheduler tick Container Apps Job that drives SchedulerService.run_once. Empty string disables the job (default)."
  type        = string
  default     = ""
}


# ---------------------------------------------------------------------------
# Analyzer tick job - drives the reference threshold analyzers
# out-of-band so metric-based scenarios (node_cpu_percent, http_429_rate,
# ...) get periodic detection. Bounded below by the metric backend's
# ingestion lag (AKS Managed Prometheus ~15 s, Azure Monitor Logs KQL
# ~2-5 min); pick 60 s cron as the safe default.
# ---------------------------------------------------------------------------

variable "analyzer_tick_cron_expression" {
  description = "Cron for the analyzer and detection-readiness tick Container Apps Job. The one-minute default enables shadow observation; an explicit empty string disables it."
  type        = string
  default     = "* * * * *"
}

variable "analyzer_targets_json" {
  description = "Optional JSON array of {resource_id, kind} pairs the analyzer tick investigates each fire. Empty uses the durable inventory projection."
  type        = string
  default     = ""
}

variable "trace_topologies_json" {
  description = "Optional JSON array of {topology_ref, resource_ref, expected_hops} declarations for shadow trace-continuity checks."
  type        = string
  default     = ""
}

variable "analyzer_window_seconds" {
  description = "Optional window (seconds) each analyzer looks back on this tick. Empty -> CLI default (300 s)."
  type        = string
  default     = ""
}

variable "trace_window_seconds" {
  description = "Optional trace-continuity detection window (seconds). One window yields at most one finding, so this MUST be several times shorter than the correlation window. Empty -> analyzer window."
  type        = string
  default     = ""
}

variable "analyzer_budget_seconds" {
  description = "Optional budget (seconds) the coordinator applies to the whole tick before it marks BUDGET_EXCEEDED. Empty -> CLI default (60 s)."
  type        = string
  default     = ""
}

variable "forecast_tick_cron_expression" {
  description = "Cron for the mechanical forecast evaluation tick Job. Empty disables it."
  type        = string
  default     = ""
}

variable "forecast_targets_json" {
  description = "JSON array of governed forecast target specifications consumed by Heimdall."
  type        = string
  default     = ""
}

variable "cost_governance_image" {
  description = "Optional Cost Governance distribution image. Empty provisions no package jobs."
  type        = string
  default     = ""
}

variable "cost_governance_collector_cron_expression" {
  description = "Cron for the activation-gated cost collector. Empty disables the Job."
  type        = string
  default     = ""
}

variable "cost_governance_analyzer_cron_expression" {
  description = "Cron for the activation-gated cost analyzer. Empty disables the Job."
  type        = string
  default     = ""
}

variable "cost_governance_scope_id" {
  description = "Exact Azure Cost Management scope for the optional collector."
  type        = string
  default     = ""
}

variable "cost_governance_known_service_ids_json" {
  description = "JSON list of ontology-grounded service ids accepted by the cost jobs."
  type        = string
  default     = ""
}

variable "cost_governance_ontology_release_id" {
  description = "Exact ontology release id required by the installed Cost Governance package."
  type        = string
  default     = ""
}

variable "cost_governance_ontology_release_digest" {
  description = "Exact SHA-256 ontology release digest required by the package."
  type        = string
  default     = ""
}

variable "prometheus_endpoint" {
  description = <<-EOT
    Base URL of a Prometheus-compatible query API (AKS Managed Prometheus,
    self-hosted Prom, Thanos, Cortex, Mimir). When non-empty, wires the
    ``FDAI_PROMETHEUS_ENDPOINT`` env var so ``wire_azure_container``
    picks Prom as the primary route for its supported metrics
    (sub-minute detection) with Azure Monitor Logs as the fallback for
    non-AKS metrics. Empty (default) keeps AML-only (or Noop) binding.
  EOT
  type        = string
  default     = ""
}

variable "prometheus_audience" {
  description = <<-EOT
    OIDC audience for the Prometheus bearer token. AKS Managed
    Prometheus with AAD requires ``https://prometheus.monitor.azure.com``.
    Empty -> unauthenticated Prom (self-hosted / behind network policy).
  EOT
  type        = string
  default     = ""
}


# ---------------------------------------------------------------------------
# Deep DB-DR drill (opt-in; see docs/runbooks/db-dr-drill.md).
# ---------------------------------------------------------------------------

variable "dr_drill_enabled" {
  description = "Toggle the scheduled DB-DR drill Container Apps Job."
  type        = bool
  default     = false
}

variable "dr_drill_job_name" {
  description = "Container Apps Job name for the DB-DR drill (32-char limit)."
  type        = string
  default     = ""
}

variable "dr_drill_cron_expression" {
  description = "Cron for the DB-DR drill. Default: 04:00 UTC on the 1st and 15th."
  type        = string
  default     = "0 4 1,15 * *"
}

variable "dr_drill_source_server_arm_id" {
  description = "ARM id of the production Postgres Flexible Server whose PITR checkpoint the drill restores. Required when dr_drill_enabled = true."
  type        = string
  default     = ""
}

variable "dr_drill_target_resource_group" {
  description = "Pre-created isolated resource group where the drill restores its temporary server."
  type        = string
  default     = ""
}

variable "dr_drill_target_server_prefix" {
  description = "Prefix for the drill target Postgres server name (short - timestamp is appended)."
  type        = string
  default     = "psql-drill"
}

variable "dr_drill_pitr_offset_minutes" {
  description = "How many minutes back from now the drill restore point sits."
  type        = number
  default     = 30
}

variable "dr_drill_integrity_tables" {
  description = "Ordered PostgreSQL tables whose counts and deterministic checksums the drill compares."
  type        = list(string)
  default     = ["alembic_version"]
}

variable "dr_drill_dry_run" {
  description = "When true, the drill CLI logs its composed config and exits without touching Azure. Set false in production."
  type        = bool
  default     = true
}

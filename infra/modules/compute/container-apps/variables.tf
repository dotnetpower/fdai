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

variable "oob_job_name" {
  description = "Container Apps Job name for out-of-band scheduled probes (CAF: caj-<workload>[-env][-region]-oob)."
  type        = string
}

variable "rule_watcher_job_name" {
  description = "Container Apps Job name for the rule-catalog source watcher (CAF: caj-<workload>[-env][-region]-rule-watcher)."
  type        = string
}

variable "rule_watcher_cron_expression" {
  description = "Cron for the rule watcher job. Daily at 03:00 UTC; the CLI filters by manifest cadence so weekly / monthly sources fire from the same job."
  type        = string
  default     = "0 3 * * *"
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

variable "inventory_identity_id" {
  description = "Dedicated read-only user-assigned MI resource id for inventory discovery."
  type        = string
}

variable "inventory_identity_client_id" {
  description = "Client id of the dedicated inventory managed identity."
  type        = string
}

variable "inventory_raw_topic" {
  description = "Raw Event Grid resource-change Event Hub consumed by Huginn's realtime discovery normalizer."
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

variable "inventory_dsn_secret_id" {
  description = "Key Vault secret id containing the inventory snapshot PostgreSQL DSN."
  type        = string
  sensitive   = true
}

variable "inventory_cron_expression" {
  description = "Cron for inventory reconciliation. Empty disables the job."
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

variable "max_replicas" {
  description = "KEDA scale ceiling."
  type        = number
  default     = 3

  validation {
    # Container Apps hard limit is 300 replicas per revision. A day-zero
    # ceiling of 3 is a safe default; a fork raises it deliberately. A
    # ``0`` here would make the app unreachable, and an unbounded number
    # would let a burst blow through cost guardrails.
    condition     = var.max_replicas >= 1 && var.max_replicas <= 300
    error_message = "max_replicas must be between 1 and 300 (Container Apps limit)."
  }
}

variable "core_cpu" {
  description = "CPU quota for the core container. Container Apps accepts increments of 0.25 up to 4.0."
  type        = number
  default     = 0.5

  validation {
    condition     = var.core_cpu >= 0.25 && var.core_cpu <= 4.0
    error_message = "core_cpu must be between 0.25 and 4.0 (Container Apps limit)."
  }
}

variable "core_memory" {
  description = "Memory quota for the core container (Container Apps expects Gi units, e.g. `1Gi`, `2Gi`)."
  type        = string
  default     = "1Gi"

  validation {
    condition     = can(regex("^[0-9]+(\\.[0-9]+)?Gi$", var.core_memory))
    error_message = "core_memory must be a Container Apps value like `1Gi` / `2.5Gi`."
  }
}

variable "health_port" {
  description = "Internal HTTP port for the core liveness and readiness probes. No ingress is exposed."
  type        = number
  default     = 8080

  validation {
    condition     = var.health_port >= 1 && var.health_port <= 65535
    error_message = "health_port must be between 1 and 65535."
  }
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

variable "min_replicas" {
  description = <<-EOT
    Floor replica count. Day-zero default 1 keeps the P1 control loop
    reachable without a KEDA scale rule; a fork that adds a scale rule
    tied to Event Hubs unprocessed-message lag MAY flip this back to 0
    for scale-to-zero. If it stays 0 without a scale rule, incoming
    Kafka events never wake the app - a silent regression that only
    the KPI dashboard would eventually surface.
  EOT
  type        = number
  default     = 1

  validation {
    condition     = var.min_replicas >= 0 && var.min_replicas <= var.max_replicas
    error_message = "min_replicas must be >= 0 and <= max_replicas."
  }
}

# ---------------------------------------------------------------------------
# Persistence DSNs (Key Vault-backed).
#
# The core control plane reads three env vars for its Postgres seams
# (`FDAI_STATE_STORE_DSN`, `FDAI_OPERATOR_MEMORY_DSN`,
# `FDAI_T1_PATTERN_LIBRARY_DSN`). Each is delivered as a Container App
# `secret {}` block that resolves a Key Vault secret via the executor
# user-assigned MI (which the KV module has already granted `Secrets User`
# on). The env var references the Container App secret, not the KV URI, so
# rotating the KV value never touches the app template.
#
# Empty string means "not wired" - the composition root then falls back
# to the in-memory backend (`_build_state_store` etc. in `src/fdai/__main__.py`).
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
  default     = "aw.change.events"
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

variable "state_store_dsn_secret_id" {
  description = "Key Vault secret resource id backing FDAI_STATE_STORE_DSN. Empty = fall back to in-memory."
  type        = string
  default     = ""
  sensitive   = true
}

variable "operator_memory_dsn_secret_id" {
  description = "Key Vault secret resource id backing FDAI_OPERATOR_MEMORY_DSN. Empty = fall back to in-memory."
  type        = string
  default     = ""
  sensitive   = true
}

variable "pattern_library_dsn_secret_id" {
  description = "Key Vault secret resource id backing FDAI_T1_PATTERN_LIBRARY_DSN. Empty = fall back to in-memory."
  type        = string
  default     = ""
  sensitive   = true
}

variable "chatops_webhook_url_secret_id" {
  description = "Key Vault secret id containing the HIL webhook URL. Empty disables push delivery."
  type        = string
  sensitive   = true
  default     = ""
}

variable "chatops_webhook_secret_id" {
  description = "Key Vault secret id containing the HIL HMAC secret."
  type        = string
  sensitive   = true
  default     = ""
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
# Analyzer tick job (opt-in) - drives the reference threshold analyzers
# out-of-band so metric-based scenarios (node_cpu_percent, http_429_rate,
# ...) get periodic detection. Bounded below by the metric backend's
# ingestion lag (AKS Managed Prometheus ~15 s, Azure Monitor Logs KQL
# ~2-5 min); pick 60 s cron as the safe default.
# ---------------------------------------------------------------------------

variable "analyzer_tick_cron_expression" {
  description = "Cron for the analyzer tick Container Apps Job that drives the reference threshold analyzers. Empty string disables the job (default)."
  type        = string
  default     = ""
}

variable "analyzer_targets_json" {
  description = "JSON array of {resource_id, kind} pairs the analyzer tick investigates each fire. Empty (default) -> the CLI logs a no-targets info line and exits 0, so a mis-provisioned cron stays quiet."
  type        = string
  default     = ""
}

variable "analyzer_window_seconds" {
  description = "Optional window (seconds) each analyzer looks back on this tick. Empty -> CLI default (300 s)."
  type        = string
  default     = ""
}

variable "analyzer_budget_seconds" {
  description = "Optional budget (seconds) the coordinator applies to the whole tick before it marks BUDGET_EXCEEDED. Empty -> CLI default (60 s)."
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

variable "dr_drill_target_rg_prefix" {
  description = "Prefix for the isolated resource group the drill lands in."
  type        = string
  default     = "rg-fdai-dr-drill"
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

variable "dr_drill_dry_run" {
  description = "When true, the drill CLI logs its composed config and exits without touching Azure. Set false in production."
  type        = bool
  default     = true
}

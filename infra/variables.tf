# -----------------------------------------------------------------------
# Workload identity + naming
# -----------------------------------------------------------------------

variable "workload" {
  description = "Workload token used in every resource name. Fixed to 'fdai' by generic-scope.instructions.md; no customer identifier."
  type        = string
  default     = "fdai"
}

variable "env" {
  description = "Environment suffix appended after the workload token (e.g. 'dev', 'staging', 'prod'). Empty string yields the day-zero unqualified names."
  type        = string
  default     = ""

  validation {
    condition     = can(regex("^(|dev|staging|prod)$", var.env))
    error_message = "env must be one of: '', 'dev', 'staging', 'prod'."
  }
}

variable "enable_dev_operations_gateway" {
  description = "Provision the development-only Azure Functions operations gateway. Requires env=dev and private networking."
  type        = bool
  default     = false
}

variable "dev_operations_gateway_private_probes_json" {
  description = "Server-owned private probe aliases as JSON. Values contain HTTPS url and managed-identity audience."
  type        = string
  default     = "{}"

  validation {
    condition     = can(jsondecode(var.dev_operations_gateway_private_probes_json))
    error_message = "dev_operations_gateway_private_probes_json must be valid JSON."
  }
}

variable "region" {
  description = "Azure region for every resource in the RG (e.g. 'koreacentral', 'westeurope')."
  type        = string
}

variable "region_short" {
  description = "Region short-name used in name suffixes when env is set (e.g. 'krc', 'weu')."
  type        = string
  default     = ""
}

# -----------------------------------------------------------------------
# Tenant + sensitive inputs (from tfvars, never committed)
# -----------------------------------------------------------------------

variable "tenant_id" {
  description = "Entra tenant id for AAD auth on Postgres. Not committed; supplied via tfvars."
  type        = string
}

variable "postgres_admin_login" {
  description = "Postgres Flexible Server administrator login. Supplied via tfvars only."
  type        = string
  sensitive   = true

  validation {
    # Azure Postgres Flex rejects short logins and the reserved 'azure_superuser'
    # / 'admin' / 'root' family; catch the obvious bad values before an apply.
    condition     = length(var.postgres_admin_login) >= 4 && !contains(["admin", "root", "postgres", "azure_superuser"], lower(var.postgres_admin_login))
    error_message = "postgres_admin_login must be at least 4 chars and not one of admin / root / postgres / azure_superuser."
  }
}

variable "postgres_admin_password" {
  description = "Postgres Flexible Server administrator password. Supplied via tfvars only."
  type        = string
  sensitive   = true

  validation {
    # Reject the tfvars.example placeholder and obvious short strings; this is
    # not a strength policy (Azure enforces its own), just a guard against a
    # 'forgot to replace SET-ME-VIA-VAULT' apply that would 500-error midway.
    condition     = length(var.postgres_admin_password) >= 12 && var.postgres_admin_password != "SET-ME-VIA-VAULT"
    error_message = "postgres_admin_password must be at least 12 characters and MUST be replaced from the tfvars.example placeholder."
  }
}

# -----------------------------------------------------------------------
# Compute image reference
# -----------------------------------------------------------------------

variable "core_image" {
  description = <<-EOT
    FDAI container image reference for the core control-plane app. Supply an
    image built from this repository's Dockerfile. The supply-chain workflow
    publishes `ghcr.io/<owner>/<repo>:sha-<commit>` and records its digest.
    Production requires the digest form; a commit tag is acceptable in dev.
  EOT
  type        = string

  validation {
    condition = (
      trimspace(var.core_image) != "" &&
      !strcontains(lower(var.core_image), "mcr.microsoft.com/azure-cli") &&
      !startswith(lower(var.core_image), "replace")
    )
    error_message = "core_image must reference an FDAI runtime image, not azure-cli or a REPLACE placeholder."
  }
}

variable "max_replicas" {
  description = "Container App max replica count (KEDA scale ceiling). Day-zero default is 3."
  type        = number
  default     = 3
}

variable "canary_cron_expression" {
  description = "Full-loop canary cadence in UTC cron format. Empty disables canary publication."
  type        = string
  default     = "*/5 * * * *"
}

variable "log_retention_days" {
  description = "Log Analytics retention in days. UI-configurable post-deploy; 30 is the day-zero default."
  type        = number
  default     = 30
}

variable "additional_tags" {
  description = "Fork-supplied tags merged on top of the base FDAI tag set. Use the `fdai:` namespace for FDAI-owned keys (e.g. fdai:cost-center, fdai:owner, fdai:criticality); customer values live here, never in the base_tags literal."
  type        = map(string)
  default     = {}
}

variable "cost_vertical" {
  description = "AIOps vertical this deployment's cost is attributed to (rendered as the `fdai:vertical` tag). 'shared' for cross-vertical control-plane infra."
  type        = string
  default     = "shared"

  validation {
    condition     = contains(["shared", "resilience", "change-safety", "cost-governance"], var.cost_vertical)
    error_message = "cost_vertical must be one of: shared, resilience, change-safety, cost-governance."
  }
}

# -----------------------------------------------------------------------
# Seam-kind selectors (approved alternates per csp-neutrality.md)
# -----------------------------------------------------------------------

variable "compute_kind" {
  description = "Runtime seam implementation. Only 'container_apps' is scaffolded today; alternate sub-modules land when a measured need arises."
  type        = string
  default     = "container_apps"
  validation {
    condition     = contains(["container_apps"], var.compute_kind)
    error_message = "compute_kind must be one of: 'container_apps'."
  }
}

variable "state_store_kind" {
  description = "State-store seam. 'postgres_flex' today; 'cosmos' lands under modules/state-store/cosmos/ when a measured need arises."
  type        = string
  default     = "postgres_flex"
  validation {
    condition     = contains(["postgres_flex"], var.state_store_kind)
    error_message = "state_store_kind must be one of: 'postgres_flex'."
  }
}

variable "event_bus_kind" {
  description = "Event-bus seam. 'event_hubs_kafka' today; 'redpanda_aks' etc. land as sibling sub-modules."
  type        = string
  default     = "event_hubs_kafka"
  validation {
    condition     = contains(["event_hubs_kafka"], var.event_bus_kind)
    error_message = "event_bus_kind must be one of: 'event_hubs_kafka'."
  }
}


variable "enable_llm" {
  description = "Opt-in switch for the Azure OpenAI module (docs/roadmap/deployment/dev-and-deploy-parity.md § W-D). When false, no Cognitive Services account is created; the runtime binds the deterministic fake."
  type        = bool
  default     = false
}

variable "resolved_capabilities" {
  description = "Resolved LLM capabilities produced by the bootstrap resolver (fdai.rule_catalog.schema.llm_resolver_cli). Entries with status='hil-only' MUST be filtered out before being passed here."
  type = list(object({
    name           = string
    family         = string
    sku            = string
    capacity_tpm   = optional(number, 0)
    capacity_unit  = optional(string, "tpm")
    capacity_value = optional(number, 0)
  }))
  default = []

  validation {
    condition = alltrue([
      for capability in var.resolved_capabilities :
      contains(["tpm", "ptu"], capability.capacity_unit) &&
      (
        capability.capacity_unit == "tpm"
        ? capability.capacity_tpm >= 1000 && capability.capacity_value == 0
        : capability.capacity_tpm == 0 && capability.capacity_value >= 1
      )
    ])
    error_message = "resolved capabilities MUST use capacity_tpm for tpm or capacity_value for ptu, never both."
  }
}

variable "enable_model_apim_gateway" {
  description = "Attach an FDAI model API to an existing APIM service. False keeps the minimum-cost inventory unchanged."
  type        = bool
  default     = false
}

variable "model_apim_gateway" {
  description = "Existing APIM and same-family PTU/Standard backend configuration. Required only when enable_model_apim_gateway is true."
  type = object({
    resource_group_name = string
    api_management_name = string
    gateway_url         = string
    api_name            = string
    api_path            = string
    frontend_tenant_id  = string
    frontend_audience   = string
    api_version         = optional(string, "2024-10-21")
    apim_principal_id   = string
    ptu_backend = object({
      name        = string
      url         = string
      resource_id = string
    })
    standard_backend = object({
      name        = string
      url         = string
      resource_id = string
    })
  })
  default  = null
  nullable = true

  validation {
    condition     = !var.enable_model_apim_gateway || var.model_apim_gateway != null
    error_message = "enable_model_apim_gateway requires model_apim_gateway configuration."
  }
}

variable "python_task_author_capability" {
  description = "Name of a resolved Azure OpenAI capability used to generate editable PythonTask drafts. Empty disables model authoring."
  type        = string
  default     = ""
}

variable "vm_task_enabled" {
  description = "Bind the governed Azure VM task ToolExecutor in the headless core. Does not enable live execution."
  type        = bool
  default     = false
}

variable "vm_task_enforce" {
  description = "Permit promoted tool.run-python-on-vm actions to reach Managed Run Command after risk gate and Owner HIL."
  type        = bool
  default     = false
}

variable "vm_task_run_as_user" {
  description = "Non-root guest account prepared by modules/vm-task-host."
  type        = string
  default     = "fdai-task"
}

variable "vm_task_root" {
  description = "Private guest directory for content-addressed task and run files."
  type        = string
  default     = "/var/lib/fdai/tasks"
}

variable "scheduler_tick_cron_expression" {
  description = "Container Apps Job cadence that evaluates persistent schedules. Empty disables it unless vm_task_enabled is true."
  type        = string
  default     = ""
}

variable "measurement_scenario_set_version" {
  description = "Frozen P0 scenario-set version the automated baseline runner replays (e.g. 'v2026.07'). Bump this in lockstep with tests/scenarios/<version>/ contents so a promotion never compares metrics across versions."
  type        = string
  default     = "v2026.07"
}


variable "dr_drill_enabled" {
  description = "Toggle the scheduled DB-DR drill Container Apps Job. Upstream ships false so a generic deploy does not incur drill cost until the fork signs off on the runbook in docs/runbooks/db-dr-drill.md."
  type        = bool
  default     = false
}

variable "dr_drill_source_server_arm_id" {
  description = "ARM id of the production Postgres Flexible Server whose PITR checkpoint the drill restores. Required when dr_drill_enabled = true."
  type        = string
  default     = ""
}

variable "dr_drill_dry_run" {
  description = "When true, the drill CLI logs its composed config and exits without touching Azure. Upstream default is true so accidentally enabling the drill does not incur cost; the fork sets false in production."
  type        = bool
  default     = true
}


# ---------------------------------------------------------------------------
# Metric analyzer tick (opt-in) - drives the reference threshold analyzers
# out-of-band so metric-based scenarios (node_cpu_percent, http_429_rate,
# ...) get near-real-time detection. Latency envelope is bounded below by
# the metric backend: AKS Managed Prometheus scrapes on ~15 s; Azure
# Monitor Logs KQL has a 2-5 min ingestion floor. A 60 s cron is the
# safe default when enabled - it never runs faster than either backend
# can serve. See docs/roadmap/rules-and-detection/observability-and-detection.md.
# ---------------------------------------------------------------------------

variable "analyzer_tick_cron_expression" {
  description = "Cron for the analyzer tick Container Apps Job. Empty string (default) disables the job entirely so a generic deploy does not incur tick cost. Fork sets e.g. '* * * * *' (every minute) once analyzer_targets_json is filled."
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Azure inventory reconciliation. Runs on the VNet-integrated Container Apps
# environment under a dedicated read-only managed identity.
# ---------------------------------------------------------------------------

variable "inventory_cron_expression" {
  description = "Cron for full Azure inventory reconciliation. Empty disables the job."
  type        = string
  default     = "0 */6 * * *"
}

variable "enable_realtime_inventory_discovery" {
  description = "Enable managed-identity Event Grid delivery of subscription resource writes and deletes to Huginn's raw inventory topic."
  type        = bool
  default     = true
}

variable "inventory_sources" {
  description = "Ordered inventory source fallback list. Supported values: arg,arm."
  type        = string
  default     = "arg,arm"
}

variable "inventory_freshness_seconds" {
  description = "Maximum active inventory age before graph-dependent decisions degrade to HIL."
  type        = number
  default     = 86400

  validation {
    condition     = var.inventory_freshness_seconds >= 1
    error_message = "inventory_freshness_seconds must be >= 1."
  }
}

variable "analyzer_targets_json" {
  description = "JSON array of {resource_id, kind} pairs the analyzer tick investigates each fire. Empty (default) - the CLI logs a no-targets info line and exits 0, so a mis-provisioned cron stays quiet. Kind MUST match one of KIND_AKS / KIND_MYSQL / KIND_AZURE_OPENAI / KIND_APP_GATEWAY / KIND_API_MANAGEMENT (see src/fdai/core/investigation/analyzers.py)."
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
  description = "Base URL of a Prometheus-compatible query API (AKS Managed Prometheus data-collection endpoint, self-hosted Prom, Thanos, Cortex, Mimir). When non-empty, wire_azure_container binds PrometheusMetricProvider as the primary route for its supported metrics with Azure Monitor Logs as the fallback for non-AKS metrics (RoutedMetricProvider composite). Empty (default) keeps AML-only (or Noop) binding."
  type        = string
  default     = ""
}

variable "prometheus_audience" {
  description = "OIDC audience for the Prometheus bearer token. AKS Managed Prometheus with AAD requires 'https://prometheus.monitor.azure.com'. Empty -> unauthenticated Prom (self-hosted / behind network policy)."
  type        = string
  default     = ""
}


# ---------------------------------------------------------------------------
# Private networking (policy-locked tenants).
# ---------------------------------------------------------------------------
variable "enable_private_networking" {
  description = "When true, provision a VNet + a Key Vault private endpoint + private DNS and bind the Container App Environment to a delegated subnet, and lock the Key Vault to private access. Required on any tenant that enforces 'Key Vault public network access disabled'. When false (day-zero default) the deploy stays fully public. See docs/roadmap/deployment/deploy-and-onboard.md (private-networking layer). NOTE: with this enabled, `terraform apply` MUST run from a host with VNet line-of-sight to the KV private endpoint (a CI runner or jumpbox inside the VNet); the operator laptop cannot write secrets to a private-only vault."
  type        = bool
  default     = false
}

variable "enable_private_postgres" {
  description = "When true, place PostgreSQL Flexible Server on the delegated VNet subnet, use private DNS, disable public access, and remove the AllowAllAzureServices firewall rule. Requires enable_private_networking. Existing environments opt in explicitly because changing this setting replaces the server."
  type        = bool
  default     = false
}

# ---------------------------------------------------------------------------
# Ops/hub VNet peering (private-networking deploys via the bootstrap runner).
# Supplied from `infra/bootstrap` outputs (ops_vnet_id / ops_vnet_name /
# ops_resource_group_name). When set with enable_private_networking, the app
# spoke VNet peers to the ops hub both ways and links its private DNS zones to
# the ops VNet so the runner resolves the app's private endpoints.
# ---------------------------------------------------------------------------
variable "runner_vnet_id" {
  description = "Ops/hub VNet resource id (from infra/bootstrap output ops_vnet_id). Empty disables peering + DNS linking."
  type        = string
  default     = ""
}

variable "runner_vnet_name" {
  description = "Ops/hub VNet name (from infra/bootstrap output ops_vnet_name). Needed to create the hub->spoke peering on the ops VNet."
  type        = string
  default     = ""
}

variable "ops_resource_group_name" {
  description = "Ops/hub resource group name (from infra/bootstrap output ops_resource_group_name). Holds the ops VNet the hub->spoke peering attaches to."
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Monitoring (opt-in). When enabled, provision an action group + metric alerts
# + diagnostic settings for the control-plane resources. Alerts are a human
# signal only - they never take an autonomous action.
# ---------------------------------------------------------------------------
variable "enable_monitoring" {
  description = "Provision the monitoring module (action group + metric alerts + diagnostic settings). Default false so a day-zero deploy stays alert-free until an alert destination is configured."
  type        = bool
  default     = false
}

variable "alert_email" {
  description = "Email that receives Azure Monitor alerts (used when enable_monitoring = true). Empty = no email receiver."
  type        = string
  default     = ""
}

variable "alert_webhook_url" {
  description = "Webhook (Teams/Slack/PagerDuty ingest) for Azure Monitor alerts. Empty = none. Never commit a populated value; supply via tfvars/CI secret."
  type        = string
  default     = ""
  sensitive   = true
}

variable "enable_chatops_hil" {
  description = "Enable signed ChatOps delivery for runtime HIL approvals."
  type        = bool
  default     = false
}

variable "chatops_webhook_url" {
  description = "Teams-compatible HIL webhook URL. Supply through CI secret; never commit a value."
  type        = string
  default     = ""
  sensitive   = true
}

variable "chatops_webhook_secret" {
  description = "HMAC secret shared by HIL card delivery and the decision callback."
  type        = string
  default     = ""
  sensitive   = true
}

variable "enable_stewardship_governance" {
  description = "Enable automatic handover draft PR creation and signed GitHub merge audit on the ingestion gateway."
  type        = bool
  default     = false
}

variable "gitops_owner" {
  description = "GitHub owner for stewardship governance draft PRs."
  type        = string
  default     = ""
}

variable "gitops_repo" {
  description = "GitHub repository for stewardship governance draft PRs."
  type        = string
  default     = ""
}

variable "gitops_token" {
  description = "GitHub App installation token or equivalent short-lived token for governance PR delivery."
  type        = string
  default     = ""
  sensitive   = true
}

variable "github_webhook_secret" {
  description = "HMAC secret for the GitHub stewardship merge webhook."
  type        = string
  default     = ""
  sensitive   = true
}

variable "enable_email_notifications" {
  description = "Provision Azure Communication Services Email and bind the send-only A2/A4 notification channels."
  type        = bool
  default     = false
}

variable "notification_email_recipients" {
  description = "Email recipients for A2 operational alerts and A4 digests. Supply through CI variables; never commit populated addresses."
  type        = list(string)
  default     = []

  validation {
    condition = (
      !var.enable_email_notifications ||
      (length(var.notification_email_recipients) > 0 && alltrue([
        for address in var.notification_email_recipients : can(regex("^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$", address))
      ]))
    )
    error_message = "enable_email_notifications requires at least one syntactically valid notification_email_recipients entry."
  }
}

variable "email_data_location" {
  description = "ACS Email data-at-rest geography. This is independent from the Azure resource region."
  type        = string
  default     = "Korea"
}

variable "import_existing_email_notifications" {
  description = "Import a pre-existing ACS Email stack into Terraform state. Use only for the first convergence plan after an approved out-of-band bootstrap."
  type        = bool
  default     = false
}

# ---------------------------------------------------------------------------
# Operator console (layer 3) - Azure Static Web App hosting the read-only SPA.
# Default false so a day-zero deploy stays headless; a fork/operator opts in.
# ---------------------------------------------------------------------------
variable "enable_console" {
  description = "Provision the operator console module (Azure Static Web App hosting console/dist/). Default false so the day-zero deploy stays headless (control plane only)."
  type        = bool
  default     = false
}

variable "console_region" {
  description = "Region for the console Static Web App. Azure Static Web Apps is NOT available in every region (e.g. koreacentral is unsupported), so this is decoupled from var.region and defaults to the nearest supported region."
  type        = string
  default     = "eastasia"

  validation {
    condition     = contains(["westus2", "centralus", "eastus2", "westeurope", "eastasia"], var.console_region)
    error_message = "console_region must be an Azure Static Web Apps region: westus2, centralus, eastus2, westeurope, eastasia."
  }
}

# ---------------------------------------------------------------------------
# Operator console read API (layer 3 backend) - Azure Container App serving
# `fdai.delivery.read_api.prod:app`. Default off so the day-zero deploy stays
# headless. Tenant-specific Entra/RBAC ids are supplied via CI Variables.
# ---------------------------------------------------------------------------
variable "enable_read_api" {
  description = "Provision the console read-API Container App + migration job. Default false so the day-zero deploy stays headless."
  type        = bool
  default     = false
}

variable "read_api_image" {
  description = "Container image for the read API (the fdai runtime image built with the `serve` extra, e.g. `<acr>/fdai:dev`). Empty falls back to core_image, which is only valid if that image carries uvicorn + alembic."
  type        = string
  default     = ""
}

variable "read_api_resolved_models_path" {
  description = "Container path to resolved-models.json for the Command Deck narrator. Empty disables narrator routes. Supplied via CI Variables; never committed with environment-specific values."
  type        = string
  default     = ""
}

variable "read_api_narrator_probe_interval_seconds" {
  description = "Periodic narrator model latency-probe interval in seconds."
  type        = number
  default     = 300

  validation {
    condition     = var.read_api_narrator_probe_interval_seconds >= 30
    error_message = "read_api_narrator_probe_interval_seconds MUST be >= 30."
  }
}

variable "read_api_web_search_enabled" {
  description = "Enable controlled Azure Responses web search for eligible chat turns."
  type        = bool
  default     = false
}

variable "read_api_web_search_allowed_domains" {
  description = "Exact public source hosts allowed for conversational web search."
  type        = list(string)
  default     = []

  validation {
    condition = (
      length(var.read_api_web_search_allowed_domains) <= 100 &&
      alltrue([
        for domain in var.read_api_web_search_allowed_domains :
        can(regex("^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$", domain))
      ])
    )
    error_message = "read_api_web_search_allowed_domains MUST contain at most 100 host names without schemes or paths."
  }
}

variable "read_api_web_search_max_results" {
  description = "Maximum citations retained from one conversational web search."
  type        = number
  default     = 3

  validation {
    condition     = var.read_api_web_search_max_results >= 1 && var.read_api_web_search_max_results <= 10
    error_message = "read_api_web_search_max_results MUST be in [1, 10]."
  }
}

variable "read_api_web_search_budget_ms" {
  description = "Per-search Azure Responses timeout in milliseconds."
  type        = number
  default     = 15000

  validation {
    condition     = var.read_api_web_search_budget_ms >= 1
    error_message = "read_api_web_search_budget_ms MUST be >= 1."
  }
}

variable "read_api_web_search_probe_interval_seconds" {
  description = "Periodic web-search candidate model probe interval in seconds."
  type        = number
  default     = 300

  validation {
    condition     = var.read_api_web_search_probe_interval_seconds >= 30
    error_message = "read_api_web_search_probe_interval_seconds MUST be >= 30."
  }
}

variable "read_api_audience" {
  description = "Expected JWT aud claim (FDAI_API_AUDIENCE), commonly the API application client id for v2 tokens. Do not use the OAuth scope string. Supplied via CI Variables; never committed."
  type        = string
  default     = ""
}

variable "rbac_readers_group_id" {
  description = "Entra security group id mapped to Reader (FDAI_RBAC_READERS_GROUP_ID). Via CI Variables."
  type        = string
  default     = ""
}

variable "rbac_contributors_group_id" {
  description = "Entra security group id mapped to Contributor. Via CI Variables."
  type        = string
  default     = ""
}

variable "rbac_approvers_group_id" {
  description = "Entra security group id mapped to Approver. Via CI Variables."
  type        = string
  default     = ""
}

variable "rbac_owners_group_id" {
  description = "Entra security group id mapped to Owner. Via CI Variables."
  type        = string
  default     = ""
}

variable "rbac_break_glass_group_id" {
  description = "Entra security group id mapped to break-glass. Via CI Variables."
  type        = string
  default     = ""
}

variable "read_api_cors_allow_origins" {
  description = "Comma-separated allowed origins for the console SPA (e.g. the Static Web App origin). MUST NOT contain `*` outside dev."
  type        = string
  default     = ""
}

variable "read_api_iam_directory_provider" {
  description = "Human identity directory adapter for IAM user search. Empty disables search; set entra only after Graph User.Read.All admin consent for the read API managed identity."
  type        = string
  default     = ""

  validation {
    condition     = contains(["", "entra"], var.read_api_iam_directory_provider)
    error_message = "read_api_iam_directory_provider MUST be empty or entra."
  }
}

variable "stewardship_maintainers" {
  description = "Comma-separated FDAI maintainer Entra user object ids. Supplied through deployment configuration and exposed as FDAI_MAINTAINERS."
  type        = string
  default     = ""
}

variable "stewardship_agent_bindings" {
  description = "Agent name to comma-separated user:<oid> or group:<oid> stewardship bindings. Supplied through deployment configuration and exposed as FDAI_STEWARD_<AGENT>."
  type        = map(string)
  default     = {}

  validation {
    condition = alltrue([
      for agent, binding in var.stewardship_agent_bindings :
      contains(["Odin", "Thor", "Forseti", "Huginn", "Heimdall", "Vidar", "Var", "Bragi", "Saga", "Mimir", "Muninn", "Norns", "Njord", "Freyr", "Loki"], agent) && trimspace(binding) != ""
    ])
    error_message = "stewardship_agent_bindings keys MUST be pantheon agent names and values MUST be non-empty."
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

# ---------------------------------------------------------------------------
# Governed document ingestion - production gateway + ADLS Gen2 HNS.
# ---------------------------------------------------------------------------
variable "enable_document_ingestion" {
  description = "Provision the production ingestion gateway, ClamAV sidecar, ADLS Gen2 HNS storage, private endpoints, and dedicated Managed Identity."
  type        = bool
  default     = false
}

variable "ingestion_image" {
  description = "FDAI runtime image containing the serve extra. Empty falls back to core_image."
  type        = string
  default     = ""
}

variable "clamav_image" {
  description = "ClamAV sidecar image. Pin by digest for production."
  type        = string
  default     = "clamav/clamav:stable"
}

variable "ingestion_cors_allow_origins" {
  description = "Comma-separated exact console origins allowed to call the ingestion gateway."
  type        = string
  default     = ""
}

variable "ingestion_embedding_capability" {
  description = "Resolved Azure OpenAI embedding capability used for document indexing."
  type        = string
  default     = "t1.embedding"
}

variable "document_storage_replication_type" {
  description = "ADLS Gen2 standard replication type."
  type        = string
  default     = "ZRS"
}

variable "document_soft_delete_retention_days" {
  type    = number
  default = 30
}

variable "document_quarantine_retention_days" {
  type    = number
  default = 30
}

variable "document_derived_cool_after_days" {
  type    = number
  default = 30
}

variable "document_max_file_size_bytes" {
  type    = number
  default = 26214400
}

variable "document_max_batch_count" {
  type    = number
  default = 10
}

variable "document_chunk_max_chars" {
  type    = number
  default = 1200
}

variable "document_chunk_overlap" {
  type    = number
  default = 150
}

variable "document_indexing_stage_timeout_seconds" {
  description = "Deadline in seconds for each artifact, index, and ready-consumer operation."
  type        = number
  default     = 90

  validation {
    condition     = var.document_indexing_stage_timeout_seconds > 0
    error_message = "document_indexing_stage_timeout_seconds must be positive."
  }
}

variable "document_policy_version" {
  type    = string
  default = "prod-policy-v1"
}

variable "document_collections" {
  description = "Comma-separated governed collection ids accepted by the ingestion gateway."
  type        = string
  default     = "shared-knowledge"
}

variable "ingestion_min_replicas" {
  type    = number
  default = 1
}

variable "ingestion_max_replicas" {
  type    = number
  default = 1

  validation {
    condition     = var.ingestion_max_replicas == 1
    error_message = "ingestion_max_replicas MUST remain 1 until distributed upload claiming is implemented."
  }
}

# ---------------------------------------------------------------------------
# Hardening knobs (root-exposed; default to the day-zero/dev posture so the
# live env is unchanged, tighten for staging/prod via tfvars). See the
# production-hardening checklist in docs/roadmap/deployment/deploy-and-onboard.md.
# ---------------------------------------------------------------------------
variable "kv_purge_protection_enabled" {
  description = "Key Vault purge protection. IRREVERSIBLE once true; prod should set it, dev leaves false so a tear-down does not wait out the purge window."
  type        = bool
  default     = false
}

variable "kv_soft_delete_retention_days" {
  description = "Key Vault soft-delete retention (7-90). Raise for prod."
  type        = number
  default     = 7
}

variable "postgres_backup_retention_days" {
  description = "Postgres Flexible backup retention (7-35). Raise for prod."
  type        = number
  default     = 7
}

variable "postgres_geo_redundant_backup" {
  description = "Postgres geo-redundant (paired-region) backup. Adds cost; prod default true once RTO/RPO is signed off."
  type        = bool
  default     = false
}

variable "postgres_high_availability_mode" {
  description = "PostgreSQL Flexible HA mode. Production requires ZoneRedundant."
  type        = string
  default     = "Disabled"

  validation {
    condition     = contains(["Disabled", "SameZone", "ZoneRedundant"], var.postgres_high_availability_mode)
    error_message = "postgres_high_availability_mode must be Disabled, SameZone, or ZoneRedundant."
  }
}

variable "acr_sku" {
  description = "Container Registry SKU (Basic | Standard | Premium). Premium unlocks private endpoints + geo-replication for prod."
  type        = string
  default     = "Basic"
  validation {
    condition     = contains(["Basic", "Standard", "Premium"], var.acr_sku)
    error_message = "acr_sku must be one of: Basic, Standard, Premium."
  }
}

variable "enable_resource_locks" {
  description = "Place a CanNotDelete management lock on the resource group so an accidental delete is blocked. Default false (dev tear-down stays easy); set true for staging/prod."
  type        = bool
  default     = false
}

variable "monthly_budget_amount" {
  description = "Monthly cost budget for the resource group (in the billing currency). 0 disables the budget. Alerts fire at 90% actual + 100% forecast to budget_alert_emails."
  type        = number
  default     = 0
}

variable "budget_alert_emails" {
  description = "Email addresses that receive cost-budget alerts. Empty disables notifications even when a budget amount is set."
  type        = list(string)
  default     = []
}

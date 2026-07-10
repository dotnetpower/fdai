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
    Container image reference for the core control-plane app. The default
    `mcr.microsoft.com/azure-cli:latest` is a **placeholder** used so
    `terraform apply` succeeds without a pre-built image; that image's
    ENTRYPOINT is `az`, so the deployed replica will exit immediately
    and Container Apps will restart-loop until a fork overrides this
    value with an image built from the repo Dockerfile
    (ENTRYPOINT `python -m fdai`). Pin by digest for production; a tag
    is acceptable for dev only.
  EOT
  type        = string
  default     = "mcr.microsoft.com/azure-cli:latest"
}

variable "max_replicas" {
  description = "Container App max replica count (KEDA scale ceiling). Day-zero default is 3."
  type        = number
  default     = 3
}

variable "log_retention_days" {
  description = "Log Analytics retention in days. UI-configurable post-deploy; 30 is the day-zero default."
  type        = number
  default     = 30
}

variable "additional_tags" {
  description = "Fork-supplied tags merged on top of the base tag set."
  type        = map(string)
  default     = {}
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
  description = "Opt-in switch for the Azure OpenAI module (docs/roadmap/dev-and-deploy-parity.md § W-D). When false, no Cognitive Services account is created; the runtime binds the deterministic fake."
  type        = bool
  default     = false
}

variable "resolved_capabilities" {
  description = "Resolved LLM capabilities produced by the bootstrap resolver (fdai.rule_catalog.schema.llm_resolver_cli). Entries with status='hil-only' MUST be filtered out before being passed here."
  type = list(object({
    name         = string
    family       = string
    sku          = string
    capacity_tpm = number
  }))
  default = []
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
# Private networking (policy-locked tenants).
# ---------------------------------------------------------------------------
variable "enable_private_networking" {
  description = "When true, provision a VNet + a Key Vault private endpoint + private DNS and bind the Container App Environment to a delegated subnet, and lock the Key Vault to private access. Required on any tenant that enforces 'Key Vault public network access disabled'. When false (day-zero default) the deploy stays fully public. See docs/roadmap/deploy-and-onboard.md (private-networking layer). NOTE: with this enabled, `terraform apply` MUST run from a host with VNet line-of-sight to the KV private endpoint (a CI runner or jumpbox inside the VNet); the operator laptop cannot write secrets to a private-only vault."
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

# ---------------------------------------------------------------------------
# Hardening knobs (root-exposed; default to the day-zero/dev posture so the
# live env is unchanged, tighten for staging/prod via tfvars). See the
# production-hardening checklist in docs/roadmap/deploy-and-onboard.md.
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


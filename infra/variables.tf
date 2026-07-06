# -----------------------------------------------------------------------
# Workload identity + naming
# -----------------------------------------------------------------------

variable "workload" {
  description = "Workload token used in every resource name. Fixed to 'aiopspilot' by generic-scope.instructions.md; no customer identifier."
  type        = string
  default     = "aiopspilot"
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
}

variable "postgres_admin_password" {
  description = "Postgres Flexible Server administrator password. Supplied via tfvars only."
  type        = string
  sensitive   = true
}

# -----------------------------------------------------------------------
# Compute image reference
# -----------------------------------------------------------------------

variable "core_image" {
  description = "Container image reference for the core control-plane app. Pin by digest for production; a tag is acceptable for dev only."
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
  description = "Resolved LLM capabilities produced by the bootstrap resolver (aiopspilot.rule_catalog.schema.llm_resolver_cli). Entries with status='hil-only' MUST be filtered out before being passed here."
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


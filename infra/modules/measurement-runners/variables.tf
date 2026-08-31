variable "baseline_enabled" {
  description = "Create the automated baseline regression Job."
  type        = bool
  default     = false
}

variable "growth_enabled" {
  description = "Create the T1 pattern-growth intake Job."
  type        = bool
  default     = false
}

variable "baseline_job_name" {
  description = "Container Apps Job name for the automated baseline regression runner (CAF: caj-<workload>[-env][-region]-measure-baseline)."
  type        = string
}

variable "growth_job_name" {
  description = "Container Apps Job name for the T1 pattern-growth intake runner (CAF: caj-<workload>[-env][-region]-measure-growth)."
  type        = string
}

variable "operational_promotion_job_name" {
  description = "Container Apps Job name for immutable operational-promotion measurement."
  type        = string
}

variable "baseline_cron_expression" {
  description = "Cron for the baseline regression job. Daily at 02:00 UTC - off-peak and one hour before the 03:00 UTC rule watcher."
  type        = string
  default     = "0 2 * * *"
}

variable "growth_cron_expression" {
  description = "Cron for the pattern-growth intake job. Every 15 minutes; each invocation drains the audit outcome stream and exits (scale-to-zero when idle)."
  type        = string
  default     = "*/15 * * * *"
}

variable "operational_promotion_enabled" {
  description = "Create the operational-promotion measurement Job. Evidence must already exist in the pinned image or a protected mount."
  type        = bool
  default     = false
}

variable "operational_promotion_cron_expression" {
  description = "Cron for operational-promotion measurement. Daily after baseline measurement by default."
  type        = string
  default     = "30 2 * * *"
}

variable "operational_promotion_fdai_revision" {
  description = "Full immutable FDAI source revision bound to every operational-promotion batch."
  type        = string
  default     = ""

  validation {
    condition     = var.operational_promotion_fdai_revision == "" || can(regex("^(?:[0-9a-f]{40}|[0-9a-f]{64})$", var.operational_promotion_fdai_revision))
    error_message = "operational_promotion_fdai_revision must be empty or a full lowercase immutable revision."
  }
}

variable "operational_promotion_evidence_root" {
  description = "Absolute container path containing reviewed digest-only operational-promotion evidence."
  type        = string
  default     = ""
}

variable "operational_promotion_manifest" {
  description = "Manifest path relative to operational_promotion_evidence_root."
  type        = string
  default     = ""
}

variable "container_app_environment_id" {
  description = "Container Apps environment resource id (shared with the core app + rule watcher)."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "resource_group_name" {
  description = "Enclosing resource group."
  type        = string
}

variable "measurement_identity_id" {
  description = "Dedicated non-executor user-assigned Managed Identity resource id used by measurement jobs."
  type        = string
}

variable "image" {
  description = "Container image reference. Pin by digest in prod."
  type        = string
}

variable "acr_login_server" {
  description = "Private ACR login server. Empty keeps anonymous public image pulls."
  type        = string
  default     = ""
}

variable "scenario_set_version" {
  description = "Frozen P0 scenario-set version the baseline runner replays (e.g. v2026.07)."
  type        = string
}

variable "state_store_dsn_secret_id" {
  description = "Key Vault secret resource id containing the shared Postgres DSN."
  type        = string
  sensitive   = true
}

variable "environment" {
  description = "Non-secret runtime env vars shared by both measurement jobs."
  type        = map(string)
  default     = {}
}


variable "tags" {
  description = "Tags."
  type        = map(string)
  default     = {}
}

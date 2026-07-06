variable "baseline_job_name" {
  description = "Container Apps Job name for the automated baseline regression runner (CAF: caj-<workload>[-env][-region]-measure-baseline)."
  type        = string
}

variable "growth_job_name" {
  description = "Container Apps Job name for the T1 pattern-growth intake runner (CAF: caj-<workload>[-env][-region]-measure-growth)."
  type        = string
}

variable "baseline_cron_expression" {
  description = "Cron for the baseline regression job. Daily at 02:00 UTC — off-peak and one hour before the 03:00 UTC rule watcher."
  type        = string
  default     = "0 2 * * *"
}

variable "growth_cron_expression" {
  description = "Cron for the pattern-growth intake job. Every 15 minutes; each invocation drains the audit outcome stream and exits (scale-to-zero when idle)."
  type        = string
  default     = "*/15 * * * *"
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

variable "executor_identity_id" {
  description = "User-assigned MI resource id used by both jobs (same identity as the core app + rule watcher)."
  type        = string
}

variable "image" {
  description = "Container image reference. Pin by digest in prod."
  type        = string
}

variable "scenario_set_version" {
  description = "Frozen P0 scenario-set version the baseline runner replays (e.g. v2026.07)."
  type        = string
}

variable "tags" {
  description = "Tags."
  type        = map(string)
  default     = {}
}

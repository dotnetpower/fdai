variable "env_name" {
  description = "Container Apps environment name (CAF: cae-<workload>[-env][-region])."
  type        = string
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

variable "image" {
  description = "Container image reference. Pin by digest in prod."
  type        = string
}

variable "max_replicas" {
  description = "KEDA scale ceiling."
  type        = number
  default     = 3
}

variable "tags" {
  description = "Tags."
  type        = map(string)
  default     = {}
}


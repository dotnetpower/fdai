variable "environment" {
  description = "Deployment environment. The alert-noise pilot is restricted to dev."
  type        = string

  validation {
    condition     = var.environment == "dev"
    error_message = "alert-noise pilot is restricted to dev."
  }
}

variable "phase" {
  description = "Exact single-axis threshold phase: baseline is inert, treatment is expected to fire."
  type        = string
  default     = "baseline"

  validation {
    condition     = contains(["baseline", "treatment"], var.phase)
    error_message = "alert-noise pilot phase must be baseline or treatment."
  }
}

variable "resource_group_name" {
  type = string
}

variable "target_resource_id" {
  description = "Existing Key Vault resource id observed by the pilot metric alert."
  type        = string

  validation {
    condition = can(regex(
      "(?i)^/subscriptions/[0-9a-f-]{36}/resourceGroups/[^/]+/providers/Microsoft\\.KeyVault/vaults/[^/]+$",
      var.target_resource_id,
    ))
    error_message = "target_resource_id must be one existing Azure Key Vault resource id."
  }
}

variable "action_group_name" {
  type = string
}

variable "action_group_short_name" {
  type = string

  validation {
    condition     = 1 <= length(var.action_group_short_name) && length(var.action_group_short_name) <= 12
    error_message = "action_group_short_name must contain 1 to 12 characters."
  }
}

variable "alert_name" {
  type = string
}

variable "receiver_email" {
  description = "Dedicated approved dev test recipient. Supply only through protected configuration."
  type        = string
  sensitive   = true

  validation {
    condition     = trimspace(var.receiver_email) != ""
    error_message = "receiver_email must name the approved dedicated dev test recipient."
  }
}

variable "tags" {
  type    = map(string)
  default = {}
}

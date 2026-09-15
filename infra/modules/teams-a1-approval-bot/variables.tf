# A1 approval bot provisioning inputs. The group-connected Teams team and channel
# cannot be created by the azurerm provider, so team_id, channel_id, and the
# Operator activity endpoint are supplied by a person and passed through to the
# teams_approval_destination contract output.

variable "name" {
  description = "Base name for the dedicated A1 approval bot and its identity."
  type        = string

  validation {
    condition     = length(var.name) > 0 && length(var.name) <= 60
    error_message = "name must be a non-empty string of at most 60 characters."
  }
}

variable "resource_group_name" {
  description = "Resource group that owns the approval bot identity."
  type        = string
}

variable "location" {
  description = "Azure location for the dedicated approval bot identity."
  type        = string
}

variable "tenant_id" {
  description = "Entra tenant id that trusts the approval bot's user-assigned identity."
  type        = string

  validation {
    condition     = length(var.tenant_id) > 0
    error_message = "tenant_id must be a non-empty Entra tenant id."
  }
}

variable "activity_url" {
  description = "HTTPS Operator ingress that receives Teams approval activities (/hil/teams-activity)."
  type        = string

  validation {
    condition     = startswith(var.activity_url, "https://")
    error_message = "activity_url must be an https URL."
  }
}

variable "approval_team_id" {
  description = "Human-supplied group-connected Teams team id for approval delivery."
  type        = string

  validation {
    condition     = length(var.approval_team_id) > 0
    error_message = "approval_team_id must be a non-empty Teams team id."
  }
}

variable "approval_channel_id" {
  description = "Human-supplied Teams channel id inside the approval team."
  type        = string

  validation {
    condition     = length(var.approval_channel_id) > 0
    error_message = "approval_channel_id must be a non-empty Teams channel id."
  }
}

variable "tags" {
  description = "Tags applied to the approval bot identity."
  type        = map(string)
  default     = {}
}

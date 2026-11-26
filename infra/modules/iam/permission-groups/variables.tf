variable "role_definition_scope" {
  description = "Azure scope where the three FDAI custom roles are defined (defaults to subscription ID; optional management group ID for multi-subscription setups)."
  type        = string

  validation {
    condition     = can(regex("^(?i)(/subscriptions/[^/]+|/providers/Microsoft\\.Management/managementGroups/[^/]+)$", var.role_definition_scope))
    error_message = "role_definition_scope must be a subscription or management group ARM scope."
  }
}

variable "assignable_scopes" {
  description = "Scopes where the three FDAI custom roles may be assigned. Defaults to [var.role_definition_scope]."
  type        = list(string)
  default     = []
}

variable "name_suffix" {
  description = "Optional deterministic suffix appended to role names to avoid tenant collisions across independent installations."
  type        = string
  default     = ""
}

variable "catalog_path" {
  description = "Path to the canonical JSON catalog of FDAI Azure IAM permission groups."
  type        = string
  default     = ""
}

variable "environment" {
  description = "Target deployment environment (dev, staging, production). FDAI Contributor is refused for default production workloads."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "production"], lower(var.environment))
    error_message = "environment must be dev, staging, or production."
  }
}

variable "binding_mode" {
  description = "Principal binding mode: direct (default, zero Entra group setup) or entra_group (opt-in enterprise security groups)."
  type        = string
  default     = "direct"

  validation {
    condition     = contains(["direct", "entra_group"], var.binding_mode)
    error_message = "binding_mode must be direct or entra_group."
  }
}

variable "assignments" {
  description = "Role assignments mapping logical keys to group_id (reader, operator, contributor), scope, principal_id, and optional principal_type."
  type = map(object({
    group_id       = string
    scope          = string
    principal_id   = string
    principal_type = optional(string)
  }))
  default = {}

  validation {
    condition = alltrue([
      for a in values(var.assignments) :
      contains(["reader", "operator", "contributor"], a.group_id)
    ])
    error_message = "Every assignment group_id must be reader, operator, or contributor."
  }

  validation {
    condition = alltrue([
      for a in values(var.assignments) :
      a.group_id == "reader" || can(regex("(?i)^/subscriptions/[^/]+/resourceGroups/[^/]+", a.scope))
    ])
    error_message = "operator and contributor groups must be scoped to a resource group (never subscription-wide)."
  }

  validation {
    condition = alltrue([
      for a in values(var.assignments) :
      !(lower(var.environment) == "production" && a.group_id == "contributor")
    ])
    error_message = "FDAI Contributor is limited to dedicated dev/test/sandbox resource groups and cannot be assigned in default production."
  }
}

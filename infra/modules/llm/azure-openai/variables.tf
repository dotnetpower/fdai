variable "name" {
  description = "Cognitive Services account name (Azure OpenAI). CAF prefix `oai-` recommended."
  type        = string
}

variable "location" {
  description = "Azure region for the Cognitive Services account."
  type        = string
}

variable "resource_group_name" {
  description = "Target resource group."
  type        = string
}

variable "sku_name" {
  description = "Cognitive Services SKU. Standard is the day-zero default."
  type        = string
  default     = "S0"
}

variable "public_network_access_enabled" {
  description = "Allow the Azure OpenAI public endpoint. Defaults to false; callers that enable it should retain a deny-by-default network ACL with explicit trusted-source rules."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Resource tags."
  type        = map(string)
  default     = {}
}

variable "executor_principal_id" {
  description = <<-EOT
    Object id of the executor Managed Identity that will invoke the deployments.
    When ``grant_executor_role`` is true, the module role-assigns `Cognitive
    Services OpenAI User` on the account so runtime calls succeed without
    extra plane-shifts.
  EOT
  type        = string
  default     = null
}

variable "grant_executor_role" {
  description = "Explicit bool guarding the role assignment - kept out of `count` conditions on unknown-at-plan-time values."
  type        = bool
  default     = true
}

variable "additional_user_principal_ids" {
  description = "Additional principals keyed by stable role name. Values may be unknown until apply."
  type        = map(string)
  default     = {}
}

variable "resolved_capabilities" {
  description = <<-EOT
    Capability deployments to create. Fed from the resolver's
    resolved-models.json - one entry per resolved capability. Entries with
    status = "hil-only" MUST be excluded upstream (the module does not
    filter; keeping the boundary explicit).

    Every entry deploys as `azurerm_cognitive_deployment` under the account.
    Standard entries use `capacity_tpm` divided by 1000. Provisioned entries
    use `capacity_value` as the exact PTU count and MUST NOT populate TPM.
  EOT
  type = list(object({
    name           = string
    family         = string
    version        = string
    sku            = string
    capacity_tpm   = optional(number, 0)
    capacity_unit  = optional(string, "tpm")
    capacity_value = optional(number, 0)
  }))
  default = []

  validation {
    condition     = length(distinct([for c in var.resolved_capabilities : c.name])) == length(var.resolved_capabilities)
    error_message = "resolved_capabilities MUST have unique names."
  }


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
    error_message = "resolved capabilities MUST declare exactly one TPM or PTU capacity value."
  }

  validation {
    condition = alltrue([
      for capability in var.resolved_capabilities :
      length(trimspace(capability.version)) > 0
    ])
    error_message = "resolved capabilities MUST pin a non-empty model version."
  }
}

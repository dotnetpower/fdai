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
  description = "Explicit bool guarding the role assignment — kept out of `count` conditions on unknown-at-plan-time values."
  type        = bool
  default     = true
}

variable "resolved_capabilities" {
  description = <<-EOT
    Capability deployments to create. Fed from the resolver's
    resolved-models.json — one entry per resolved capability. Entries with
    status = "hil-only" MUST be excluded upstream (the module does not
    filter; keeping the boundary explicit).

    Every entry deploys as `azurerm_cognitive_deployment` under the account.
    The Terraform-side capacity is the resolver's `capacity_tpm` divided by
    1000 (Azure counts capacity in units of 1k TPM), rounded down.
  EOT
  type = list(object({
    name         = string
    family       = string
    sku          = string
    capacity_tpm = number
  }))
  default = []

  validation {
    condition     = length(distinct([for c in var.resolved_capabilities : c.name])) == length(var.resolved_capabilities)
    error_message = "resolved_capabilities MUST have unique names."
  }
}

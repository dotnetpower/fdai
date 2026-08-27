variable "account_name" {
  description = "CAF-compatible AI Services account name."
  type        = string
}

variable "project_name" {
  description = "Deployment-owned Foundry project name."
  type        = string
}

variable "location" {
  description = "Azure region for the Foundry account, project, and deployments."
  type        = string
}

variable "resource_group_name" {
  description = "Target FDAI application resource group."
  type        = string
}

variable "deployments" {
  description = "Publisher-qualified partner capability deployments."
  type = list(object({
    name         = string
    publisher    = string
    family       = string
    version      = string
    sku          = string
    capacity_tpm = number
  }))

  validation {
    condition = alltrue([
      for deployment in var.deployments :
      contains(["Anthropic", "MistralAI"], deployment.publisher) &&
      length(trimspace(deployment.name)) > 0 &&
      length(trimspace(deployment.family)) > 0 &&
      length(trimspace(deployment.version)) > 0 &&
      deployment.capacity_tpm >= 1000
    ])
    error_message = "Partner deployments MUST use an allowlisted publisher, pinned identity, and at least 1000 TPM."
  }

  validation {
    condition     = length(distinct([for deployment in var.deployments : deployment.name])) == length(var.deployments)
    error_message = "Partner deployment names MUST be unique."
  }
}

variable "user_principal_ids" {
  description = "Principals allowed to invoke the Foundry project, keyed by stable role."
  type        = map(string)
  default     = {}
}

variable "tags" {
  description = "FDAI ownership and cost-attribution tags."
  type        = map(string)
  default     = {}
}

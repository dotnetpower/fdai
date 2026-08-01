variable "account_name" {
  description = "CAF-compatible AI Services account name."
  type        = string
}

variable "project_name" {
  description = "Deployment-owned Foundry project name."
  type        = string
}

variable "location" {
  description = "Azure region for the Foundry account, project, and model deployment."
  type        = string
}

variable "resource_group_name" {
  description = "Target FDAI application resource group."
  type        = string
}

variable "private_networking_enabled" {
  description = "Disable public access when the deployment provides a private endpoint."
  type        = bool
}

variable "model_deployment_name" {
  description = "Resolved t1.web_search deployment name."
  type        = string
}

variable "model_family" {
  description = "Resolved OpenAI family used by the Foundry prompt agent."
  type        = string
}

variable "model_sku" {
  description = "Resolved Standard-compatible deployment SKU."
  type        = string
}

variable "model_capacity_tpm" {
  description = "Resolved model capacity in TPM."
  type        = number

  validation {
    condition     = var.model_capacity_tpm >= 1000
    error_message = "model_capacity_tpm MUST be >= 1000."
  }
}

variable "user_principal_ids" {
  description = "Principals allowed to reconcile or invoke the project agent, keyed by stable role."
  type        = map(string)
}

variable "tags" {
  description = "FDAI ownership and cost-attribution tags."
  type        = map(string)
  default     = {}
}

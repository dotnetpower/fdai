variable "account_name" {
  description = "CAF-compatible Azure AI Document Intelligence account name."
  type        = string
}

variable "location" {
  description = "Azure region for the Document Intelligence account."
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

variable "log_analytics_workspace_id" {
  description = "Log Analytics workspace that receives Document Intelligence metrics."
  type        = string
}

variable "tags" {
  description = "FDAI ownership and cost-attribution tags."
  type        = map(string)
  default     = {}
}

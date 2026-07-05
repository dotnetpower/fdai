variable "name" {
  description = "Key Vault name (CAF: kv-<workload>[-env][-region])."
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

variable "tenant_id" {
  description = "Entra tenant id."
  type        = string
}

variable "executor_principal_id" {
  description = "OID of the executor MI. Granted 'Key Vault Secrets User'."
  type        = string
  default     = null
}

variable "grant_executor_role" {
  description = <<-EOT
    Whether to grant the executor MI 'Key Vault Secrets User' at plan time.
    Kept as an explicit bool so `count` never depends on a resource attribute
    that is unknown-until-apply (the classic Terraform two-stage apply pain).
    Default true — matches the root wiring that always provisions the MI.
  EOT
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags."
  type        = map(string)
  default     = {}
}


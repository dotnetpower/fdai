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
    Default true - matches the root wiring that always provisions the MI.
  EOT
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags."
  type        = map(string)
  default     = {}
}

# ---------------------------------------------------------------------------
# Network posture + retention knobs. Defaults keep the day-zero deploy
# runnable from any location while giving a fork a one-line toggle to
# harden every setting for prod.
# ---------------------------------------------------------------------------
variable "public_network_access_enabled" {
  description = "When false, KV rejects every plane call from a public IP even if it hits an allowed bypass. Container Apps KV refs still resolve because Azure-managed traffic uses a Microsoft backbone route."
  type        = bool
  default     = true
}

variable "network_acls_default_action" {
  description = "'Allow' opens KV to all public IPs; 'Deny' restricts to `bypass = AzureServices` + explicit `ip_rules`. Day-zero default is Allow to keep the CI apply reachable."
  type        = string
  default     = "Allow"

  validation {
    condition     = contains(["Allow", "Deny"], var.network_acls_default_action)
    error_message = "network_acls_default_action must be 'Allow' or 'Deny'."
  }
}

variable "network_acls_ip_rules" {
  description = "Explicit IP allowlist evaluated when `network_acls_default_action = Deny`. Empty list is safe on Allow default."
  type        = list(string)
  default     = []
}

variable "network_acls_subnet_ids" {
  description = "Explicit VNet subnet allowlist. Populate once the Container Apps env has a delegated subnet."
  type        = list(string)
  default     = []
}

variable "purge_protection_enabled" {
  description = "Keep false when Terraform must purge a destroyed vault and immediately reuse its name."
  type        = bool
  default     = false
}

variable "soft_delete_retention_days" {
  description = "Days a deleted vault or object remains recoverable before purge. FDAI uses the Azure minimum of 7."
  type        = number
  default     = 7

  validation {
    condition     = var.soft_delete_retention_days >= 7 && var.soft_delete_retention_days <= 90
    error_message = "soft_delete_retention_days must be between 7 and 90."
  }
}

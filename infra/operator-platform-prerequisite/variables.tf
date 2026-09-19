variable "subscription_id" {
  description = "Exact existing platform subscription."
  type        = string
}

variable "tenant_id" {
  description = "Exact existing platform tenant."
  type        = string
}

variable "key_vault_id" {
  description = "Existing platform-owned Key Vault resource id."
  type        = string
}

variable "operator_principal_id" {
  description = "Existing Operator workload identity principal id."
  type        = string
}

variable "tags" {
  description = "Existing platform tag set."
  type        = map(string)
}

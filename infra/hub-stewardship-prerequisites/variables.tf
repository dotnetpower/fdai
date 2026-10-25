variable "location" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "acr_name" {
  type = string
}

variable "key_vault_name" {
  type = string
}

variable "state_store_dsn_secret_name" {
  type    = string
  default = "fdai-state-store-dsn"
}

variable "eventhub_namespace_name" {
  type = string
}

variable "log_analytics_workspace_name" {
  type = string
}

variable "vnet_name" {
  type = string
}

variable "private_endpoint_subnet_name" {
  type    = string
  default = "snet-pe"
}

variable "ops_resource_group_name" {
  type = string
}

variable "ops_vnet_name" {
  type = string
}

variable "aks_name" {
  type = string
}

variable "namespace" {
  type    = string
  default = "fdai-runtime"
}

variable "name_suffix" {
  type = string

  validation {
    condition     = can(regex("^[a-z0-9]{6}$", var.name_suffix))
    error_message = "name_suffix MUST be exactly six lowercase alphanumeric characters."
  }
}

variable "document_storage_name" {
  type = string

  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.document_storage_name))
    error_message = "document_storage_name MUST be a valid Storage account name."
  }
}

variable "deployer_principal_id" {
  type = string
}

variable "email_data_location" {
  type    = string
  default = "Korea"
}

variable "tags" {
  type    = map(string)
  default = {}
}

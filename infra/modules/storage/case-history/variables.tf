variable "name" {
  description = "Globally unique StorageV2 account name for case-history artifacts."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.name))
    error_message = "name MUST contain 3-24 lowercase alphanumeric characters."
  }
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "deployer_principal_id" {
  description = "Object id of the VNet-integrated Terraform runner identity."
  type        = string
}

variable "runtime_principal_id" {
  description = "Object id of the FDAI runtime managed identity."
  type        = string
}

variable "replication_type" {
  type    = string
  default = "ZRS"

  validation {
    condition     = contains(["LRS", "ZRS", "GRS", "GZRS", "RAGRS", "RAGZRS"], var.replication_type)
    error_message = "replication_type MUST be a supported standard Storage replication type."
  }
}

variable "public_network_access_enabled" {
  type    = bool
  default = false
}

variable "private_link_access" {
  description = "Private-link resource and tenant pairs allowed through storage network rules."
  type = map(object({
    endpoint_resource_id = string
    endpoint_tenant_id   = string
  }))
  default = {}
}

variable "container_name" {
  type    = string
  default = "case-history"

  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$", var.container_name))
    error_message = "container_name MUST be a valid lowercase Blob container name."
  }
}

variable "soft_delete_retention_days" {
  type    = number
  default = 30

  validation {
    condition     = var.soft_delete_retention_days >= 7 && var.soft_delete_retention_days <= 365
    error_message = "soft_delete_retention_days MUST be in [7, 365]."
  }
}

variable "version_retention_days" {
  type    = number
  default = 90

  validation {
    condition     = var.version_retention_days >= var.soft_delete_retention_days
    error_message = "version_retention_days MUST be >= soft_delete_retention_days."
  }
}

variable "tags" {
  type    = map(string)
  default = {}
}

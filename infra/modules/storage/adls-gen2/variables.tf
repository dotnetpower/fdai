variable "name" {
  description = "Globally unique ADLS Gen2 StorageV2 account name."
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

variable "infrastructure_encryption_enabled" {
  type    = bool
  default = true
}

variable "source_file_system" {
  type    = string
  default = "documents"
}

variable "derived_file_system" {
  type    = string
  default = "derived"
}

variable "soft_delete_retention_days" {
  type    = number
  default = 30

  validation {
    condition     = var.soft_delete_retention_days >= 7 && var.soft_delete_retention_days <= 365
    error_message = "soft_delete_retention_days MUST be in [7, 365]."
  }
}

variable "container_delete_retention_days" {
  type    = number
  default = 30

  validation {
    condition     = var.container_delete_retention_days >= 7 && var.container_delete_retention_days <= 365
    error_message = "container_delete_retention_days MUST be in [7, 365]."
  }
}

variable "quarantine_retention_days" {
  type    = number
  default = 30

  validation {
    condition     = var.quarantine_retention_days >= 1
    error_message = "quarantine_retention_days MUST be positive."
  }
}

variable "derived_cool_after_days" {
  type    = number
  default = 30

  validation {
    condition     = var.derived_cool_after_days >= 1
    error_message = "derived_cool_after_days MUST be positive."
  }
}

variable "cors_allowed_origins" {
  type    = list(string)
  default = []
}

variable "tags" {
  type    = map(string)
  default = {}
}

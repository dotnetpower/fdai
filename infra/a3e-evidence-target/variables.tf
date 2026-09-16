variable "subscription_id" {
  description = "Azure subscription that owns the isolated evidence target."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a GUID."
  }
}

variable "resource_group_name" {
  description = "Existing protected holding resource group for the disposable target."
  type        = string

  validation {
    condition     = trimspace(var.resource_group_name) != ""
    error_message = "resource_group_name must be non-empty."
  }
}

variable "deploy_runner_principal_id" {
  description = "Object id of the authenticated principal permitted to prepare this target."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.deploy_runner_principal_id))
    error_message = "deploy_runner_principal_id must be a GUID."
  }
}

variable "environment" {
  description = "Environment token used in deterministic names and ownership tags."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z0-9-]{2,12}$", var.environment))
    error_message = "environment must contain 2-12 lowercase letters, digits, or hyphens."
  }
}

variable "region" {
  description = "Approved Azure region for the isolated evidence target."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]+$", var.region))
    error_message = "region must use the canonical lowercase Azure region token."
  }
}

variable "region_short" {
  description = "Short region token used in deterministic resource names."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{2,6}$", var.region_short))
    error_message = "region_short must contain 2-6 lowercase letters or digits."
  }
}

variable "expires_at_utc" {
  description = "RFC 3339 expiry recorded on every disposable resource."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", var.expires_at_utc))
    error_message = "expires_at_utc must use UTC RFC 3339 form."
  }
}

variable "vm_size" {
  description = "Exact subscription-available VM SKU selected by the reviewed plan."
  type        = string

  validation {
    condition     = can(regex("^Standard_[A-Za-z0-9_]{1,64}$", var.vm_size))
    error_message = "vm_size must be a valid Azure standard VM SKU token."
  }
}

variable "vm_image" {
  description = "Exact region-available Linux image selected by the reviewed plan."
  type = object({
    publisher = string
    offer     = string
    sku       = string
    version   = string
  })

  validation {
    condition = (
      trimspace(var.vm_image.publisher) != "" &&
      trimspace(var.vm_image.offer) != "" &&
      trimspace(var.vm_image.sku) != "" &&
      trimspace(var.vm_image.version) != "" &&
      lower(trimspace(var.vm_image.version)) != "latest"
    )
    error_message = "vm_image fields must be non-empty and version must be exact, not latest."
  }
}

variable "admin_ssh_public_key" {
  description = "SSH public key retained only in protected deployment input."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^ssh-(rsa|ed25519) ", trimspace(var.admin_ssh_public_key)))
    error_message = "admin_ssh_public_key must be an OpenSSH RSA or Ed25519 public key."
  }
}

variable "vnet_address_space" {
  description = "Non-overlapping address space for the isolated target network."
  type        = string
  default     = "10.74.0.0/24"

  validation {
    condition = (
      can(cidrhost(var.vnet_address_space, 0)) &&
      can(regex("/24$", var.vnet_address_space))
    )
    error_message = "vnet_address_space must be a valid /24 CIDR block."
  }
}

variable "additional_tags" {
  description = "Additional deployment-owned non-sensitive tags."
  type        = map(string)
  default     = {}
}

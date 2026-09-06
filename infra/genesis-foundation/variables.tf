variable "subscription_id" {
  description = "Explicit verified target subscription, shared by both root and bootstrap providers."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a UUID for the verified target."
  }
}

variable "tenant_id" {
  description = "Explicit verified target tenant, shared by both root and bootstrap providers."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "tenant_id must be a UUID for the verified target."
  }
}

variable "workload" {
  description = "Deployment-owned workload token used by the existing bootstrap CAF naming convention."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,11}$", var.workload))
    error_message = "workload must contain 2-12 lowercase letters or digits and start with a letter."
  }
}

variable "env" {
  description = "Deployment environment, independent of approval and runtime authority."
  type        = string
  nullable    = false

  validation {
    condition     = contains(["dev", "staging", "prod"], var.env)
    error_message = "env must be dev, staging, or prod."
  }
}

variable "region" {
  description = "Explicit Azure public-cloud region for foundation resources. Availability and quota are external prerequisites."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z][a-z0-9]+$", var.region))
    error_message = "region must be an Azure location token, not a display name."
  }
}

variable "region_short" {
  description = "Deployment-owned short region token used in CAF resource names."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,7}$", var.region_short))
    error_message = "region_short must contain 2-8 lowercase letters or digits and start with a letter."
  }
}

variable "state_storage_account_name" {
  description = "Globally unique state account name derived once by the installer and reused unchanged on resume. No random name is generated here."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.state_storage_account_name))
    error_message = "state_storage_account_name must contain 3-24 lowercase letters or digits."
  }
}

variable "state_retention_days" {
  description = "Blob and container soft-delete retention, configured through ARM only."
  type        = number
  default     = 30
  nullable    = false

  validation {
    condition     = var.state_retention_days >= 1 && var.state_retention_days <= 365 && floor(var.state_retention_days) == var.state_retention_days
    error_message = "state_retention_days must be an integer from 1 through 365."
  }
}

variable "ops_address_space" {
  description = "Explicit IPv4 hub CIDR. The installer must reject overlap with app, VPN, peer, and resolver ranges before approval."
  type        = string
  nullable    = false

  validation {
    condition     = can(cidrnetmask(var.ops_address_space))
    error_message = "ops_address_space must be an IPv4 CIDR."
  }
}

variable "runner_subnet_prefix" {
  description = "Explicit runner-subnet IPv4 CIDR inside the reviewed ops address space."
  type        = string
  nullable    = false

  validation {
    condition     = can(cidrnetmask(var.runner_subnet_prefix))
    error_message = "runner_subnet_prefix must be an IPv4 CIDR."
  }
}

variable "pe_subnet_prefix" {
  description = "Explicit private-endpoint-subnet IPv4 CIDR inside the reviewed ops address space."
  type        = string
  nullable    = false

  validation {
    condition     = can(cidrnetmask(var.pe_subnet_prefix))
    error_message = "pe_subnet_prefix must be an IPv4 CIDR."
  }
}

variable "enable_public_egress" {
  description = "Explicitly opt into bootstrap's outbound-only NAT path. False creates no public IP or replacement route; the deployment must provide an approved private management, identity, and artifact path."
  type        = bool
  default     = false
  nullable    = false
}

variable "runner_ssh_public_key" {
  description = "Public SSH key for the private runner. Never provide a private key, password, or registration token."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^ssh-(ed25519|rsa) [A-Za-z0-9+/]+={0,2}( [^\\r\\n]+)?$", trimspace(var.runner_ssh_public_key)))
    error_message = "runner_ssh_public_key must be a single OpenSSH RSA or Ed25519 public key."
  }
}

variable "runner_source_image_id" {
  description = "Exact prebuilt managed-image or numeric gallery image-version ARM ID. Image trust, availability, installed tools, and ephemeral ResourceDisk compatibility must be verified before approval; bootstrap rejects latest and unversioned galleries."
  type        = string
  nullable    = false
}

variable "runner_vm_size" {
  description = "Reviewed runner size with quota and enough local ResourceDisk capacity for the pinned image."
  type        = string
  default     = "Standard_D4ds_v5"
  nullable    = false
}

variable "source_commit" {
  description = "Exact verified source revision recorded on foundation resources; a reference, not an approval."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.source_commit))
    error_message = "source_commit must be a lowercase 40-character Git SHA."
  }
}

variable "run_digest" {
  description = "SHA-256 digest binding the provisioning run, recorded as provenance on every taggable foundation resource. It grants no authority."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.run_digest))
    error_message = "run_digest must be a lowercase SHA-256 digest."
  }
}

variable "foundation_context_digest" {
  description = "Explicit SHA-256 foundation context binding for the foundation-owned app resource group. Pass this unchanged to the platform's reference-only mode; it is not an approval or readiness claim."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.foundation_context_digest))
    error_message = "foundation_context_digest must be a lowercase SHA-256 digest."
  }
}

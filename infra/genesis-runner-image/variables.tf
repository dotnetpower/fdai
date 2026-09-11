variable "subscription_id" {
  description = "Explicit verified subscription for the pre-Foundation runner-image build."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a UUID for the verified target."
  }
}

variable "tenant_id" {
  description = "Explicit verified tenant for the pre-Foundation runner-image build."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "tenant_id must be a UUID for the verified target."
  }
}

variable "workload" {
  description = "Deployment-owned workload token used by the FDAI CAF naming convention."
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
  description = "Azure region in which the exact runner image is built and retained."
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

variable "source_commit" {
  description = "Exact required-CI-green source revision whose image recipe is being built."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.source_commit))
    error_message = "source_commit must be a lowercase 40-character Git SHA."
  }
}

variable "run_digest" {
  description = "SHA-256 binding for this image build; it grants no apply authority."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.run_digest))
    error_message = "run_digest must be a lowercase SHA-256 digest."
  }
}

variable "source_image_version" {
  description = "Exact Canonical Ubuntu 24.04 server Marketplace version. Mutable latest is prohibited."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]+(\\.[0-9]+)+$", var.source_image_version)) && lower(var.source_image_version) != "latest"
    error_message = "source_image_version must be an exact numeric Marketplace version, not latest."
  }
}

variable "azure_cli_version" {
  description = "Exact Azure CLI product version verified inside the image."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.azure_cli_version))
    error_message = "azure_cli_version must be an exact semantic version."
  }
}

variable "azure_cli_package_version" {
  description = "Exact packages.microsoft.com Azure CLI package version for Ubuntu 24.04."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+-[0-9]+~noble$", var.azure_cli_package_version))
    error_message = "azure_cli_package_version must be an exact Ubuntu noble package version."
  }
}

variable "microsoft_package_key_fingerprint" {
  description = "Expected uppercase fingerprint for the Microsoft package-signing key."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9A-F]{40}$", var.microsoft_package_key_fingerprint))
    error_message = "microsoft_package_key_fingerprint must be an uppercase 40-character fingerprint."
  }
}

variable "terraform_version" {
  description = "Exact Terraform version installed from its checksum-pinned official archive."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.terraform_version))
    error_message = "terraform_version must be an exact semantic version."
  }
}

variable "terraform_sha256" {
  description = "SHA-256 of the official linux_amd64 Terraform archive."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.terraform_sha256))
    error_message = "terraform_sha256 must be a lowercase SHA-256 digest."
  }
}

variable "terraform_binary_sha256" {
  description = "SHA-256 of the Terraform executable extracted from the authenticated archive."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.terraform_binary_sha256))
    error_message = "terraform_binary_sha256 must be a lowercase SHA-256 digest."
  }
}

variable "opa_version" {
  description = "Exact OPA version installed from its checksum-pinned static binary."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.opa_version))
    error_message = "opa_version must be an exact semantic version."
  }
}

variable "opa_sha256" {
  description = "SHA-256 of the official linux_amd64 static OPA binary."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.opa_sha256))
    error_message = "opa_sha256 must be a lowercase SHA-256 digest."
  }
}

variable "github_runner_version" {
  description = "Exact GitHub Actions runner version staged without registration material."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.github_runner_version))
    error_message = "github_runner_version must be an exact semantic version."
  }
}

variable "github_runner_sha256" {
  description = "SHA-256 of the exact official Linux x64 GitHub Actions runner archive."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.github_runner_sha256))
    error_message = "github_runner_sha256 must be a lowercase SHA-256 digest."
  }
}

variable "build_vm_size" {
  description = "Bounded private builder VM size used only while producing the managed image."
  type        = string
  default     = "Standard_D2ds_v5"
  nullable    = false

  validation {
    condition     = can(regex("^Standard_[A-Za-z0-9_]{1,64}$", var.build_vm_size))
    error_message = "build_vm_size must be a valid Azure standard VM SKU token."
  }
}

variable "verify_vm_size" {
  description = "Bounded private verifier VM size used to boot and inspect the captured image."
  type        = string
  default     = "Standard_B2s"
  nullable    = false

  validation {
    condition     = can(regex("^Standard_[A-Za-z0-9_]{1,64}$", var.verify_vm_size))
    error_message = "verify_vm_size must be a valid Azure standard VM SKU token."
  }
}

variable "build_admin_username" {
  description = "Non-secret local administrator name for the private builder and verifier VMs."
  type        = string
  default     = "fdairunner"
  nullable    = false

  validation {
    condition     = can(regex("^[a-z][a-z0-9_-]{2,31}$", var.build_admin_username))
    error_message = "build_admin_username must be a valid lowercase Linux account name."
  }
}

variable "runner_ssh_public_key" {
  description = "Public SSH key placed on private build VMs; no inbound public path is created."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^ssh-(ed25519|rsa) [A-Za-z0-9+/=]+(?: [^\\r\\n]+)?$", var.runner_ssh_public_key))
    error_message = "runner_ssh_public_key must be one OpenSSH public key line."
  }
}

variable "build_address_space" {
  description = "Private address space dedicated to the temporary runner-image build network."
  type        = string
  default     = "192.168.240.0/24"
  nullable    = false

  validation {
    condition     = can(cidrhost(var.build_address_space, 1)) && can(regex("^(10\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|192\\.168\\.)", var.build_address_space))
    error_message = "build_address_space must be a valid private IPv4 CIDR."
  }
}

variable "build_subnet_prefix" {
  description = "Private subnet used by the builder and verifier VMs."
  type        = string
  default     = "192.168.240.0/26"
  nullable    = false

  validation {
    condition     = can(cidrhost(var.build_subnet_prefix, 1)) && can(regex("^(10\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|192\\.168\\.)", var.build_subnet_prefix))
    error_message = "build_subnet_prefix must be a valid private IPv4 CIDR."
  }
}

variable "firewall_subnet_prefix" {
  description = "Dedicated Azure Firewall data subnet for allowlisted build egress."
  type        = string
  default     = "192.168.240.64/26"
  nullable    = false

  validation {
    condition     = can(cidrhost(var.firewall_subnet_prefix, 1)) && can(regex("^(10\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|192\\.168\\.)", var.firewall_subnet_prefix))
    error_message = "firewall_subnet_prefix must be a valid private IPv4 CIDR."
  }
}

variable "firewall_management_subnet_prefix" {
  description = "Dedicated Azure Firewall management subnet for the Basic SKU."
  type        = string
  default     = "192.168.240.128/26"
  nullable    = false

  validation {
    condition     = can(cidrhost(var.firewall_management_subnet_prefix, 1)) && can(regex("^(10\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|192\\.168\\.)", var.firewall_management_subnet_prefix))
    error_message = "firewall_management_subnet_prefix must be a valid private IPv4 CIDR."
  }
}

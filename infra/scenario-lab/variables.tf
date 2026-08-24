variable "environment" {
  description = "Scenario-lab environment token used in names and tags."
  type        = string
  default     = "lab"

  validation {
    condition     = can(regex("^[a-z0-9-]{2,12}$", var.environment))
    error_message = "environment must contain 2-12 lowercase letters, digits, or hyphens."
  }
}

variable "region" {
  description = "Azure region for the scenario lab."
  type        = string
}

variable "region_short" {
  description = "Short region token used in resource names."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{2,6}$", var.region_short))
    error_message = "region_short must contain 2-6 lowercase letters or digits."
  }
}

variable "expires_at_utc" {
  description = "RFC 3339 expiry recorded on every lab resource for cost and cleanup review."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", var.expires_at_utc))
    error_message = "expires_at_utc must use UTC RFC 3339 form, for example 2026-08-31T09:00:00Z."
  }
}

variable "runner_vnet" {
  description = "Existing VNet-integrated deploy runner network peered with the private lab."
  type = object({
    id                  = string
    name                = string
    resource_group_name = string
  })
}

variable "operator_access" {
  description = "Optional P2S VPN VNet and operator principal used for direct workstation testing. Null keeps runner-only access."
  type = object({
    principal_id             = string
    vnet_id                  = string
    vnet_name                = string
    vnet_resource_group_name = string
  })
  default  = null
  nullable = true

  validation {
    condition = var.operator_access == null || (
      trimspace(var.operator_access.principal_id) != "" &&
      startswith(var.operator_access.vnet_id, "/subscriptions/") &&
      trimspace(var.operator_access.vnet_name) != "" &&
      trimspace(var.operator_access.vnet_resource_group_name) != ""
    )
    error_message = "operator_access must provide a principal id and complete Azure VNet identity, or be null."
  }
}

variable "admin_ssh_public_key" {
  description = "SSH public key for the private Linux stress host."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^ssh-(rsa|ed25519) ", trimspace(var.admin_ssh_public_key)))
    error_message = "admin_ssh_public_key must be an OpenSSH RSA or Ed25519 public key."
  }
}

variable "vm_image_version" {
  description = "Exact region-available Ubuntu image version. Mutable 'latest' is not accepted."
  type        = string

  validation {
    condition     = trimspace(var.vm_image_version) != "" && lower(trimspace(var.vm_image_version)) != "latest"
    error_message = "vm_image_version must be a non-empty exact image version and cannot be latest."
  }
}

variable "aks_node_vm_size" {
  description = "VM size for the single AKS system node."
  type        = string
  default     = "Standard_D2s_v5"
}

variable "stress_vm_size" {
  description = "VM size for CPU and memory pressure scenarios."
  type        = string
  default     = "Standard_B2s"
}

variable "mysql_sku_name" {
  description = "Burstable MySQL Flexible Server SKU used by the credit-pressure scenario."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "mysql_version" {
  description = "MySQL Flexible Server engine version."
  type        = string
  default     = "8.0.21"
}

variable "mysql_admin_login" {
  description = "Scenario-lab MySQL administrator login. The password is generated in Terraform."
  type        = string
  default     = "fdailabadmin"
}

variable "azure_openai_model_family" {
  description = "Region-available Azure OpenAI model family used by the rate-limit scenario."
  type        = string
  default     = "gpt-4.1-nano"
}

variable "azure_openai_model_version" {
  description = "Exact Azure OpenAI model version used by the rate-limit scenario."
  type        = string
  default     = "2025-04-14"
}

variable "azure_openai_deployment_name" {
  description = "Azure OpenAI deployment name exposed to the scenario runner."
  type        = string
  default     = "sre-rate-limit"
}

variable "azure_openai_deployment_sku" {
  description = "Azure OpenAI deployment SKU."
  type        = string
  default     = "GlobalStandard"
}

variable "azure_openai_capacity_tpm" {
  description = "Azure OpenAI deployment throughput in tokens per minute."
  type        = number
  default     = 1000

  validation {
    condition     = var.azure_openai_capacity_tpm >= 1000 && var.azure_openai_capacity_tpm % 1000 == 0
    error_message = "azure_openai_capacity_tpm must be a positive multiple of 1000."
  }
}

variable "lab_address_space" {
  description = "Address space for the isolated scenario-lab VNet."
  type        = list(string)
  default     = ["10.42.0.0/20"]
}

variable "aks_subnet_prefix" {
  description = "AKS node subnet prefix."
  type        = string
  default     = "10.42.0.0/22"
}

variable "vm_subnet_prefix" {
  description = "Private stress-host subnet prefix."
  type        = string
  default     = "10.42.4.0/24"
}

variable "mysql_subnet_prefix" {
  description = "Delegated MySQL subnet prefix."
  type        = string
  default     = "10.42.5.0/24"
}

variable "private_endpoint_subnet_prefix" {
  description = "Private endpoint subnet prefix."
  type        = string
  default     = "10.42.6.0/24"
}

variable "additional_tags" {
  description = "Deployment-supplied generic tags merged with FDAI ownership tags."
  type        = map(string)
  default     = {}
}

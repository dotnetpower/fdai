variable "resource_group_name" {
  description = "Existing development resource group that owns the Console and gateway."
  type        = string
}

variable "gateway_location" {
  description = "Azure region for API Management."
  type        = string
}

variable "console_location" {
  description = "Azure Static Web Apps hosting region."
  type        = string
}

variable "workload" {
  description = "CAF workload token."
  type        = string
  default     = "fdai"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.workload))
    error_message = "workload must be a lowercase CAF token."
  }
}

variable "environment" {
  description = "Deployment environment. This root is development-only."
  type        = string
  default     = "dev"

  validation {
    condition     = var.environment == "dev"
    error_message = "The development Console/gateway root supports only environment=dev."
  }
}

variable "region_short" {
  description = "Reviewed short region token for API Management and ownership tags."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{2,12}$", var.region_short))
    error_message = "region_short must be a reviewed lowercase region token."
  }
}

variable "console_region_short" {
  description = "Reviewed short hosting-region token for Static Web Apps."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{2,12}$", var.console_region_short))
    error_message = "console_region_short must be a reviewed lowercase region token."
  }
}

variable "resource_name_suffix" {
  description = "Stable six-character suffix for globally scoped resource names."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{6}$", var.resource_name_suffix))
    error_message = "resource_name_suffix must be exactly six lowercase alphanumeric characters."
  }
}

variable "frontend_tenant_id" {
  description = "Microsoft Entra tenant whose access tokens the gateway accepts."
  type        = string
}

variable "frontend_audience" {
  description = "Operator API application client id expected in access tokens."
  type        = string
}

variable "operator_backend_url" {
  description = "HTTPS origin of the existing Operator API backend."
  type        = string

  validation {
    condition     = can(regex("^https?://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$", var.operator_backend_url))
    error_message = "operator_backend_url must be an HTTP(S) origin without path, query, fragment, or explicit port."
  }
}

variable "ingestion_backend_url" {
  description = "HTTPS origin of the existing document ingestion API backend."
  type        = string

  validation {
    condition     = can(regex("^https?://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$", var.ingestion_backend_url))
    error_message = "ingestion_backend_url must be an HTTP(S) origin without path, query, fragment, or explicit port."
  }
}

variable "backend_nsg_id" {
  description = "Exact AKS backend subnet NSG id. Required when either backend uses HTTP."
  type        = string
  default     = ""
}

variable "backend_nsg_destination_addresses" {
  description = "Exact Operator and ingestion LoadBalancer frontend addresses allowed from AzureCloud."
  type        = list(string)
  default     = []

  validation {
    condition = (
      var.backend_nsg_id == ""
      ? length(var.backend_nsg_destination_addresses) == 0
      : length(var.backend_nsg_destination_addresses) == 2
    )
    error_message = "An NSG binding requires exactly two backend frontend addresses; without one the address list must be empty."
  }
}

variable "publisher_name" {
  description = "Publisher name shown by API Management."
  type        = string
  default     = "FDAI"
}

variable "publisher_email" {
  description = "Publisher email shown by API Management."
  type        = string
  default     = "operator@example.com"
}

variable "console_custom_hostname" {
  description = "Optional custom Console hostname. Empty uses the Static Web App default hostname."
  type        = string
  default     = ""

  validation {
    condition = (
      var.console_custom_hostname == "" ||
      can(regex("^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])$", var.console_custom_hostname))
    )
    error_message = "console_custom_hostname must be empty or a hostname without scheme, path, query, fragment, or port."
  }
}

variable "tags" {
  description = "Additional customer-agnostic tags merged with the FDAI ownership tags."
  type        = map(string)
  default     = {}
}

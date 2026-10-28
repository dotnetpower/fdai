variable "enabled" {
  description = "Whether to provision the browser-facing API Management gateway."
  type        = bool
  default     = true
  nullable    = false
}

variable "name" {
  description = "API Management service name."
  type        = string

  validation {
    condition     = can(regex("^apim-[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])$", var.name)) && length(var.name) <= 50
    error_message = "name must be a valid APIM CAF name of at most 50 characters."
  }
}

variable "resource_group_name" {
  description = "Resource group that owns the API Management service."
  type        = string
}

variable "location" {
  description = "Azure region for the API Management service."
  type        = string
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

  validation {
    condition     = can(regex("^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$", var.publisher_email))
    error_message = "publisher_email must be a valid email address."
  }
}

variable "frontend_tenant_id" {
  description = "Microsoft Entra tenant whose access tokens the gateway accepts."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.frontend_tenant_id))
    error_message = "frontend_tenant_id must be a GUID."
  }
}

variable "frontend_audience" {
  description = "Microsoft Entra application client id expected in API access tokens."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.frontend_audience))
    error_message = "frontend_audience must be the API application client GUID, not an api:// App ID URI."
  }
}

variable "console_origin" {
  description = "Exact Static Web App HTTPS origin permitted by the gateway CORS policies."
  type        = string

  validation {
    condition     = can(regex("^https://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$", var.console_origin))
    error_message = "console_origin must be an HTTPS origin without a path, query, fragment, or explicit port."
  }
}

variable "operator_backend_url" {
  description = "Operator API backend origin. The backend independently validates Microsoft Entra JWTs and App Roles."
  type        = string

  validation {
    condition     = can(regex("^https?://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$", var.operator_backend_url))
    error_message = "operator_backend_url must be an HTTP or HTTPS origin without a path, query, fragment, or explicit port."
  }
}

variable "ingestion_backend_url" {
  description = "Document ingestion API backend origin. The backend independently validates Microsoft Entra JWTs and App Roles."
  type        = string

  validation {
    condition     = can(regex("^https?://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$", var.ingestion_backend_url))
    error_message = "ingestion_backend_url must be an HTTP or HTTPS origin without a path, query, fragment, or explicit port."
  }
}

variable "backend_nsg_id" {
  description = "Optional backend subnet NSG resource id. Required when either backend uses HTTP."
  type        = string
  default     = ""

  validation {
    condition = (
      var.backend_nsg_id == "" ||
      can(regex("^/subscriptions/[0-9a-fA-F-]+/resourceGroups/[^/]+/providers/Microsoft[.]Network/networkSecurityGroups/[^/]+$", var.backend_nsg_id))
    )
    error_message = "backend_nsg_id must be empty or an Azure network security group resource id."
  }
}

variable "backend_nsg_destination_addresses" {
  description = "Exact Operator and ingestion LoadBalancer frontend addresses admitted by the optional NSG rule."
  type        = list(string)
  default     = []

  validation {
    condition = (
      var.backend_nsg_id == "" ?
      length(var.backend_nsg_destination_addresses) == 0 :
      length(var.backend_nsg_destination_addresses) == 2
    )
    error_message = "backend_nsg_destination_addresses must be empty without an NSG or contain exactly two backend addresses with an NSG."
  }
}

variable "tags" {
  description = "Tags applied to API Management after Azure-safe key normalization."
  type        = map(string)
  default     = {}
}

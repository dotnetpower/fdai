variable "resource_group_name" {
  description = "Resource group containing the existing API Management instance."
  type        = string
}

variable "api_management_name" {
  description = "Existing API Management service name. This module does not create the service."
  type        = string
}

variable "gateway_url" {
  description = "HTTPS gateway origin, including a custom domain when configured."
  type        = string

  validation {
    condition     = can(regex("^https://[^/?#]+$", var.gateway_url))
    error_message = "gateway_url must be an HTTPS origin without path, query, or fragment."
  }
}

variable "api_name" {
  description = "Stable APIM API name for one FDAI model capability."
  type        = string
}

variable "api_path" {
  description = "APIM API path without a leading or trailing slash."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9/-]*[a-z0-9]$", var.api_path))
    error_message = "api_path must be lowercase kebab-case path segments without edge slashes."
  }
}

variable "frontend_tenant_id" {
  description = "Entra tenant whose tokens APIM accepts from FDAI callers."
  type        = string
}

variable "frontend_audience" {
  description = "Application ID URI expected in the FDAI caller token."
  type        = string
}

variable "api_version" {
  description = "Azure OpenAI data-plane API version applied at the gateway."
  type        = string
  default     = "2024-10-21"
}

variable "ptu_backend" {
  description = "Primary PTU backend. URL ends at /openai/deployments/<deployment>."
  type = object({
    name        = string
    url         = string
    resource_id = string
  })

  validation {
    condition     = can(regex("^https://[^?#]+$", var.ptu_backend.url))
    error_message = "ptu_backend.url must use HTTPS without a query or fragment."
  }
}

variable "standard_backend" {
  description = "Same-family Standard backend used only after a PTU HTTP 429."
  type = object({
    name        = string
    url         = string
    resource_id = string
  })

  validation {
    condition     = can(regex("^https://[^?#]+$", var.standard_backend.url))
    error_message = "standard_backend.url must use HTTPS without a query or fragment."
  }
}

variable "apim_principal_id" {
  description = "Object id of the existing APIM managed identity."
  type        = string
}

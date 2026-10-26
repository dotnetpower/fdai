variable "name" {
  description = "Static Web App resource name (CAF: stapp-<workload>[-env][-region])."
  type        = string

  validation {
    condition     = can(regex("^stapp-[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])$", var.name)) && length(var.name) <= 40
    error_message = "name must be a valid Static Web App CAF name of at most 40 characters."
  }
}

variable "location" {
  description = "Azure region. Static Web App tier availability varies by region; validate with `az staticwebapp list-secrets` before selecting."
  type        = string
}

variable "resource_group_name" {
  description = "Enclosing resource group."
  type        = string
}

variable "sku_tier" {
  description = "Static Web App SKU tier. Day-zero default is 'Free' (Free tier is sufficient for the read-only console)."
  type        = string
  default     = "Free"

  validation {
    condition     = contains(["Free", "Standard"], var.sku_tier)
    error_message = "sku_tier must be one of: 'Free', 'Standard'."
  }
}

variable "sku_size" {
  description = "SKU size. Must match sku_tier (Azure enforces this)."
  type        = string
  default     = "Free"

  validation {
    condition     = contains(["Free", "Standard"], var.sku_size)
    error_message = "sku_size must be one of: 'Free', 'Standard'."
  }
}

variable "custom_hostname" {
  description = "Optional custom domain hostname for the console (e.g. 'console.example.com'). Empty string disables the custom-domain resource entirely."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags merged onto the Static Web App resource."
  type        = map(string)
  default     = {}
}

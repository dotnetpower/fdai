variable "subscription_id" {
  description = "Exact development subscription for the isolated certification."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F-]{36}$", var.subscription_id))
    error_message = "subscription_id must be a GUID."
  }
}

variable "tenant_id" {
  description = "Exact Microsoft Entra tenant for the isolated certification."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F-]{36}$", var.tenant_id))
    error_message = "tenant_id must be a GUID."
  }
}

variable "location" {
  description = "Azure region used only by the disposable certification sandbox."
  type        = string
  default     = "westus2"
}

variable "resource_group_name" {
  description = "Existing development application resource group that hosts only the task-owned sandbox resources."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9._()-]{1,90}$", var.resource_group_name))
    error_message = "resource_group_name must be one valid existing Azure resource group name."
  }
}

variable "source_revision" {
  description = "Exact protected source revision embedded in the prebuilt Core image."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.source_revision))
    error_message = "source_revision must be a full lowercase commit SHA."
  }
}

variable "request_id" {
  description = "Stable content-addressed inventory network certification request."
  type        = string

  validation {
    condition     = can(regex("^inventory-network-[0-9a-f]{48}$", var.request_id))
    error_message = "request_id must use inventory-network- plus 48 lowercase hex characters."
  }
}

variable "core_image" {
  description = "Prebuilt exact-revision Core image imported into the selected ACR."
  type        = string

  validation {
    condition = can(regex(
      "^[a-z0-9.-]+\\.azurecr\\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$",
      var.core_image
    ))
    error_message = "core_image must be an immutable ACR digest reference."
  }
}

variable "acr_id" {
  description = "Existing development ACR resource ID used only for image pull."
  type        = string
}

variable "acr_login_server" {
  description = "Existing development ACR login server."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{5,50}\\.azurecr\\.io$", var.acr_login_server))
    error_message = "acr_login_server must be an Azure Container Registry host."
  }
}

variable "expires_at" {
  description = "RFC 3339 sandbox expiry retained as ownership metadata."
  type        = string
}

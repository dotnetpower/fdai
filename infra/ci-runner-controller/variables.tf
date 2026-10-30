variable "subscription_id" {
  type        = string
  description = "Explicit approved subscription, supplied outside source control."
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be an explicit subscription UUID."
  }
}

variable "location" {
  type        = string
  description = "Approved Azure region for both isolated CI environments."
  validation {
    condition     = can(regex("^[a-z][a-z0-9]+$", var.location))
    error_message = "location must be a nonempty Azure region name."
  }
}

variable "resource_group_name" {
  type        = string
  description = "New dedicated controller resource group, not an existing application group."
  validation {
    condition     = can(regex("^[A-Za-z0-9_()-][A-Za-z0-9_.()-]{0,88}[A-Za-z0-9_()-]$", var.resource_group_name))
    error_message = "resource_group_name must be a valid explicit resource group name."
  }
}

variable "worker_resource_group_name" {
  type        = string
  description = "New exclusive worker resource group; never reuse an application or controller group."
  validation {
    condition = (
      can(regex("^[A-Za-z0-9_()-][A-Za-z0-9_.()-]{0,88}[A-Za-z0-9_()-]$", var.worker_resource_group_name)) &&
      lower(var.worker_resource_group_name) != lower(var.resource_group_name)
    )
    error_message = "worker_resource_group_name must be valid and distinct from resource_group_name."
  }
}

variable "name" {
  type        = string
  description = "Deployment-specific CI name stem; all owned resource names derive from it."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,14}[a-z0-9]$", var.name))
    error_message = "name must be 3-17 lowercase letters, digits or hyphens, beginning with a letter."
  }
}

variable "registry_id" {
  type        = string
  description = "Existing registry ARM ID; this root never creates a registry."
  validation {
    condition = (
      can(regex("(?i)^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft.ContainerRegistry/registries/[^/]+$", var.registry_id)) &&
      startswith(lower(var.registry_id), "/subscriptions/${lower(var.subscription_id)}/")
    )
    error_message = "registry_id must identify an existing registry in the selected subscription."
  }
}

variable "registry_server" {
  type        = string
  description = "Existing registry login host without scheme or path; it must match registry_id."
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]+\\.azurecr\\.io$", var.registry_server))
    error_message = "registry_server must be an Azure registry login hostname."
  }
}

variable "controller_image" {
  type        = string
  description = "Complete immutable controller image reference in registry_server."
  validation {
    condition     = can(regex("^${replace(var.registry_server, ".", "\\.")}/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$", var.controller_image))
    error_message = "controller_image must be registry_server/repository@sha256:<64 lowercase hex digits>."
  }
}

variable "worker_image" {
  type        = string
  description = "Complete immutable broker-only worker image reference, shared by both Manual Jobs."
  validation {
    condition     = can(regex("^${replace(var.registry_server, ".", "\\.")}/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$", var.worker_image))
    error_message = "worker_image must be registry_server/repository@sha256:<64 lowercase hex digits>."
  }
}

variable "github_repository" {
  type        = string
  description = "Exact owner/repository controlled by the PAT-owning service."
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be owner/repository."
  }
}

variable "storage_account_name" {
  type        = string
  description = "Globally unique private controller state account name."
  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.storage_account_name))
    error_message = "storage_account_name must be 3-24 lowercase letters or digits."
  }
}

variable "storage_blob" {
  type        = string
  default     = "controller-state.json"
  description = "Lease/state blob name; no GitHub credentials or workspace data belong in it."
  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", var.storage_blob))
    error_message = "storage_blob must be a single nonempty blob name without a path."
  }
}

variable "controller_base_url" {
  type        = string
  default     = ""
  description = "Optional approved HTTPS origin. Empty selects https://CONTAINER_APP_HOSTNAME at runtime, avoiding a Terraform self-reference."
  validation {
    condition     = var.controller_base_url == "" || can(regex("^https://[a-z0-9][a-z0-9.-]+[a-z0-9]$", var.controller_base_url))
    error_message = "controller_base_url must be empty or an HTTPS origin without port, path, query or credentials."
  }
}

variable "vm_subnet_id" {
  type        = string
  default     = ""
  description = "Existing unpeered CI-only subnet with inbound deny, no application routes, and approved outbound access."
  validation {
    condition = (
      (var.vm_subnet_id == "" && var.vm_image_id == "") ||
      (
        can(regex("(?i)^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft.Network/virtualNetworks/[^/]+/subnets/[^/]+$", var.vm_subnet_id)) &&
        startswith(lower(var.vm_subnet_id), "/subscriptions/${lower(var.subscription_id)}/")
      )
    )
    error_message = "vm_subnet_id must identify an existing CI-only subnet in the selected subscription; empty is allowed only while vm_image_id is empty."
  }
}

variable "vm_image_id" {
  type        = string
  default     = ""
  description = "Exact pre-baked Trusted Launch Azure Compute Gallery version ARM ID. Empty explicitly disables Docker workers; managed images are unsupported."
  validation {
    condition = (
      var.vm_image_id == "" ||
      (
        can(regex("(?i)^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft.Compute/galleries/[^/]+/images/[^/]+/versions/[0-9]+\\.[0-9]+\\.[0-9]+$", var.vm_image_id)) &&
        startswith(lower(var.vm_image_id), "/subscriptions/${lower(var.subscription_id)}/")
      )
    )
    error_message = "vm_image_id must be empty or an exact gallery image version ARM ID in the selected subscription; managed images and latest are unsupported."
  }
}

variable "vm_size" {
  type        = string
  default     = "Standard_D4ds_v4"
  description = "Four-vCPU Docker worker size; the operator must verify quota/capacity before enabling up to 16 workers."
  validation {
    condition = contains([
      "Standard_D4ds_v4", "Standard_D4s_v5", "Standard_D4as_v5", "Standard_D4ads_v5"
    ], var.vm_size)
    error_message = "vm_size must be a supported four-vCPU SKU matching the pool CPU accounting."
  }
}

variable "ssh_public_key" {
  type        = string
  default     = ""
  description = "Operator public SSH key only. Never pass a private key or enable public VM ingress."
  validation {
    condition     = (var.ssh_public_key == "" && var.vm_image_id == "") || can(regex("^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/]+={0,3}( [^\\r\\n]+)?$", var.ssh_public_key))
    error_message = "ssh_public_key must be a single OpenSSH public key; empty is allowed only while vm_image_id is empty."
  }
}

variable "controller_apply" {
  type        = bool
  default     = false
  description = "Explicit dispatch activation after credentials, exclusivity, isolation and quota checks; defaults to shadow planning."
}

variable "replica_timeout_seconds" {
  type        = number
  default     = 86400
  description = "24-hour platform ceiling with one-hour idle rotation and at most six-hour CI jobs. This is not a drain timer."
  validation {
    condition     = var.replica_timeout_seconds == 86400
    error_message = "replica_timeout_seconds must remain 86400 so idle rotation preserves CI execution headroom."
  }
}

variable "additional_tags" {
  type    = map(string)
  default = {}
}

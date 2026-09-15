variable "kubeconfig_path" {
  description = "Private kubeconfig created by the managed deployment host."
  type        = string
}

variable "image" {
  description = "Digest-pinned pgvector PostgreSQL image imported into the deployment ACR."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$", var.image))
    error_message = "image must be an ACR reference pinned by sha256 digest."
  }
}

variable "key_vault_id" {
  description = "Existing deployment Key Vault resource id."
  type        = string
}

variable "runtime_principal_ids" {
  description = "Runtime identities granted read access to the published DSN."
  type        = set(string)
}

variable "namespace" {
  description = "Namespace dedicated to the compact non-production database."
  type        = string
  default     = "fdai-data"
}

variable "database_name" {
  description = "FDAI database name."
  type        = string
  default     = "fdai"
}

variable "admin_login" {
  description = "FDAI database bootstrap login."
  type        = string
  default     = "fdaiadmin"
}

variable "storage_size" {
  description = "Persistent volume request for compact PostgreSQL."
  type        = string
  default     = "100Gi"
}

variable "tags" {
  description = "Stable labels projected from deployment ownership tags."
  type        = map(string)
  default     = {}
}

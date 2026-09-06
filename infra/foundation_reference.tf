variable "foundation_resource_group_context_digest" {
  description = "For a new platform state only, reference the application group owned by genesis foundation instead of managing it twice. Existing ownership requires a separately reviewed state handoff."
  type        = string
  default     = null

  validation {
    condition = var.foundation_resource_group_context_digest == null ? true : can(
      regex("^[0-9a-f]{64}$", var.foundation_resource_group_context_digest)
    )
    error_message = "foundation_resource_group_context_digest must be null or a lowercase SHA-256."
  }
}

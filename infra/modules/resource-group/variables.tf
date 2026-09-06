variable "name" {
  description = "Resource group name (CAF: rg-<workload>[-env][-region][-instance])."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "tags" {
  description = "Base tag set applied to the RG."
  type        = map(string)
  default     = {}
}

variable "reference_existing" {
  description = "Reference a foundation-owned group instead of managing it. Select only when creating a new platform state."
  type        = bool
  default     = false
  nullable    = false
}

variable "foundation_context_digest" {
  description = "Approved foundation context stamped on the externally owned group; required only in reference mode."
  type        = string
  default     = null

  validation {
    condition = var.reference_existing ? can(
      regex("^[0-9a-f]{64}$", var.foundation_context_digest)
    ) : var.foundation_context_digest == null
    error_message = "Reference mode requires a lowercase SHA-256 foundation context; managed mode must omit it."
  }
}

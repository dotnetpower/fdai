variable "subscription_id" {
  type        = string
  description = "Explicitly approved Azure subscription. Supply outside source control."
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "name" {
  type        = string
  description = "Resource name stem for the elastic CI runner."
}

variable "registry_name" {
  type        = string
  description = "Globally unique container registry name (5-50 lowercase letters and digits)."

  validation {
    condition     = can(regex("^[a-z0-9]{5,50}$", var.registry_name))
    error_message = "registry_name must be 5-50 lowercase letters and digits."
  }
}

variable "github_repository" {
  type        = string
  description = "owner/repository whose queued jobs scale the runner."

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be owner/repository."
  }
}

variable "runner_image" {
  type        = string
  description = "Image in the registry, as repository:tag, built by build-image.sh."

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9_.-]{1,64}$", var.runner_image)) && !endswith(var.runner_image, ":latest")
    error_message = "runner_image must be repository:tag and must not use latest."
  }
}

variable "runner_labels" {
  type    = list(string)
  default = ["fdai-ci", "fdai-ci-aca"]
}

variable "job_cpu" {
  type    = number
  default = 4
}

variable "job_memory" {
  type    = string
  default = "8Gi"
}

variable "max_executions" {
  type        = number
  default     = 24
  description = "Upper bound on concurrent runner executions; the cost and quota ceiling."

  validation {
    condition     = var.max_executions >= 1 && var.max_executions <= 64
    error_message = "max_executions must be between 1 and 64."
  }
}

variable "replica_timeout_seconds" {
  type    = number
  default = 1800
}

variable "additional_tags" {
  type    = map(string)
  default = {}
}

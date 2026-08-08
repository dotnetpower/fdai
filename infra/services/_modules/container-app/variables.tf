variable "name" { type = string }
variable "platform" {
  type = object({
    resource_group_name          = string
    container_app_environment_id = string
    acr_login_server             = string
  })
}
variable "image" { type = string }
variable "identity_ids" { type = list(string) }
variable "registry_identity_id" { type = string }
variable "command" { type = list(string) }
variable "args" { type = list(string) }
variable "sidecars" {
  description = "Optional dependency containers sharing the service revision."
  type = list(object({
    name    = string
    image   = string
    cpu     = number
    memory  = string
    command = optional(list(string), [])
    args    = optional(list(string), [])
    startup_probe = optional(object({
      transport               = string
      port                    = number
      path                    = optional(string)
      interval_seconds        = optional(number, 5)
      timeout_seconds         = optional(number, 3)
      failure_count_threshold = optional(number, 30)
    }))
    liveness_probe = optional(object({
      transport               = string
      port                    = number
      path                    = optional(string)
      interval_seconds        = optional(number, 30)
      timeout_seconds         = optional(number, 3)
      failure_count_threshold = optional(number, 3)
    }))
    readiness_probe = optional(object({
      transport               = string
      port                    = number
      path                    = optional(string)
      interval_seconds        = optional(number, 10)
      timeout_seconds         = optional(number, 3)
      failure_count_threshold = optional(number, 3)
    }))
  }))
  default = []

  validation {
    condition     = length(distinct([for sidecar in var.sidecars : sidecar.name])) == length(var.sidecars)
    error_message = "Sidecar names must be unique within a Container App revision."
  }
}
variable "secrets" {
  type = list(object({
    name                = string
    identity            = string
    key_vault_secret_id = string
  }))
  sensitive = true
}
variable "environment" {
  type = list(object({
    name        = string
    value       = optional(string)
    secret_name = optional(string)
  }))

  validation {
    condition = alltrue([
      for item in var.environment : (item.value == null) != (item.secret_name == null)
    ])
    error_message = "Each environment entry must set exactly one of value or secret_name."
  }
}
variable "health" {
  type = object({
    port                    = number
    liveness_path           = optional(string)
    readiness_path          = string
    startup_path            = optional(string)
    interval_seconds        = optional(number, 30)
    timeout_seconds         = optional(number, 3)
    failure_count_threshold = optional(number, 3)
    startup_failure_count   = optional(number, 30)
  })
}
variable "ingress" {
  type = object({
    external_enabled = bool
    target_port      = number
    transport        = optional(string, "auto")
  })
  default = null
}
variable "scaling" {
  type = object({
    min_replicas = number
    max_replicas = number
    cpu          = number
    memory       = string
  })
}
variable "component" { type = string }
variable "rollback_strategy" { type = string }
variable "tags" { type = map(string) }

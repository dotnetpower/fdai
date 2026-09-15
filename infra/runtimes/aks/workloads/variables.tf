variable "kubeconfig_path" {
  description = "Private kubeconfig created by the managed deployment host."
  type        = string
}

variable "namespace" {
  description = "Namespace dedicated to FDAI workloads."
  type        = string
  default     = "fdai-runtime"
}

variable "tenant_id" {
  description = "Microsoft Entra tenant used for workload identity."
  type        = string
}

variable "oidc_issuer_url" {
  description = "AKS OIDC issuer used by federated identity credentials."
  type        = string
}

variable "key_vault_name" {
  description = "Key Vault name used by the managed CSI provider."
  type        = string
}

variable "workloads" {
  description = "Runtime-neutral FDAI service specifications."
  type = map(object({
    component            = string
    image                = string
    identity_resource_id = string
    identity_client_id   = string
    additional_identities = optional(map(object({
      resource_id = string
      client_id   = string
    })), {})
    command            = list(string)
    args               = optional(list(string), [])
    replicas           = number
    max_replicas       = number
    cpu                = string
    memory             = string
    port               = number
    external           = optional(bool, false)
    readiness_path     = string
    liveness_path      = string
    environment        = map(string)
    secret_environment = optional(map(string), {})
  }))

  validation {
    condition = alltrue([
      for workload in values(var.workloads) :
      workload.replicas >= 1 && workload.max_replicas >= workload.replicas &&
      can(regex("^[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$", workload.image)) &&
      workload.port >= 1
    ])
    error_message = "Every workload requires a digest-pinned image, valid scaling bounds, and a valid port."
  }
}

variable "scheduled_jobs" {
  description = "Runtime-neutral scheduled job specifications."
  type = map(object({
    component            = string
    image                = string
    identity_resource_id = string
    identity_client_id   = string
    command              = list(string)
    args                 = optional(list(string), [])
    schedule             = string
    deadline_seconds     = number
    retry_limit          = number
    cpu                  = string
    memory               = string
    environment          = map(string)
    secret_environment   = optional(map(string), {})
  }))
  default = {}
}

variable "tags" {
  description = "Stable labels projected from deployment ownership tags."
  type        = map(string)
  default     = {}
}

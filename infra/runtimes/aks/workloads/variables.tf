variable "kubeconfig_path" {
  description = "Private kubeconfig created by the managed deployment host."
  type        = string
}

variable "namespace" {
  description = "Namespace dedicated to FDAI workloads."
  type        = string
  default     = "fdai-runtime"
}

variable "executor_external_scale_targets" {
  description = "Explicit existing namespaces and exact Deployment names eligible for Thor-owned scale-only RBAC. Empty by default; requires separate plan approval and revocation."
  type        = map(set(string))
  default     = {}
  nullable    = false

  validation {
    condition = length(var.executor_external_scale_targets) <= 16 && alltrue([
      for namespace, names in var.executor_external_scale_targets :
      can(regex("^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$", namespace)) &&
      namespace != var.namespace && namespace != "default" && !startswith(namespace, "kube-") &&
      length(names) >= 1 && length(names) <= 16 && alltrue([
        for name in names : can(regex("^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$", name))
      ])
    ])
    error_message = "External scale targets require up to 16 non-system, non-runtime namespaces with 1 to 16 exact DNS-label Deployment names each."
  }
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
    sidecars = optional(map(object({
      image   = string
      command = optional(list(string), [])
      args    = optional(list(string), [])
      cpu     = string
      memory  = string
      port    = number
      writable_paths = optional(map(object({
        mount_path = string
        size_limit = string
      })), {})
    })), {})
  }))

  validation {
    condition = alltrue([
      for workload in values(var.workloads) :
      workload.replicas >= 1 && workload.max_replicas >= workload.replicas &&
      can(regex("^[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$", workload.image)) &&
      workload.port >= 1 && alltrue([
        for sidecar_name, sidecar in workload.sidecars :
        can(regex("^[a-z][a-z0-9-]{0,62}$", sidecar_name)) &&
        can(regex("^[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$", sidecar.image)) &&
        sidecar.port >= 1 && sidecar.port <= 65535
      ])
    ])
    error_message = "Every workload and sidecar requires a digest-pinned image, valid scaling bounds, and a valid port."
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

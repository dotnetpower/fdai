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

variable "browser_gateway" {
  description = "Optional APIM Consumption gateway for browser-facing AKS services."
  type = object({
    enabled              = optional(bool, true)
    resource_group_name  = string
    location             = string
    workload             = string
    environment          = string
    region_short         = string
    resource_name_suffix = string
    backend_nsg_id       = optional(string, "")
    publisher_name       = optional(string, "FDAI")
    publisher_email      = optional(string, "operator@example.com")
  })
  default  = null
  nullable = true

  validation {
    condition = var.browser_gateway == null ? true : (
      can(regex("^[a-z][a-z0-9-]{1,30}$", var.browser_gateway.workload)) &&
      can(regex("^[a-z][a-z0-9-]{1,15}$", var.browser_gateway.environment)) &&
      can(regex("^[a-z0-9]{2,12}$", var.browser_gateway.region_short)) &&
      can(regex("^[a-z0-9]{6}$", var.browser_gateway.resource_name_suffix)) &&
      can(regex("^[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?$", var.browser_gateway.resource_group_name)) &&
      can(regex("^[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?$", var.browser_gateway.location)) &&
      can(regex("^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$", var.browser_gateway.publisher_email)) &&
      length("apim-${var.browser_gateway.workload}-${var.browser_gateway.environment}-${var.browser_gateway.region_short}-${var.browser_gateway.resource_name_suffix}") <= 50 &&
      (
        var.browser_gateway.backend_nsg_id == "" ||
        can(regex("^/subscriptions/[0-9a-fA-F-]+/resourceGroups/[^/]+/providers/Microsoft[.]Network/networkSecurityGroups/[^/]+$", var.browser_gateway.backend_nsg_id))
      )
    )
    error_message = "browser_gateway requires portable CAF naming tokens, a publisher email, and an optional Azure NSG resource ID."
  }

  validation {
    condition = var.browser_gateway == null ? true : (
      !var.browser_gateway.enabled ? true : try(
        var.workloads["operator-service"].external &&
        var.workloads["document-ingestion-api"].external &&
        coalesce(var.workloads["operator-service"].service_port, var.workloads["operator-service"].port) == 80 &&
        coalesce(var.workloads["document-ingestion-api"].service_port, var.workloads["document-ingestion-api"].port) == 80,
        false,
      )
    )
    error_message = "browser_gateway requires external operator-service and document-ingestion-api workloads on Service port 80."
  }
}

variable "workloads" {
  description = "Runtime-neutral FDAI service specifications."
  type = map(object({
    component            = string
    source_commit        = string
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
    service_port       = optional(number)
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
      can(regex("^[0-9a-f]{40}$", workload.source_commit)) &&
      can(regex("^[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$", workload.image)) &&
      workload.port >= 1 && workload.port <= 65535 &&
      coalesce(workload.service_port, workload.port) >= 1 &&
      coalesce(workload.service_port, workload.port) <= 65535 && alltrue([
        for sidecar_name, sidecar in workload.sidecars :
        can(regex("^[a-z][a-z0-9-]{0,62}$", sidecar_name)) &&
        can(regex("^[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$", sidecar.image)) &&
        sidecar.port >= 1 && sidecar.port <= 65535
      ])
    ])
    error_message = "Every workload requires an exact source commit, digest-pinned images, valid scaling bounds, and a valid port."
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

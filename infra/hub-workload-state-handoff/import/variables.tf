variable "kubeconfig_path" {
  description = "Private kubeconfig used only to read and import exact existing objects."
  type        = string
  sensitive   = true
}

variable "kubeconfig_context" {
  description = "Exact kubeconfig context for the reviewed AKS target."
  type        = string
}

variable "namespace" {
  description = "Existing namespace containing every reviewed workload object."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$", var.namespace))
    error_message = "namespace must be one Kubernetes DNS label."
  }
}

variable "deployments" {
  description = "Exact existing Deployment names mapped to namespace/name import IDs."
  type        = map(string)

  validation {
    condition = length(var.deployments) <= 64 && alltrue([
      for name, id in var.deployments :
      can(regex("^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$", name)) &&
      id == "${var.namespace}/${name}"
    ])
    error_message = "Deployment import IDs must exactly equal namespace/name."
  }
}

variable "services" {
  description = "Exact existing Service names mapped to namespace/name import IDs."
  type        = map(string)

  validation {
    condition = length(var.services) <= 64 && alltrue([
      for name, id in var.services :
      can(regex("^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$", name)) &&
      id == "${var.namespace}/${name}"
    ])
    error_message = "Service import IDs must exactly equal namespace/name."
  }
}

variable "cron_jobs" {
  description = "Exact existing CronJob names mapped to namespace/name import IDs."
  type        = map(string)

  validation {
    condition = length(var.cron_jobs) <= 64 && alltrue([
      for name, id in var.cron_jobs :
      can(regex("^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$", name)) &&
      id == "${var.namespace}/${name}"
    ])
    error_message = "CronJob import IDs must exactly equal namespace/name."
  }
}

variable "horizontal_pod_autoscalers" {
  description = "Exact existing HorizontalPodAutoscaler names mapped to namespace/name import IDs."
  type        = map(string)

  validation {
    condition = length(var.horizontal_pod_autoscalers) <= 64 && alltrue([
      for name, id in var.horizontal_pod_autoscalers :
      can(regex("^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$", name)) &&
      id == "${var.namespace}/${name}"
    ])
    error_message = "HorizontalPodAutoscaler import IDs must exactly equal namespace/name."
  }
}

check "nonempty_inventory" {
  assert {
    condition = (
      length(var.deployments) +
      length(var.services) +
      length(var.cron_jobs) +
      length(var.horizontal_pod_autoscalers)
    ) > 0
    error_message = "At least one exact existing workload object is required."
  }
}

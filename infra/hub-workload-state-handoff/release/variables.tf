variable "kubeconfig_path" {
  description = "Private kubeconfig used only to refresh the reviewed state-release plan."
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
}

variable "deployments" {
  description = "Reviewed Deployment import inventory retained for plan verification."
  type        = map(string)
}

variable "services" {
  description = "Reviewed Service import inventory retained for plan verification."
  type        = map(string)
}

variable "cron_jobs" {
  description = "Reviewed CronJob import inventory retained for plan verification."
  type        = map(string)
}

variable "horizontal_pod_autoscalers" {
  description = "Reviewed HorizontalPodAutoscaler import inventory retained for plan verification."
  type        = map(string)
}

check "exact_import_ids" {
  assert {
    condition = alltrue(flatten([
      for objects in [
        var.deployments,
        var.services,
        var.cron_jobs,
        var.horizontal_pod_autoscalers,
        ] : [
        for name, id in objects :
        can(regex("^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$", name)) &&
        id == "${var.namespace}/${name}"
      ]
    ]))
    error_message = "Every retained import ID must exactly equal namespace/name."
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

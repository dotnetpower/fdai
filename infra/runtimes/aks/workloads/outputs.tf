output "namespace" {
  description = "Namespace containing FDAI workloads."
  value       = kubernetes_namespace_v1.runtime.metadata[0].name
}

output "workload_names" {
  description = "Declared FDAI Deployment names."
  value       = sort(keys(kubernetes_deployment_v1.workload))
}

output "scheduled_job_names" {
  description = "Declared FDAI CronJob names."
  value       = sort(keys(kubernetes_cron_job_v1.job))
}

output "external_service_names" {
  description = "Public service names selected by the workload specification."
  value       = sort([for name, workload in var.workloads : name if workload.external])
}

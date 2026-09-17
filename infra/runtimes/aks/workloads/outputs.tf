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

output "external_service_addresses" {
  description = "Public LoadBalancer addresses keyed by external workload name."
  value = {
    for name, workload in var.workloads : name => coalesce(
      try(kubernetes_service_v1.workload[name].status[0].load_balancer[0].ingress[0].ip, null),
      try(kubernetes_service_v1.workload[name].status[0].load_balancer[0].ingress[0].hostname, null),
    ) if workload.external
  }
}

output "browser_gateway_operator_url" {
  description = "HTTPS base URL for the root-routed Operator API."
  value       = local.browser_gateway_enabled ? azurerm_api_management.browser_gateway[0].gateway_url : ""
}

output "browser_gateway_ingestion_url" {
  description = "HTTPS base URL for the dedicated document-ingestion API."
  value       = local.browser_gateway_enabled ? "${azurerm_api_management.browser_gateway[0].gateway_url}/ingestion" : ""
}

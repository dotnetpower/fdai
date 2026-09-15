output "cluster_id" {
  description = "AKS cluster resource id."
  value       = azurerm_kubernetes_cluster.runtime.id
}

output "cluster_name" {
  description = "AKS cluster name."
  value       = azurerm_kubernetes_cluster.runtime.name
}

output "private_fqdn" {
  description = "Private AKS API hostname used by the managed deployment host."
  value       = azurerm_kubernetes_cluster.runtime.private_fqdn
}

output "oidc_issuer_url" {
  description = "OIDC issuer used for workload identity federation."
  value       = azurerm_kubernetes_cluster.runtime.oidc_issuer_url
}

output "kubelet_identity_object_id" {
  description = "Kubelet identity object id granted ACR pull."
  value       = azurerm_kubernetes_cluster.runtime.kubelet_identity[0].object_id
}

output "host" {
  description = "Private Kubernetes API endpoint for the separately initialized workloads provider."
  value       = azurerm_kubernetes_cluster.runtime.kube_config[0].host
  sensitive   = true
}

output "cluster_ca_certificate" {
  description = "Cluster CA for the separately initialized workloads provider."
  value       = azurerm_kubernetes_cluster.runtime.kube_config[0].cluster_ca_certificate
  sensitive   = true
}

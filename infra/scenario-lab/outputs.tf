output "resource_group_name" {
  description = "Resource group that owns the disposable scenario lab."
  value       = azurerm_resource_group.scenario_lab.name
}

output "key_vault_name" {
  description = "Private Key Vault that stores the generated MySQL password."
  value       = module.key_vault.name
}

output "mysql_password_secret_name" {
  description = "Key Vault secret name retrieved into an ephemeral runner file before a test."
  value       = azurerm_key_vault_secret.mysql_admin_password.name
}

output "operator_dns_routing_domains" {
  description = "Private service suffixes added to the generated P2S VPN profile for workstation testing."
  value = [
    "mysql.database.azure.com",
    "openai.azure.com",
    "vault.azure.net",
    "vaultcore.azure.net",
  ]
}

output "operator_access_enabled" {
  description = "Whether direct P2S VPN routing, DNS, and operator RBAC are configured."
  value       = local.operator_enabled
}

output "enforce_environment" {
  description = "Sensitive runner-only values used to materialize the FDAI_ENFORCE_* environment."
  sensitive   = true
  value = {
    subscription_id       = data.azurerm_client_config.current.subscription_id
    resource_group        = azurerm_resource_group.scenario_lab.name
    aks_cluster_name      = azurerm_kubernetes_cluster.scenario_lab.name
    aks_context           = azurerm_kubernetes_cluster.scenario_lab.name
    workload_namespace    = "fdai-sre-demo"
    chaos_namespace       = "chaos-mesh"
    backend_deployment    = "api-backend"
    backend_service       = "api-backend"
    backend_label         = "app=api-backend"
    backend_container     = "web"
    backend_replicas      = 3
    vm_name               = azurerm_linux_virtual_machine.stress.name
    mysql_host            = azurerm_mysql_flexible_server.scenario_lab.fqdn
    mysql_user            = var.mysql_admin_login
    mysql_server          = azurerm_mysql_flexible_server.scenario_lab.name
    mysql_password_secret = azurerm_key_vault_secret.mysql_admin_password.name
    key_vault_name        = module.key_vault.name
    azure_openai_endpoint = module.azure_openai.endpoint
    azure_openai_deployment = lookup(
      module.azure_openai.deployments,
      var.azure_openai_deployment_name,
      var.azure_openai_deployment_name,
    )
  }
}

output "portal_resource_group_path" {
  description = "Azure portal resource-group path without tenant-specific host assumptions."
  value       = azurerm_resource_group.scenario_lab.id
}

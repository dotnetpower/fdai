output "resource_group_name" {
  description = "Resource group that owns the disposable scenario lab."
  value       = data.azurerm_resource_group.scenario_lab.name
}

output "operator_dns_routing_domains" {
  description = "Private service suffixes added to the generated P2S VPN profile for workstation testing."
  value = [
    "mysql.database.azure.com",
    "openai.azure.com",
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
    resource_group        = data.azurerm_resource_group.scenario_lab.name
    aks_cluster_name      = azurerm_kubernetes_cluster.scenario_lab.name
    aks_context           = azurerm_kubernetes_cluster.scenario_lab.name
    workload_namespace    = "fdai-sre-demo"
    chaos_namespace       = "chaos-mesh"
    backend_deployment    = "order-service"
    backend_service       = "order-service"
    backend_label         = "app=order-service"
    backend_container     = "order-service"
    backend_replicas      = 3
    backend_image         = "ghcr.io/azure-samples/aks-store-demo/order-service"
    store_front_dns_label = local.store_front_dns_label
    store_front_hostname  = local.store_front_dns_hostname
    vm_name               = azurerm_linux_virtual_machine.stress.name
    mysql_host            = azurerm_mysql_flexible_server.scenario_lab.fqdn
    mysql_user            = var.mysql_admin_login
    mysql_server          = azurerm_mysql_flexible_server.scenario_lab.name
    mysql_password        = random_password.mysql_admin.result
    azure_openai_endpoint = module.azure_openai.endpoint
    azure_openai_deployment = lookup(
      module.azure_openai.deployments,
      var.azure_openai_deployment_name,
      var.azure_openai_deployment_name,
    )
    commerce_enabled             = var.commerce_enabled
    commerce_namespace           = var.commerce_namespace
    commerce_identity_client_id  = var.commerce_enabled ? azurerm_user_assigned_identity.commerce[0].client_id : null
    commerce_servicebus_id       = var.commerce_enabled ? azurerm_servicebus_namespace.commerce[0].id : null
    commerce_servicebus_hostname = var.commerce_enabled ? "${azurerm_servicebus_namespace.commerce[0].name}.servicebus.windows.net" : null
    commerce_cosmos_id           = var.commerce_enabled ? azurerm_cosmosdb_account.commerce[0].id : null
    commerce_cosmos_endpoint     = var.commerce_enabled ? azurerm_cosmosdb_account.commerce[0].endpoint : null
  }
}

output "portal_resource_group_path" {
  description = "Azure portal resource-group path without tenant-specific host assumptions."
  value       = data.azurerm_resource_group.scenario_lab.id
}

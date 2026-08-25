resource "azurerm_role_assignment" "aks_network_contributor" {
  scope                = azurerm_virtual_network.scenario_lab.id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_user_assigned_identity.aks.principal_id
}

resource "azurerm_kubernetes_cluster" "scenario_lab" {
  # checkov:skip=CKV_AZURE_117:CMK-backed node disks add durable key infrastructure to a disposable fault target.
  # checkov:skip=CKV_AZURE_116:The one-node lab validates fault behavior, not Azure Policy admission.
  # checkov:skip=CKV_AZURE_232:A separate tainted system pool would double the minimum node cost.
  # checkov:skip=CKV_AZURE_168:Thirty pods bound the one-node lab and cover the three-replica workload.
  # checkov:skip=CKV_AZURE_170:Paid AKS SLA is not required for an approved disposable test window.
  # checkov:skip=CKV_AZURE_226:Managed OS disks avoid ephemeral-disk SKU coupling in regional labs.
  # checkov:skip=CKV_AZURE_227:Host encryption is subscription-feature and SKU gated; storage encryption remains platform-managed.
  # checkov:skip=CKV_AZURE_172:The lab mounts no Key Vault secrets through the CSI driver.
  # checkov:skip=CKV_AZURE_171:AzureRM 4.x uses automatic_upgrade_channel; this check still reads the retired attribute name.
  name                                = "aks-${local.suffix}"
  location                            = data.azurerm_resource_group.scenario_lab.location
  resource_group_name                 = data.azurerm_resource_group.scenario_lab.name
  dns_prefix                          = "aks-${local.suffix}"
  private_cluster_enabled             = true
  private_cluster_public_fqdn_enabled = true
  private_dns_zone_id                 = "System"
  local_account_disabled              = true
  oidc_issuer_enabled                 = true
  workload_identity_enabled           = true
  role_based_access_control_enabled   = true
  sku_tier                            = "Free"
  support_plan                        = "KubernetesOfficial"
  automatic_upgrade_channel           = "patch"
  node_os_upgrade_channel             = "NodeImage"
  tags                                = local.tags

  default_node_pool {
    name                         = "system"
    vm_size                      = var.aks_node_vm_size
    node_count                   = 1
    vnet_subnet_id               = azurerm_subnet.aks.id
    only_critical_addons_enabled = false
    os_disk_type                 = "Managed"
    os_sku                       = "Ubuntu"
    temporary_name_for_rotation  = "systemtmp"
    max_pods                     = 30
    tags                         = local.tags

    upgrade_settings {
      max_surge = "10%"
    }
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.aks.id]
  }

  azure_active_directory_role_based_access_control {
    azure_rbac_enabled = true
    tenant_id          = data.azurerm_client_config.current.tenant_id
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_policy      = "azure"
    outbound_type       = "userAssignedNATGateway"
    load_balancer_sku   = "standard"
    service_cidr        = "10.43.0.0/24"
    dns_service_ip      = "10.43.0.10"
    pod_cidr            = "10.44.0.0/16"
  }

  oms_agent {
    log_analytics_workspace_id      = module.log_analytics.workspace_id
    msi_auth_for_monitoring_enabled = true
  }

  depends_on = [
    azurerm_role_assignment.aks_network_contributor,
    azurerm_subnet_nat_gateway_association.aks,
  ]
}

resource "azurerm_role_assignment" "runner_aks_credentials" {
  scope                = azurerm_kubernetes_cluster.scenario_lab.id
  role_definition_name = "Azure Kubernetes Service Cluster User Role"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "runner_aks_admin" {
  scope                = azurerm_kubernetes_cluster.scenario_lab.id
  role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "operator_aks_credentials" {
  count = local.operator_enabled ? 1 : 0

  scope                = azurerm_kubernetes_cluster.scenario_lab.id
  role_definition_name = "Azure Kubernetes Service Cluster User Role"
  principal_id         = var.operator_access.principal_id
}

resource "azurerm_role_assignment" "operator_aks_admin" {
  count = local.operator_enabled ? 1 : 0

  scope                = azurerm_kubernetes_cluster.scenario_lab.id
  role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"
  principal_id         = var.operator_access.principal_id
}

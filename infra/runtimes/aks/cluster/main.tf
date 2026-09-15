locals {
  name = "aks-${var.workload}-${var.environment}-${var.region_short}"
  tags = merge(var.tags, {
    "fdai:managed"   = "true"
    "fdai:component" = "aks-runtime"
    "fdai:runtime"   = "aks"
  })
}

data "azurerm_client_config" "current" {}

resource "azurerm_user_assigned_identity" "cluster" {
  name                = "id-${local.name}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = local.tags
}

resource "azurerm_role_assignment" "cluster_network" {
  scope                = var.aks_subnet_id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_user_assigned_identity.cluster.principal_id
}

resource "azurerm_kubernetes_cluster" "runtime" {
  # checkov:skip=CKV_AZURE_117:Azure-managed encryption is retained until a deployment selects an independently governed CMK profile.
  # checkov:skip=CKV_AZURE_171:AzureRM 4.x uses automatic_upgrade_channel; the pinned scanner reads the retired automatic_channel_upgrade attribute.
  # checkov:skip=CKV_AZURE_226:Managed OS disks support the diskless default SKUs; platform-managed disk encryption and host encryption remain enabled.
  # checkov:skip=CKV_AZURE_227:AzureRM 4.x uses host_encryption_enabled; the pinned scanner reads the retired enable_host_encryption attribute.
  name                                = local.name
  location                            = var.location
  resource_group_name                 = var.resource_group_name
  dns_prefix                          = local.name
  private_cluster_enabled             = true
  private_cluster_public_fqdn_enabled = true
  private_dns_zone_id                 = "System"
  local_account_disabled              = true
  oidc_issuer_enabled                 = true
  workload_identity_enabled           = true
  role_based_access_control_enabled   = true
  azure_policy_enabled                = true
  sku_tier                            = "Standard"
  support_plan                        = "KubernetesOfficial"
  automatic_upgrade_channel           = "patch"
  node_os_upgrade_channel             = "NodeImage"
  tags                                = local.tags

  default_node_pool {
    name                         = "system"
    vm_size                      = var.system_node_sku
    node_count                   = var.system_node_count
    vnet_subnet_id               = var.aks_subnet_id
    only_critical_addons_enabled = true
    os_disk_type                 = "Managed"
    host_encryption_enabled      = true
    os_sku                       = "AzureLinux"
    temporary_name_for_rotation  = "systemtmp"
    max_pods                     = 50
    zones                        = var.availability_zones
    tags                         = local.tags

    upgrade_settings {
      max_surge = "33%"
    }
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.cluster.id]
  }

  azure_active_directory_role_based_access_control {
    azure_rbac_enabled = true
    tenant_id          = data.azurerm_client_config.current.tenant_id
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium"
    network_policy      = "cilium"
    outbound_type       = "managedNATGateway"
    load_balancer_sku   = "standard"
    service_cidr        = "10.43.0.0/24"
    dns_service_ip      = "10.43.0.10"
    pod_cidr            = "10.44.0.0/16"
  }

  oms_agent {
    log_analytics_workspace_id      = var.log_analytics_workspace_id
    msi_auth_for_monitoring_enabled = true
  }

  key_vault_secrets_provider {
    secret_rotation_enabled = true
  }

  depends_on = [azurerm_role_assignment.cluster_network]
}

resource "azurerm_kubernetes_cluster_node_pool" "user" {
  # checkov:skip=CKV_AZURE_227:AzureRM 4.x uses host_encryption_enabled; the pinned scanner reads the retired enable_host_encryption attribute.
  name                    = "runtime"
  kubernetes_cluster_id   = azurerm_kubernetes_cluster.runtime.id
  vm_size                 = var.user_node_sku
  auto_scaling_enabled    = true
  min_count               = var.user_node_min_count
  max_count               = var.user_node_max_count
  mode                    = "User"
  os_disk_type            = "Managed"
  host_encryption_enabled = true
  os_sku                  = "AzureLinux"
  vnet_subnet_id          = var.aks_subnet_id
  zones                   = var.availability_zones
  max_pods                = 50
  node_labels = {
    "fdai.io/pool" = "runtime"
  }
  tags = local.tags

  upgrade_settings {
    max_surge = "33%"
  }
}

resource "azurerm_role_assignment" "managed_host_cluster_user" {
  scope                = azurerm_kubernetes_cluster.runtime.id
  role_definition_name = "Azure Kubernetes Service Cluster User Role"
  principal_id         = var.managed_host_principal_id
}

resource "azurerm_role_assignment" "managed_host_cluster_admin" {
  scope                = azurerm_kubernetes_cluster.runtime.id
  role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"
  principal_id         = var.managed_host_principal_id
}

resource "azurerm_role_assignment" "kubelet_acr_pull" {
  scope                = var.container_registry_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.runtime.kubelet_identity[0].object_id
}

locals {
  name = "aks-${var.workload}-${var.environment}-${var.region_short}"
  container_insights_dcr_name = trimsuffix(
    substr("MSCI-${var.location}-${local.name}", 0, 64),
    "-",
  )
  tags = merge(var.tags, {
    "fdai:managed"   = "true"
    "fdai:component" = "aks-runtime"
    "fdai:runtime"   = "aks"
  })
}

data "azurerm_client_config" "current" {}

resource "azurerm_public_ip" "egress" {
  name                = "pip-${local.name}-egress"
  location            = var.location
  resource_group_name = var.resource_group_name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags

  lifecycle {
    # Azure Policy owns IP tags; Terraform continues to own regular resource tags.
    ignore_changes = [ip_tags]
  }
}

resource "azurerm_nat_gateway" "egress" {
  name                    = "nat-${local.name}"
  location                = var.location
  resource_group_name     = var.resource_group_name
  sku_name                = "Standard"
  idle_timeout_in_minutes = 4
  tags                    = local.tags
}

resource "azurerm_nat_gateway_public_ip_association" "egress" {
  nat_gateway_id       = azurerm_nat_gateway.egress.id
  public_ip_address_id = azurerm_public_ip.egress.id
}

resource "azurerm_subnet_nat_gateway_association" "egress" {
  subnet_id      = var.aks_subnet_id
  nat_gateway_id = azurerm_nat_gateway.egress.id
}

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

resource "azurerm_role_assignment" "cluster_api_network" {
  scope                = var.aks_api_server_subnet_id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_user_assigned_identity.cluster.principal_id
}

#trivy:ignore:AZU-0065
resource "azurerm_kubernetes_cluster" "runtime" {
  # checkov:skip=CKV_AZURE_117:Azure-managed encryption is retained until a deployment selects an independently governed CMK profile.
  # checkov:skip=CKV_AZURE_115:The basic stage restricts public API access by CIDR and Entra RBAC before a separately governed private transition.
  # checkov:skip=CKV_AZURE_171:AzureRM 4.x uses automatic_upgrade_channel; the pinned scanner reads the retired automatic_channel_upgrade attribute.
  # checkov:skip=CKV_AZURE_226:Managed OS disks support the diskless default SKUs; platform-managed disk encryption and host encryption remain enabled.
  # checkov:skip=CKV_AZURE_227:AzureRM 4.x uses host_encryption_enabled; the pinned scanner reads the retired enable_host_encryption attribute.
  # The basic stage uses explicit authorized CIDRs, Entra RBAC, disabled local accounts, and API Server VNet Integration before a separately verified private transition.
  name                                = local.name
  location                            = var.location
  resource_group_name                 = var.resource_group_name
  dns_prefix                          = local.name
  private_cluster_enabled             = var.private_cluster_enabled
  private_cluster_public_fqdn_enabled = var.private_cluster_enabled
  private_dns_zone_id                 = var.private_cluster_enabled ? "System" : null
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

  api_server_access_profile {
    virtual_network_integration_enabled = true
    subnet_id                           = var.aks_api_server_subnet_id
    authorized_ip_ranges                = var.api_server_authorized_ip_ranges
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium"
    network_policy      = "cilium"
    outbound_type       = "userAssignedNATGateway"
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

  depends_on = [
    azurerm_role_assignment.cluster_network,
    azurerm_role_assignment.cluster_api_network,
    azurerm_nat_gateway_public_ip_association.egress,
    azurerm_subnet_nat_gateway_association.egress,
  ]
}

resource "azurerm_monitor_data_collection_rule" "container_insights" {
  name                = local.container_insights_dcr_name
  location            = var.location
  resource_group_name = var.resource_group_name
  description         = "Collect AKS Container Insights logs and inventory."
  tags                = local.tags

  destinations {
    log_analytics {
      name                  = "ciworkspace"
      workspace_resource_id = var.log_analytics_workspace_id
    }
  }

  data_flow {
    streams      = ["Microsoft-ContainerInsights-Group-Default"]
    destinations = ["ciworkspace"]
  }

  data_sources {
    extension {
      name           = "ContainerInsightsExtension"
      extension_name = "ContainerInsights"
      streams        = ["Microsoft-ContainerInsights-Group-Default"]
      extension_json = jsonencode({
        dataCollectionSettings = {
          interval               = "1m"
          namespaceFilteringMode = "Off"
          namespaces             = []
          enableContainerLogV2   = true
        }
      })
    }
  }
}

resource "azurerm_monitor_data_collection_rule_association" "container_insights" {
  name                    = "ContainerInsightsExtension"
  target_resource_id      = azurerm_kubernetes_cluster.runtime.id
  data_collection_rule_id = azurerm_monitor_data_collection_rule.container_insights.id
  description             = "Associate the Container Insights collection rule with the AKS cluster."
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

locals {
  tags = merge(var.additional_tags, {
    "fdai:managed"    = "true"
    "fdai:workload"   = "ci"
    "fdai:layer"      = "ci-runner-controller"
    "fdai:managed-by" = "terraform"
    "fdai:vertical"   = "shared"
  })
  worker_tags              = merge(local.tags, { "fdai:layer" = "ci-runner-worker" })
  jobs                     = { control = "caj-${var.name}-control", general = "caj-${var.name}-general" }
  name_prefix              = "${var.name}-worker"
  vm_enabled               = var.vm_image_id != ""
  subnet_resource_group_id = local.vm_enabled ? join("/", slice(split("/", var.vm_subnet_id), 0, min(5, length(split("/", var.vm_subnet_id))))) : null
  image_resource_group_id  = local.vm_enabled ? join("/", slice(split("/", var.vm_image_id), 0, min(5, length(split("/", var.vm_image_id))))) : null
  config = {
    repository        = var.github_repository
    subscription_id   = var.subscription_id
    resource_group    = azurerm_resource_group.workers.name
    jobs              = local.jobs
    storage_url       = azurerm_storage_account.state.primary_blob_endpoint
    storage_container = azurerm_storage_container.state.name
    storage_blob      = var.storage_blob
    controller_url    = var.controller_base_url
    vm_subnet_id      = var.vm_subnet_id
    vm_image_id       = var.vm_image_id
    vm_size           = var.vm_size
    ssh_public_key    = var.ssh_public_key
    location          = var.location
    worker_image      = var.worker_image
    name_prefix       = local.name_prefix
    cpu_budgets       = { container_cpu = 260, vm_cpu = 64 }
  }
}

resource "azurerm_resource_group" "controller" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.tags
}

resource "azurerm_resource_group" "workers" {
  name     = var.worker_resource_group_name
  location = var.location
  tags     = local.worker_tags
}

resource "azurerm_log_analytics_workspace" "controller" {
  name                = "log-${var.name}-controller"
  resource_group_name = azurerm_resource_group.controller.name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_log_analytics_workspace" "workers" {
  name                = "log-${var.name}-workers"
  resource_group_name = azurerm_resource_group.workers.name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.worker_tags
}

# Separate environments, not just separate app identities: build code never shares the
# controller's managed-identity endpoint, environment, state mount or workspace.
resource "azurerm_container_app_environment" "controller" {
  name                       = "cae-${var.name}-controller"
  resource_group_name        = azurerm_resource_group.controller.name
  location                   = var.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.controller.id
  tags                       = local.tags
}

resource "azurerm_container_app_environment" "workers" {
  name                       = "cae-${var.name}-workers"
  resource_group_name        = azurerm_resource_group.workers.name
  location                   = var.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.workers.id
  tags                       = local.worker_tags
}

# The controller has no VNet attachment. Public Blob HTTPS is Entra-only, not
# anonymous access; adding a private endpoint requires a separate trusted subnet.
# Blob service diagnostic settings below replace legacy shared-key queue logging.
# Platform-managed double encryption avoids adding a Key Vault/key-management identity.
#trivy:ignore:AZU-0012
#trivy:ignore:AZU-0057
#trivy:ignore:AZU-0060
resource "azurerm_storage_account" "state" {
  # checkov:skip=CKV_AZURE_59:Dedicated non-VNet controller uses authenticated HTTPS to Blob; shared keys and anonymous access are disabled and its RBAC is container-scoped.
  # checkov:skip=CKV_AZURE_190:No application or worker network is attached; a private endpoint needs a separately reviewed controller VNet, not the untrusted CI subnet.
  # checkov:skip=CKV2_AZURE_33:Private endpoints require a separately reviewed trusted controller VNet; this Blob-only account uses Entra-authenticated HTTPS and container-only RBAC.
  # checkov:skip=CKV2_AZURE_1:Platform-managed double encryption protects isolated nonsecret CI state without introducing a Key Vault/key-management identity.
  # checkov:skip=CKV_AZURE_33:Queues are not used; Blob read/write/delete diagnostics are enabled below without enabling shared-key Storage Analytics.
  # checkov:skip=CKV_AZURE_206:ZRS replicates this single-region CI lease/state across availability zones; geographic failover of stale controller state is not part of this root's recovery contract.
  name                              = var.storage_account_name
  resource_group_name               = azurerm_resource_group.controller.name
  location                          = var.location
  account_tier                      = "Standard"
  account_replication_type          = "ZRS"
  account_kind                      = "StorageV2"
  min_tls_version                   = "TLS1_2"
  https_traffic_only_enabled        = true
  infrastructure_encryption_enabled = true
  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  allow_nested_items_to_be_public   = false
  cross_tenant_replication_enabled  = false
  local_user_enabled                = false
  public_network_access_enabled     = true
  tags                              = local.tags

  blob_properties {
    versioning_enabled       = true
    change_feed_enabled      = true
    last_access_time_enabled = true
    delete_retention_policy {
      days = 7
    }
    container_delete_retention_policy {
      days = 7
    }
  }
}

resource "azurerm_storage_container" "state" {
  # checkov:skip=CKV2_AZURE_21:The graph check misses this ARM container linkage; state_blob explicitly enables StorageRead, StorageWrite and StorageDelete on its blobServices/default parent.
  name                  = "controller-state"
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
}

resource "azurerm_monitor_diagnostic_setting" "state_blob" {
  name                       = "diag-${var.name}-state-blob"
  target_resource_id         = "${azurerm_storage_account.state.id}/blobServices/default"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.controller.id

  enabled_log {
    category = "StorageRead"
  }
  enabled_log {
    category = "StorageWrite"
  }
  enabled_log {
    category = "StorageDelete"
  }
  enabled_metric {
    category = "AllMetrics"
  }
}

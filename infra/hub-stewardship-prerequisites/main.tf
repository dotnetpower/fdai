data "azurerm_client_config" "current" {}

data "azurerm_resource_group" "target" {
  name = var.resource_group_name
}

data "azurerm_container_registry" "target" {
  name                = var.acr_name
  resource_group_name = var.resource_group_name
}

data "azurerm_key_vault" "target" {
  name                = var.key_vault_name
  resource_group_name = var.resource_group_name
}

data "azurerm_key_vault_secret" "state_store_dsn" {
  name         = var.state_store_dsn_secret_name
  key_vault_id = data.azurerm_key_vault.target.id
}

data "azurerm_eventhub" "pantheon_objects" {
  name                = "fdai.pantheon.objects"
  namespace_name      = var.eventhub_namespace_name
  resource_group_name = var.resource_group_name
}

data "azurerm_eventhub" "pipeline_stages" {
  name                = "fdai.pipeline.stages"
  namespace_name      = var.eventhub_namespace_name
  resource_group_name = var.resource_group_name
}

data "azurerm_log_analytics_workspace" "target" {
  name                = var.log_analytics_workspace_name
  resource_group_name = var.resource_group_name
}

data "azurerm_virtual_network" "target" {
  name                = var.vnet_name
  resource_group_name = var.resource_group_name
}

data "azurerm_subnet" "private_endpoints" {
  name                 = var.private_endpoint_subnet_name
  virtual_network_name = var.vnet_name
  resource_group_name  = var.resource_group_name
}

data "azurerm_virtual_network" "ops" {
  name                = var.ops_vnet_name
  resource_group_name = var.ops_resource_group_name
}

data "azurerm_private_dns_zone" "ops_blob" {
  name                = "privatelink.blob.core.windows.net"
  resource_group_name = var.ops_resource_group_name
}

data "azurerm_kubernetes_cluster" "target" {
  name                = var.aks_name
  resource_group_name = var.resource_group_name
}

locals {
  tags = merge(var.tags, {
    "fdai:managed"    = "true"
    "fdai:managed-by" = "terraform"
    "fdai:layer"      = "hub-stewardship-prerequisites"
  })
  identities = {
    ingestion = {
      component       = "document-ingestion-api"
      identity_suffix = "ingestion"
      service_account = "document-ingestion-api"
    }
    worker = {
      component       = "document-ingestion-worker"
      identity_suffix = "ingestion-worker"
      service_account = "document-processing-worker"
    }
    migration = {
      component       = "document-ingestion-migration"
      identity_suffix = "ingestion-migration"
      service_account = "fdai-schema-migration"
    }
    notification = {
      component       = "notification-delivery"
      identity_suffix = "notification"
      service_account = "core-control-plane"
    }
  }
}

module "identity" {
  for_each            = local.identities
  source              = "../modules/identity/user-assigned-mi"
  name                = "id-fdai-dev-wus3-${each.value.identity_suffix}"
  resource_group_name = data.azurerm_resource_group.target.name
  location            = var.location
  tags                = merge(local.tags, { "fdai:component" = each.value.component })
}

resource "azurerm_federated_identity_credential" "workload" {
  for_each            = local.identities
  name                = "fic-${each.value.service_account}"
  resource_group_name = data.azurerm_resource_group.target.name
  parent_id           = module.identity[each.key].resource_id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = data.azurerm_kubernetes_cluster.target.oidc_issuer_url
  subject             = "system:serviceaccount:${var.namespace}:${each.value.service_account}"
}

module "document_storage" {
  source = "../modules/storage/adls-gen2"

  name                            = var.document_storage_name
  resource_group_name             = data.azurerm_resource_group.target.name
  location                        = var.location
  deployer_principal_id           = var.deployer_principal_id
  log_analytics_workspace_id      = data.azurerm_log_analytics_workspace.target.id
  replication_type                = "ZRS"
  public_network_access_enabled   = false
  soft_delete_retention_days      = 30
  container_delete_retention_days = 30
  quarantine_retention_days       = 30
  derived_cool_after_days         = 30
  tags                            = merge(local.tags, { "fdai:component" = "document-storage" })
}

module "document_intelligence" {
  source = "../modules/document-intelligence"

  account_name               = "di-fdai-dev-wus3-${var.name_suffix}"
  location                   = var.location
  resource_group_name        = data.azurerm_resource_group.target.name
  private_networking_enabled = true
  log_analytics_workspace_id = data.azurerm_log_analytics_workspace.target.id
  tags                       = merge(local.tags, { "fdai:component" = "document-intelligence" })
}

module "document_blob_private_endpoint" {
  source = "../modules/private-endpoint"

  name                  = "pe-${var.document_storage_name}-blob"
  location              = var.location
  resource_group_name   = data.azurerm_resource_group.target.name
  subnet_id             = data.azurerm_subnet.private_endpoints.id
  vnet_id               = data.azurerm_virtual_network.target.id
  target_resource_id    = module.document_storage.id
  subresource_name      = "blob"
  private_dns_zone_name = "privatelink.blob.core.windows.net"
  additional_private_dns_zone_ids = [
    data.azurerm_private_dns_zone.ops_blob.id,
  ]
  tags = local.tags
}

module "document_dfs_private_endpoint" {
  source = "../modules/private-endpoint"

  name                  = "pe-${var.document_storage_name}-dfs"
  location              = var.location
  resource_group_name   = data.azurerm_resource_group.target.name
  subnet_id             = data.azurerm_subnet.private_endpoints.id
  vnet_id               = data.azurerm_virtual_network.target.id
  target_resource_id    = module.document_storage.id
  subresource_name      = "dfs"
  private_dns_zone_name = "privatelink.dfs.core.windows.net"
  extra_vnet_links      = { ops = data.azurerm_virtual_network.ops.id }
  tags                  = local.tags
}

module "document_intelligence_private_endpoint" {
  source = "../modules/private-endpoint"

  name                  = "pe-di-fdai-dev-wus3-${var.name_suffix}"
  location              = var.location
  resource_group_name   = data.azurerm_resource_group.target.name
  subnet_id             = data.azurerm_subnet.private_endpoints.id
  vnet_id               = data.azurerm_virtual_network.target.id
  target_resource_id    = module.document_intelligence.resource_id
  subresource_name      = "account"
  private_dns_zone_name = "privatelink.cognitiveservices.azure.com"
  extra_vnet_links      = { ops = data.azurerm_virtual_network.ops.id }
  tags                  = local.tags
}

resource "azurerm_key_vault_secret" "ingestion_api_dsn" {
  # checkov:skip=CKV_AZURE_41:This managed-identity DSN selects a database role; rotation follows coordinated role and workload rollout rather than an independent expiry.
  name         = "fdai-ingestion-api-dsn"
  value        = "${data.azurerm_key_vault_secret.state_store_dsn.value}&options=-c%20role%3Dfdai_ingestion_api"
  key_vault_id = data.azurerm_key_vault.target.id
  content_type = "postgres-dsn-role-fdai-ingestion-api"
  tags         = local.tags
}

resource "azurerm_key_vault_secret" "ingestion_worker_dsn" {
  # checkov:skip=CKV_AZURE_41:This managed-identity DSN selects a database role; rotation follows coordinated role and workload rollout rather than an independent expiry.
  name         = "fdai-ingestion-worker-dsn"
  value        = "${data.azurerm_key_vault_secret.state_store_dsn.value}&options=-c%20role%3Dfdai_ingestion_worker"
  key_vault_id = data.azurerm_key_vault.target.id
  content_type = "postgres-dsn-role-fdai-ingestion-worker"
  tags         = local.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  for_each             = toset(["ingestion", "worker", "migration"])
  scope                = data.azurerm_container_registry.target.id
  role_definition_name = "AcrPull"
  principal_id         = module.identity[each.key].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "api_secret_reader" {
  scope                = azurerm_key_vault_secret.ingestion_api_dsn.resource_versionless_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = module.identity["ingestion"].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "worker_secret_reader" {
  scope                = azurerm_key_vault_secret.ingestion_worker_dsn.resource_versionless_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = module.identity["worker"].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "migration_secret_reader" {
  scope                = data.azurerm_key_vault_secret.state_store_dsn.resource_versionless_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = module.identity["migration"].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "document_data" {
  for_each             = toset(["ingestion", "worker"])
  scope                = module.document_storage.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = module.identity[each.key].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "pantheon_sender" {
  for_each             = toset(["ingestion", "worker"])
  scope                = data.azurerm_eventhub.pantheon_objects.id
  role_definition_name = "Azure Event Hubs Data Sender"
  principal_id         = module.identity[each.key].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "worker_pantheon_receiver" {
  scope                = data.azurerm_eventhub.pantheon_objects.id
  role_definition_name = "Azure Event Hubs Data Receiver"
  principal_id         = module.identity["worker"].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "pipeline_sender" {
  scope                = data.azurerm_eventhub.pipeline_stages.id
  role_definition_name = "Azure Event Hubs Data Sender"
  principal_id         = module.identity["ingestion"].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "pipeline_receiver" {
  scope                = data.azurerm_eventhub.pipeline_stages.id
  role_definition_name = "Azure Event Hubs Data Receiver"
  principal_id         = module.identity["worker"].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "ocr_user" {
  scope                = module.document_intelligence.resource_id
  role_definition_name = "Cognitive Services User"
  principal_id         = module.identity["worker"].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_communication_service" "notifications" {
  name                = "acs-fdai-dev-wus3-${var.name_suffix}"
  resource_group_name = data.azurerm_resource_group.target.name
  data_location       = var.email_data_location
  tags                = merge(local.tags, { "fdai:component" = "notification-delivery" })
}

resource "azurerm_email_communication_service" "notifications" {
  name                = "ec-fdai-dev-wus3-${var.name_suffix}"
  resource_group_name = data.azurerm_resource_group.target.name
  data_location       = var.email_data_location
  tags                = merge(local.tags, { "fdai:component" = "notification-delivery" })
}

resource "azurerm_email_communication_service_domain" "notifications" {
  name              = "AzureManagedDomain"
  email_service_id  = azurerm_email_communication_service.notifications.id
  domain_management = "AzureManaged"
  tags              = merge(local.tags, { "fdai:component" = "notification-delivery" })
}

resource "azurerm_communication_service_email_domain_association" "notifications" {
  communication_service_id = azurerm_communication_service.notifications.id
  email_service_domain_id  = azurerm_email_communication_service_domain.notifications.id
}

resource "azurerm_role_assignment" "notification_sender" {
  scope                = azurerm_communication_service.notifications.id
  role_definition_name = "Communication and Email Service Owner"
  principal_id         = module.identity["notification"].principal_id
  principal_type       = "ServicePrincipal"
}

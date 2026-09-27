locals {
  suffix = substr(sha256(var.request_id), 0, 8)
  tags = {
    "fdai:managed"      = "true"
    "fdai:workload"     = "inventory-network-certification"
    "fdai:env"          = "dev"
    "fdai:layer"        = "validation"
    "fdai:managed-by"   = "terraform"
    "fdai:request-id"   = var.request_id
    "fdai:source-sha"   = var.source_revision
    "fdai:expires-at"   = var.expires_at
    "fdai:task-owned"   = "true"
    "fdai:authority"    = "observation-only"
    "fdai:cleanup-mode" = "exact-plan"
  }
  resource_group_name = "rg-fdai-invnet-${local.suffix}"
  storage_name        = "stfdaiinv${local.suffix}"
  postgres_name       = "psql-fdai-invnet-${local.suffix}"
  receipt_name        = "${var.request_id}.json"
  receipt_url         = "https://${local.storage_name}.blob.core.windows.net/receipts/${local.receipt_name}"
  dsn = join("", [
    "postgresql://fdaiadmin:",
    urlencode(random_password.postgres.result),
    "@",
    azurerm_postgresql_flexible_server.certification.fqdn,
    ":5432/fdai?sslmode=require",
  ])
}

resource "terraform_data" "target_fence" {
  input = {
    subscription_id = var.subscription_id
    tenant_id       = var.tenant_id
    source_revision = var.source_revision
    request_id      = var.request_id
  }

  lifecycle {
    precondition {
      condition = (
        lower(data.azurerm_client_config.current.subscription_id) == lower(var.subscription_id) &&
        lower(data.azurerm_client_config.current.tenant_id) == lower(var.tenant_id)
      )
      error_message = "Authenticated Terraform target does not match the certification inputs."
    }
  }
}

resource "azurerm_resource_group" "certification" {
  name     = local.resource_group_name
  location = var.location
  tags     = local.tags
}

resource "azurerm_virtual_network" "certification" {
  name                = "vnet-fdai-invnet-${local.suffix}"
  address_space       = ["10.246.0.0/16"]
  location            = azurerm_resource_group.certification.location
  resource_group_name = azurerm_resource_group.certification.name
  tags                = local.tags
}

resource "azurerm_subnet" "container_apps" {
  name                 = "snet-container-apps"
  resource_group_name  = azurerm_resource_group.certification.name
  virtual_network_name = azurerm_virtual_network.certification.name
  address_prefixes     = ["10.246.0.0/23"]

  delegation {
    name = "container-apps"
    service_delegation {
      name = "Microsoft.App/environments"
    }
  }
}

resource "azurerm_subnet" "postgres" {
  name                 = "snet-postgres"
  resource_group_name  = azurerm_resource_group.certification.name
  virtual_network_name = azurerm_virtual_network.certification.name
  address_prefixes     = ["10.246.4.0/24"]

  delegation {
    name = "postgres"
    service_delegation {
      name = "Microsoft.DBforPostgreSQL/flexibleServers"
    }
  }
}

resource "azurerm_subnet" "private_endpoints" {
  name                              = "snet-private-endpoints"
  resource_group_name               = azurerm_resource_group.certification.name
  virtual_network_name              = azurerm_virtual_network.certification.name
  address_prefixes                  = ["10.246.5.0/24"]
  private_endpoint_network_policies = "Disabled"
}

resource "azurerm_private_dns_zone" "postgres" {
  name                = "privatelink.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.certification.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "link-postgres"
  resource_group_name   = azurerm_resource_group.certification.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.certification.id
  registration_enabled  = false
  tags                  = local.tags
}

resource "azurerm_private_dns_zone" "blob" {
  name                = "privatelink.blob.core.windows.net"
  resource_group_name = azurerm_resource_group.certification.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "blob" {
  name                  = "link-blob"
  resource_group_name   = azurerm_resource_group.certification.name
  private_dns_zone_name = azurerm_private_dns_zone.blob.name
  virtual_network_id    = azurerm_virtual_network.certification.id
  registration_enabled  = false
  tags                  = local.tags
}

resource "random_password" "postgres" {
  length           = 40
  special          = true
  override_special = "_%@-"
}

resource "azurerm_postgresql_flexible_server" "certification" {
  name                          = local.postgres_name
  resource_group_name           = azurerm_resource_group.certification.name
  location                      = azurerm_resource_group.certification.location
  version                       = "16"
  delegated_subnet_id           = azurerm_subnet.postgres.id
  private_dns_zone_id           = azurerm_private_dns_zone.postgres.id
  public_network_access_enabled = false
  administrator_login           = "fdaiadmin"
  administrator_password        = random_password.postgres.result
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  backup_retention_days         = 7
  geo_redundant_backup_enabled  = false
  tags                          = local.tags

  authentication {
    active_directory_auth_enabled = false
    password_auth_enabled         = true
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]
}

resource "azurerm_postgresql_flexible_server_database" "certification" {
  name      = "fdai"
  server_id = azurerm_postgresql_flexible_server.certification.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_storage_account" "receipts" {
  name                            = local.storage_name
  resource_group_name             = azurerm_resource_group.certification.name
  location                        = azurerm_resource_group.certification.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  public_network_access_enabled   = false
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false
  tags                            = local.tags

  blob_properties {
    versioning_enabled = true
    delete_retention_policy {
      days = 7
    }
    container_delete_retention_policy {
      days = 7
    }
  }
}

resource "azurerm_storage_container" "receipts" {
  name                  = "receipts"
  storage_account_id    = azurerm_storage_account.receipts.id
  container_access_type = "private"
}

resource "azurerm_private_endpoint" "blob" {
  name                = "pe-invnet-blob-${local.suffix}"
  location            = azurerm_resource_group.certification.location
  resource_group_name = azurerm_resource_group.certification.name
  subnet_id           = azurerm_subnet.private_endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "blob"
    private_connection_resource_id = azurerm_storage_account.receipts.id
    is_manual_connection           = false
    subresource_names              = ["blob"]
  }

  private_dns_zone_group {
    name                 = "blob"
    private_dns_zone_ids = [azurerm_private_dns_zone.blob.id]
  }
}

resource "azurerm_log_analytics_workspace" "certification" {
  name                = "log-fdai-invnet-${local.suffix}"
  location            = azurerm_resource_group.certification.location
  resource_group_name = azurerm_resource_group.certification.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_container_app_environment" "certification" {
  name                           = "cae-fdai-invnet-${local.suffix}"
  location                       = azurerm_resource_group.certification.location
  resource_group_name            = azurerm_resource_group.certification.name
  log_analytics_workspace_id     = azurerm_log_analytics_workspace.certification.id
  infrastructure_subnet_id       = azurerm_subnet.container_apps.id
  internal_load_balancer_enabled = true
  tags                           = local.tags
}

resource "azurerm_user_assigned_identity" "campaign" {
  name                = "id-fdai-invnet-campaign-${local.suffix}"
  location            = azurerm_resource_group.certification.location
  resource_group_name = azurerm_resource_group.certification.name
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "verifier" {
  name                = "id-fdai-invnet-verifier-${local.suffix}"
  location            = azurerm_resource_group.certification.location
  resource_group_name = azurerm_resource_group.certification.name
  tags                = local.tags
}

resource "azurerm_role_assignment" "campaign_subscription_reader" {
  scope                = "/subscriptions/${var.subscription_id}"
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.campaign.principal_id
}

resource "azurerm_role_assignment" "campaign_acr_pull" {
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.campaign.principal_id
}

resource "azurerm_role_assignment" "verifier_acr_pull" {
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.verifier.principal_id
}

resource "azurerm_role_assignment" "campaign_receipt_writer" {
  scope                = azurerm_storage_account.receipts.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.campaign.principal_id
}

resource "azurerm_role_assignment" "verifier_receipt_reader" {
  scope                = azurerm_storage_account.receipts.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.verifier.principal_id
}

resource "azurerm_role_assignment" "verifier_sandbox_reader" {
  scope                = azurerm_resource_group.certification.id
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.verifier.principal_id
}

resource "azurerm_container_app_job" "migrate" {
  name                         = "job-invnet-migrate-${local.suffix}"
  location                     = azurerm_resource_group.certification.location
  resource_group_name          = azurerm_resource_group.certification.name
  container_app_environment_id = azurerm_container_app_environment.certification.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 900
  replica_retry_limit          = 0
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.campaign.id]
  }

  registry {
    server   = var.acr_login_server
    identity = azurerm_user_assigned_identity.campaign.id
  }

  secret {
    name  = "dsn"
    value = local.dsn
  }

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name    = "migrate"
      image   = var.core_image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["alembic"]
      args    = ["upgrade", "head"]

      env {
        name        = "FDAI_DATABASE_URL"
        secret_name = "dsn"
      }
    }
  }

  depends_on = [
    azurerm_postgresql_flexible_server_database.certification,
    azurerm_role_assignment.campaign_acr_pull,
  ]
}

resource "azurerm_container_app_job" "campaign" {
  name                         = "job-invnet-campaign-${local.suffix}"
  location                     = azurerm_resource_group.certification.location
  resource_group_name          = azurerm_resource_group.certification.name
  container_app_environment_id = azurerm_container_app_environment.certification.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 1800
  replica_retry_limit          = 0
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.campaign.id]
  }

  registry {
    server   = var.acr_login_server
    identity = azurerm_user_assigned_identity.campaign.id
  }

  secret {
    name  = "dsn"
    value = local.dsn
  }

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name    = "campaign"
      image   = var.core_image
      cpu     = 1.0
      memory  = "2Gi"
      command = ["python"]
      args    = ["-m", "fdai.delivery.inventory_network_certification_cli", "run"]

      env {
        name        = "FDAI_INVENTORY_DSN"
        secret_name = "dsn"
      }
      env {
        name  = "FDAI_INVENTORY_SCOPES"
        value = var.subscription_id
      }
      env {
        name  = "FDAI_INVENTORY_SOURCES"
        value = "arg,arm"
      }
      env {
        name  = "FDAI_INVENTORY_RESOURCE_TYPES"
        value = "resource-group"
      }
      env {
        name  = "FDAI_INVENTORY_RECOVERY_DELTA"
        value = "0"
      }
      env {
        name  = "FDAI_INVENTORY_RESOURCE_CHANGE_FEED"
        value = "0"
      }
      env {
        name  = "FDAI_INVENTORY_NETWORK_CERTIFICATION"
        value = "1"
      }
      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = azurerm_user_assigned_identity.campaign.client_id
      }
      env {
        name  = "AZURE_SUBSCRIPTION_ID"
        value = var.subscription_id
      }
      env {
        name  = "AZURE_TENANT_ID"
        value = var.tenant_id
      }
      env {
        name  = "FDAI_EXECUTION_VENUE"
        value = "deployed"
      }
      env {
        name  = "FDAI_NETWORK_CERT_SOURCE_REVISION"
        value = var.source_revision
      }
      env {
        name  = "FDAI_NETWORK_CERT_REQUEST_ID"
        value = var.request_id
      }
      env {
        name  = "FDAI_NETWORK_CERT_RECEIPT_URL"
        value = local.receipt_url
      }
    }
  }

  depends_on = [
    azurerm_private_endpoint.blob,
    azurerm_role_assignment.campaign_subscription_reader,
    azurerm_role_assignment.campaign_receipt_writer,
  ]
}

resource "azurerm_container_app_job" "verifier" {
  name                         = "job-invnet-verify-${local.suffix}"
  location                     = azurerm_resource_group.certification.location
  resource_group_name          = azurerm_resource_group.certification.name
  container_app_environment_id = azurerm_container_app_environment.certification.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 600
  replica_retry_limit          = 0
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.verifier.id]
  }

  registry {
    server   = var.acr_login_server
    identity = azurerm_user_assigned_identity.verifier.id
  }

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name    = "verifier"
      image   = var.core_image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python"]
      args    = ["-m", "fdai.delivery.inventory_network_certification_cli", "verify"]

      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = azurerm_user_assigned_identity.verifier.client_id
      }
      env {
        name  = "AZURE_SUBSCRIPTION_ID"
        value = var.subscription_id
      }
      env {
        name  = "AZURE_TENANT_ID"
        value = var.tenant_id
      }
      env {
        name  = "FDAI_EXECUTION_VENUE"
        value = "deployed"
      }
      env {
        name  = "FDAI_NETWORK_CERT_SOURCE_REVISION"
        value = var.source_revision
      }
      env {
        name  = "FDAI_NETWORK_CERT_REQUEST_ID"
        value = var.request_id
      }
      env {
        name  = "FDAI_NETWORK_CERT_RECEIPT_URL"
        value = local.receipt_url
      }
    }
  }

  depends_on = [
    azurerm_private_endpoint.blob,
    azurerm_role_assignment.verifier_receipt_reader,
    azurerm_role_assignment.verifier_sandbox_reader,
  ]
}

# Blob access diagnostics are emitted by the dedicated document_blob
# diagnostic setting below; Trivy does not correlate that child resource.
#trivy:ignore:AZU-0057
resource "azurerm_storage_account" "documents" {
  # checkov:skip=CKV_AZURE_35:The production private-networking gate makes default_action resolve to Deny.
  # checkov:skip=CKV_AZURE_59:The production private-networking gate disables public access.
  # checkov:skip=CKV_AZURE_43:The name variable enforces the Storage 3-24 lowercase alphanumeric contract.
  # checkov:skip=CKV_AZURE_33:The account exposes ADLS Gen2 filesystems only; no Queue service is consumed.
  # checkov:skip=CKV_AZURE_206:The validated replication input defaults to zone-redundant storage.
  # checkov:skip=CKV2_AZURE_33:The root creates the private endpoint whenever the production private-networking gate is active.
  # checkov:skip=CKV2_AZURE_1:Infrastructure encryption and platform-managed keys avoid a second key lifecycle for governed document storage.
  name                              = var.name
  resource_group_name               = var.resource_group_name
  location                          = var.location
  account_kind                      = "StorageV2"
  account_tier                      = "Standard"
  account_replication_type          = var.replication_type
  is_hns_enabled                    = true
  shared_access_key_enabled         = false
  local_user_enabled                = false
  public_network_access_enabled     = var.public_network_access_enabled
  allow_nested_items_to_be_public   = false
  min_tls_version                   = "TLS1_2"
  infrastructure_encryption_enabled = var.infrastructure_encryption_enabled
  cross_tenant_replication_enabled  = false

  blob_properties {
    versioning_enabled = false

    delete_retention_policy {
      days = var.soft_delete_retention_days
    }

    container_delete_retention_policy {
      days = var.container_delete_retention_days
    }

    dynamic "cors_rule" {
      for_each = length(var.cors_allowed_origins) == 0 ? [] : [1]
      content {
        allowed_origins    = var.cors_allowed_origins
        allowed_methods    = ["GET", "HEAD", "OPTIONS", "PUT"]
        allowed_headers    = ["authorization", "content-type", "x-ms-*"]
        exposed_headers    = ["etag", "x-ms-request-id", "x-ms-version"]
        max_age_in_seconds = 300
      }
    }
  }

  network_rules {
    default_action = var.public_network_access_enabled ? "Allow" : "Deny"
    bypass         = ["AzureServices"]

    dynamic "private_link_access" {
      for_each = var.private_link_access
      content {
        endpoint_resource_id = private_link_access.value.endpoint_resource_id
        endpoint_tenant_id   = private_link_access.value.endpoint_tenant_id
      }
    }
  }

  tags = var.tags
}

resource "azurerm_role_assignment" "deployer_data_owner" {
  scope                = azurerm_storage_account.documents.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = var.deployer_principal_id
}

resource "azurerm_monitor_diagnostic_setting" "document_blob" {
  name                       = "diag-${var.name}-blob"
  target_resource_id         = "${azurerm_storage_account.documents.id}/blobServices/default"
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category = "StorageRead"
  }

  enabled_log {
    category = "StorageWrite"
  }

  enabled_log {
    category = "StorageDelete"
  }
}

resource "azurerm_storage_data_lake_gen2_filesystem" "documents" {
  name               = var.source_file_system
  storage_account_id = azurerm_storage_account.documents.id

  depends_on = [azurerm_role_assignment.deployer_data_owner]
}

resource "azurerm_storage_data_lake_gen2_filesystem" "derived" {
  name               = var.derived_file_system
  storage_account_id = azurerm_storage_account.documents.id

  depends_on = [azurerm_role_assignment.deployer_data_owner]
}

resource "azurerm_storage_data_lake_gen2_path" "quarantine" {
  path               = "quarantine"
  filesystem_name    = azurerm_storage_data_lake_gen2_filesystem.documents.name
  storage_account_id = azurerm_storage_account.documents.id
  resource           = "directory"
}

resource "azurerm_storage_data_lake_gen2_path" "governed" {
  path               = "governed"
  filesystem_name    = azurerm_storage_data_lake_gen2_filesystem.documents.name
  storage_account_id = azurerm_storage_account.documents.id
  resource           = "directory"
}

resource "azurerm_storage_data_lake_gen2_path" "derived_documents" {
  path               = "documents"
  filesystem_name    = azurerm_storage_data_lake_gen2_filesystem.derived.name
  storage_account_id = azurerm_storage_account.documents.id
  resource           = "directory"
}

resource "azurerm_storage_management_policy" "documents" {
  storage_account_id = azurerm_storage_account.documents.id

  rule {
    name    = "expire-quarantine"
    enabled = true

    filters {
      prefix_match = ["${var.source_file_system}/quarantine/"]
      blob_types   = ["blockBlob"]
    }

    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = var.quarantine_retention_days
      }
    }
  }

  rule {
    name    = "tier-derived"
    enabled = true

    filters {
      prefix_match = ["${var.derived_file_system}/documents/"]
      blob_types   = ["blockBlob"]
    }

    actions {
      base_blob {
        tier_to_cool_after_days_since_modification_greater_than = var.derived_cool_after_days
      }
    }
  }
}

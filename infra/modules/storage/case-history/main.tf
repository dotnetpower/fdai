resource "azurerm_storage_account" "case_history" {
  name                              = var.name
  resource_group_name               = var.resource_group_name
  location                          = var.location
  account_kind                      = "StorageV2"
  account_tier                      = "Standard"
  account_replication_type          = var.replication_type
  is_hns_enabled                    = false
  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  public_network_access_enabled     = var.public_network_access_enabled
  allow_nested_items_to_be_public   = false
  min_tls_version                   = "TLS1_2"
  infrastructure_encryption_enabled = true
  cross_tenant_replication_enabled  = false

  blob_properties {
    versioning_enabled  = true
    change_feed_enabled = true

    delete_retention_policy {
      days = var.soft_delete_retention_days
    }

    container_delete_retention_policy {
      days = var.soft_delete_retention_days
    }
  }

  network_rules {
    default_action = var.public_network_access_enabled ? "Allow" : "Deny"
    bypass         = ["None"]

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
  scope                = azurerm_storage_account.case_history.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = var.deployer_principal_id
}

resource "azurerm_role_assignment" "runtime_data_contributor" {
  scope                = azurerm_storage_account.case_history.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = var.runtime_principal_id
}

resource "azurerm_storage_container" "case_history" {
  name                  = var.container_name
  storage_account_id    = azurerm_storage_account.case_history.id
  container_access_type = "private"

  depends_on = [azurerm_role_assignment.deployer_data_owner]
}

resource "azurerm_storage_management_policy" "case_history" {
  storage_account_id = azurerm_storage_account.case_history.id

  rule {
    name    = "expire-superseded-case-versions"
    enabled = true

    filters {
      prefix_match = ["${var.container_name}/case-history/"]
      blob_types   = ["blockBlob"]
    }

    actions {
      version {
        delete_after_days_since_creation = var.version_retention_days
      }
    }
  }
}

resource "azurerm_key_vault" "primary" {
  name                            = var.name
  location                        = var.location
  resource_group_name             = var.resource_group_name
  tenant_id                       = var.tenant_id
  sku_name                        = "standard"
  enabled_for_deployment          = false
  enabled_for_disk_encryption     = false
  enabled_for_template_deployment = false
  rbac_authorization_enabled      = true
  purge_protection_enabled        = false
  soft_delete_retention_days      = 7
  tags                            = var.tags
}

# Grant the executor MI runtime read access to secrets.
resource "azurerm_role_assignment" "executor_secrets_user" {
  count                = var.grant_executor_role ? 1 : 0
  scope                = azurerm_key_vault.primary.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = var.executor_principal_id
}


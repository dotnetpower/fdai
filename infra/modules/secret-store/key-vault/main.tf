# The module retains a public dev path for disposable environments. Production
# is not exempt: infra/production-gates.tf requires private networking, which
# sets public access off and default_action to Deny.
# FDAI's reviewed teardown profile requires a purgeable seven-day vault so a
# destroyed globally named environment can be recreated immediately.
#trivy:ignore:AZU-0013
#trivy:ignore:AZU-0016
resource "azurerm_key_vault" "primary" {
  # checkov:skip=CKV_AZURE_189:The production gate disables public access; the module retains a conditional day-zero path.
  # checkov:skip=CKV_AZURE_109:network_acls explicitly bind the reviewed bypass, default action, IP rules, and subnet rules.
  # checkov:skip=CKV_AZURE_42:Soft delete remains enabled by Azure and the provider recovers soft-deleted vaults on create.
  # checkov:skip=CKV_AZURE_110:The documented teardown profile intentionally requires purge protection off with seven-day soft delete.
  # checkov:skip=CKV2_AZURE_32:The root creates and links the Key Vault private endpoint whenever the production private-networking gate is active.
  name                            = var.name
  location                        = var.location
  resource_group_name             = var.resource_group_name
  tenant_id                       = var.tenant_id
  sku_name                        = "standard"
  enabled_for_deployment          = false
  enabled_for_disk_encryption     = false
  enabled_for_template_deployment = false
  rbac_authorization_enabled      = true
  purge_protection_enabled        = var.purge_protection_enabled
  soft_delete_retention_days      = var.soft_delete_retention_days
  # Explicit rather than provider-default so posture is diff-visible.
  public_network_access_enabled = var.public_network_access_enabled

  # Restrict to Azure Services + a caller-supplied IP allowlist.
  # `bypass = "AzureServices"` lets Container Apps + the terraform-running
  # principal reach KV without needing a private endpoint on day zero.
  # Adding entries to `network_acls_ip_rules` narrows further; the empty
  # default keeps the deploy CI-runnable from any location.
  network_acls {
    bypass                     = "AzureServices"
    default_action             = var.network_acls_default_action
    ip_rules                   = var.network_acls_ip_rules
    virtual_network_subnet_ids = var.network_acls_subnet_ids
  }

  tags = var.tags
}

# Grant the executor MI runtime read access to secrets.
resource "azurerm_role_assignment" "executor_secrets_user" {
  count                = var.grant_executor_role ? 1 : 0
  scope                = azurerm_key_vault.primary.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = var.executor_principal_id
}

resource "random_id" "cost_pseudonym_key" {
  count       = 1
  byte_length = 32
}

resource "azurerm_key_vault_secret" "cost_pseudonym_key" {
  # checkov:skip=CKV_AZURE_41:Pseudonyms remain stable; rotation requires a coordinated projection revision.
  count        = 1
  name         = "fdai-cost-pseudonym-key"
  value        = sensitive(random_id.cost_pseudonym_key[0].hex)
  key_vault_id = var.key_vault_id
  content_type = "cost-pseudonym-key-hex"
  tags         = var.tags
}

resource "azurerm_role_assignment" "operator_cost_pseudonym_secret_reader" {
  count                = 1
  scope                = azurerm_key_vault_secret.cost_pseudonym_key[0].resource_versionless_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = var.operator_principal_id
}

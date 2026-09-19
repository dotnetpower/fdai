output "cost_pseudonym_key_secret_id" {
  description = "Versioned Key Vault secret id for the Operator service plan."
  value       = azurerm_key_vault_secret.cost_pseudonym_key[0].id
  sensitive   = true
}

mock_provider "azurerm" {}

variables {
  name                  = "oai-fdai-dev-krc"
  location              = "koreacentral"
  resource_group_name   = "rg-fdai-dev-krc"
  grant_executor_role   = false
  resolved_capabilities = []
}

run "private_access_is_the_default" {
  command = plan

  assert {
    condition     = azurerm_cognitive_account.primary.public_network_access_enabled == false
    error_message = "Azure OpenAI public network access must remain disabled by default."
  }
}

run "explicit_public_access_is_preserved" {
  command = plan

  variables {
    public_network_access_enabled = true
  }

  assert {
    condition     = azurerm_cognitive_account.primary.public_network_access_enabled == true
    error_message = "An explicit Azure OpenAI public network opt-in must reach the account."
  }

  assert {
    condition     = azurerm_cognitive_account.primary.local_auth_enabled == false
    error_message = "Public network access must not enable local key authentication."
  }
}

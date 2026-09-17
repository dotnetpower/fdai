mock_provider "azurerm" {}

variables {
  account_name        = "aif-fdai-partner-dev-krc"
  project_name        = "proj-fdai-partner-dev-krc"
  location            = "koreacentral"
  resource_group_name = "rg-fdai-dev-krc"
  deployments = [{
    name         = "t2.reasoner.secondary"
    publisher    = "Cohere"
    family       = "cohere-command-a"
    version      = "1"
    sku          = "GlobalStandard"
    capacity_tpm = 10000
  }]
  user_principal_ids = {
    executor = "00000000-0000-0000-0000-000000000001"
  }
}

run "plans_private_partner_model" {
  command = plan

  assert {
    condition     = azurerm_cognitive_account.partner.kind == "AIServices"
    error_message = "Partner models must use an AIServices account."
  }

  assert {
    condition     = azurerm_cognitive_account.partner.public_network_access_enabled == false
    error_message = "Private deployments must disable public account access."
  }

  assert {
    condition     = azurerm_cognitive_deployment.capability["t2.reasoner.secondary"].model[0].format == "Cohere"
    error_message = "Cohere must map to the Azure Cohere model format."
  }

  assert {
    condition     = azurerm_cognitive_deployment.capability["t2.reasoner.secondary"].model[0].version == "1"
    error_message = "Partner model versions must remain pinned."
  }

  assert {
    condition     = azurerm_role_assignment.project_user["executor"].role_definition_name == "Azure AI Developer"
    error_message = "Runtime principals must receive the current Foundry project developer role."
  }
}

run "allows_explicit_public_development_access" {
  command = plan

  variables {
    public_network_access_enabled = true
  }

  assert {
    condition     = azurerm_cognitive_account.partner.public_network_access_enabled == true
    error_message = "The explicit public development profile must reach its deployment-owned Foundry account."
  }

  assert {
    condition     = azurerm_cognitive_account.partner.local_auth_enabled == false
    error_message = "Public network access must not enable local-key authentication."
  }
}

mock_provider "azurerm" {}

variables {
  account_name        = "aif-fdai-partner-dev-krc"
  project_name        = "proj-fdai-partner-dev-krc"
  location            = "koreacentral"
  resource_group_name = "rg-fdai-dev-krc"
  deployments = [{
    name         = "t2.reasoner.secondary"
    publisher    = "MistralAI"
    family       = "Mistral-Large-3"
    version      = "1"
    sku          = "GlobalStandard"
    capacity_tpm = 1000
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
    condition     = azurerm_cognitive_deployment.capability["t2.reasoner.secondary"].model[0].format == "Mistral AI"
    error_message = "MistralAI must map to the Azure Mistral AI model format."
  }

  assert {
    condition     = azurerm_cognitive_deployment.capability["t2.reasoner.secondary"].model[0].version == "1"
    error_message = "Partner model versions must remain pinned."
  }

  assert {
    condition     = azurerm_role_assignment.project_user["executor"].role_definition_name == "Azure AI User"
    error_message = "Runtime principals must receive only the project user role."
  }
}

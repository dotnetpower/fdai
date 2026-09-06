resource "azurerm_role_definition" "dev_gateway_model_deployment" {
  count = var.enable_dev_operations_gateway && var.enable_llm ? 1 : 0

  name = "FDAI Model Deployment Operator ${substr(
    sha256(lower(module.llm_azure_openai[0].resource_id)),
    0,
    8,
  )}"
  scope       = module.llm_azure_openai[0].resource_id
  description = "Create, read, and remove governed model deployments on one FDAI Azure AI account."

  permissions {
    actions = [
      "Microsoft.CognitiveServices/accounts/deployments/read",
      "Microsoft.CognitiveServices/accounts/deployments/write",
      "Microsoft.CognitiveServices/accounts/deployments/delete",
    ]
    not_actions = []
  }

  assignable_scopes = [module.llm_azure_openai[0].resource_id]
}

resource "azurerm_role_assignment" "dev_gateway_model_deployment" {
  count = var.enable_dev_operations_gateway && var.enable_llm ? 1 : 0

  scope              = module.llm_azure_openai[0].resource_id
  role_definition_id = azurerm_role_definition.dev_gateway_model_deployment[0].role_definition_resource_id
  principal_id       = module.dev_gateway_executor_identity[0].principal_id
  principal_type     = "ServicePrincipal"
}

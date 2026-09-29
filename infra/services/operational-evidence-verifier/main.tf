resource "terraform_data" "verifier_separation_contract" {
  input = var.identity.principal_id

  lifecycle {
    precondition {
      condition = !contains([
        var.executor_anchors.core_runtime_executor,
        var.executor_anchors.isolated_executor,
        var.executor_anchors.dev_operations_gateway_executor,
        var.executor_anchors.deploy_runner,
      ], var.identity.principal_id) && !contains(tolist(var.executor_anchors.vertical_effect_executors), var.identity.principal_id)
      error_message = "Verifier identity principal must differ from every executor-class principal."
    }
  }
}

resource "azurerm_role_assignment" "verifier_role_readback_reader" {
  for_each             = var.own_role_readback.scopes
  scope                = each.value
  role_definition_name = "Reader"
  principal_id         = var.identity.principal_id
}

resource "azurerm_role_assignment" "verifier_acr_pull" {
  scope                = var.platform.acr_resource_id
  role_definition_name = "AcrPull"
  principal_id         = var.identity.principal_id
}

resource "azurerm_role_assignment" "verifier_database_secret_reader" {
  scope                = var.database.dsn_secret_scope
  role_definition_name = "Key Vault Secrets User"
  principal_id         = var.identity.principal_id
}

module "verifier" {
  source = "./modules/operational-evidence-verifier"

  name              = var.name
  platform          = var.platform
  image             = var.image
  identity          = var.identity
  database          = var.database
  registries        = var.registries
  anchors_json      = var.anchors_json
  executor_anchors  = var.executor_anchors
  caller_auth       = var.caller_auth
  own_role_readback = var.own_role_readback
  health            = var.health
  runtime_env       = var.runtime_env
  scaling           = var.scaling
  tags              = var.tags

  depends_on = [
    terraform_data.verifier_separation_contract,
    azurerm_role_assignment.verifier_acr_pull,
    azurerm_role_assignment.verifier_database_secret_reader,
    azurerm_role_assignment.verifier_role_readback_reader,
  ]
}

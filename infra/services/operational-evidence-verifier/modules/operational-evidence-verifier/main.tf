locals {
  env = [
    { name = "FDAI_EXECUTION_VENUE", value = "deployed" },
    { name = "RUNTIME_ENV", value = var.runtime_env },
    { name = "FDAI_MI_CLIENT_ID", value = var.identity.client_id },
    { name = "AZURE_CLIENT_ID", value = var.identity.client_id },
    { name = "POSTGRES_HOST", value = var.database.host },
    { name = "FDAI_DATABASE_ROLE", value = var.database.role },
    { name = "PGOPTIONS", value = "-c role=${var.database.role}" },
    { name = "FDAI_OPERATIONAL_EVIDENCE_ENABLED", value = "1" },
    { name = "FDAI_OPERATIONAL_EVIDENCE_TRUST_REGISTRY_PATH", value = var.registries.trust_path },
    { name = "FDAI_OPERATIONAL_EVIDENCE_TRUST_REGISTRY_PIN", value = var.registries.trust_pin },
    { name = "FDAI_OPERATIONAL_EVIDENCE_GRANT_REGISTRY_PATH", value = var.registries.grant_path },
    { name = "FDAI_OPERATIONAL_EVIDENCE_GRANT_REGISTRY_PIN", value = var.registries.grant_pin },
    { name = "FDAI_OPERATIONAL_EVIDENCE_ANCHORS_JSON", value = var.anchors_json },
    { name = "FDAI_OPERATIONAL_EVIDENCE_CORE_EXECUTOR_PRINCIPAL_ID", value = var.executor_anchors.core_runtime_executor },
    { name = "FDAI_OPERATIONAL_EVIDENCE_ISOLATED_EXECUTOR_PRINCIPAL_ID", value = var.executor_anchors.isolated_executor },
    { name = "FDAI_OPERATIONAL_EVIDENCE_DEV_GATEWAY_EXECUTOR_PRINCIPAL_ID", value = var.executor_anchors.dev_operations_gateway_executor },
    { name = "FDAI_OPERATIONAL_EVIDENCE_VERTICAL_EXECUTOR_PRINCIPALS_JSON", value = jsonencode(sort(tolist(var.executor_anchors.vertical_effect_executors))) },
    { name = "FDAI_OPERATIONAL_EVIDENCE_DEPLOY_RUNNER_PRINCIPAL_ID", value = var.executor_anchors.deploy_runner },
    { name = "FDAI_OPERATIONAL_EVIDENCE_CALLER_TOKEN_ISSUER", value = var.caller_auth.issuer },
    { name = "FDAI_OPERATIONAL_EVIDENCE_CALLER_TOKEN_AUDIENCE", value = var.caller_auth.audience },
    { name = "FDAI_OPERATIONAL_EVIDENCE_CALLER_TOKEN_JWKS_JSON", value = var.caller_auth.jwks_json },
    { name = "FDAI_OPERATIONAL_EVIDENCE_ROLE_READBACK_SCOPES_JSON", value = jsonencode(sort(tolist(var.own_role_readback.scopes))) },
    { name = "FDAI_OPERATIONAL_EVIDENCE_ALLOWED_ROLE_SCOPES_JSON", value = jsonencode({
      AcrPull                  = [var.platform.acr_resource_id]
      "Key Vault Secrets User" = [var.database.dsn_secret_scope]
      "Monitoring Reader"      = sort(tolist(var.own_role_readback.scopes))
      Reader                   = sort(tolist(var.own_role_readback.scopes))
    }) },
    { name = "FDAI_OPERATIONAL_EVIDENCE_VERIFIER_URL", value = "http://127.0.0.1:${var.health.port}" },
    { name = "FDAI_OPERATIONAL_EVIDENCE_READER_ROLE", value = "fdai_core" },
    { name = "FDAI_OPERATIONAL_EVIDENCE_VERIFIER_DSN", secret_name = "verifier-dsn" },
  ]
}

resource "terraform_data" "separation_contract" {
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

module "container_app" {
  source = "../../../_modules/container-app"

  name                 = var.name
  platform             = var.platform
  image                = var.image
  identity_ids         = [var.identity.resource_id]
  registry_identity_id = var.identity.resource_id
  command              = ["python", "-m", "fdai.delivery.operational_evidence_server"]
  args                 = ["--host", "0.0.0.0", "--port", tostring(var.health.port)]
  secrets = [{
    name                = "verifier-dsn"
    identity            = var.identity.resource_id
    key_vault_secret_id = var.database.dsn_secret_id
  }]
  environment       = local.env
  health            = var.health
  ingress           = { external_enabled = false, target_port = var.health.port }
  scaling           = var.scaling
  component         = "operational-evidence-verifier"
  rollback_strategy = "previous-revision"
  tags              = var.tags
  depends_on        = [terraform_data.separation_contract]
}

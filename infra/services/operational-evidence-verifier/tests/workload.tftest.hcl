mock_provider "azurerm" {}

variables {
  name  = "ca-fdai-evidence-verifier"
  image = "registry.example.com/fdai/core@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  platform = {
    resource_group_name          = "example"
    container_app_environment_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.App/managedEnvironments/example"
    acr_login_server             = "registry.example.com"
    acr_resource_id              = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.ContainerRegistry/registries/example"
  }
  identity = {
    resource_id  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/evidence-verifier"
    client_id    = "00000000-0000-0000-0000-000000000001"
    principal_id = "verifier-principal"
  }
  database = {
    dsn_secret_id    = "https://vault.example.com/secrets/verifier-dsn"
    dsn_secret_scope = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.KeyVault/vaults/example/secrets/verifier-dsn"
    host             = "database.example.com"
    role             = "fdai_operational_evidence_verifier"
  }
  registries = {
    trust_path = "config/operational-evidence-trust-registry.json"
    trust_pin  = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    grant_path = "/app/config/operational-evidence-grants.json"
    grant_pin  = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
  anchors_json = jsonencode({ schema_version = "1.0.0", venue = "deployed", anchors = [] })
  executor_anchors = {
    core_runtime_executor           = "core-executor"
    isolated_executor               = "isolated-executor"
    dev_operations_gateway_executor = "devgw-executor"
    vertical_effect_executors       = ["change-executor", "resilience-executor", "finops-executor"]
    deploy_runner                   = "deploy-runner"
  }
  caller_auth = {
    issuer    = "https://login.example.com/tenant/v2.0"
    audience  = "api://operational-evidence-verifier"
    jwks_json = jsonencode({ keys = [] })
  }
  own_role_readback = {
    scopes = ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example"]
  }
  runtime_env = "dev"
}

run "verifier_workload_is_internal_and_separated" {
  command = plan

  assert {
    condition = (
      output.identity_principal_id == "verifier-principal" &&
      output.service.name == "ca-fdai-evidence-verifier"
    )
    error_message = "The service must expose the dedicated verifier identity and workload name."
  }

  assert {
    condition = (
      output.internal_ingress.external_enabled == false &&
      output.internal_ingress.target_port == 8791
    )
    error_message = "The verifier must expose only internal ingress on its readiness and issuance port."
  }

  assert {
    condition = (
      length(azurerm_role_assignment.verifier_role_readback_reader) == 1 &&
      azurerm_role_assignment.verifier_acr_pull.role_definition_name == "AcrPull" &&
      azurerm_role_assignment.verifier_acr_pull.scope == var.platform.acr_resource_id &&
      azurerm_role_assignment.verifier_database_secret_reader.role_definition_name == "Key Vault Secrets User" &&
      azurerm_role_assignment.verifier_database_secret_reader.scope == var.database.dsn_secret_scope &&
      one(values(azurerm_role_assignment.verifier_role_readback_reader)).role_definition_name == "Reader"
    )
    error_message = "Terraform must grant only the own-role readback role in this service root."
  }
}

run "reject_verifier_equal_to_executor" {
  command = plan
  variables {
    identity = {
      resource_id  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/evidence-verifier"
      client_id    = "00000000-0000-0000-0000-000000000001"
      principal_id = "core-executor"
    }
  }
  expect_failures = [terraform_data.verifier_separation_contract]
}

run "reject_duplicate_executor_anchor" {
  command = plan
  variables {
    executor_anchors = {
      core_runtime_executor           = "core-executor"
      isolated_executor               = "core-executor"
      dev_operations_gateway_executor = "devgw-executor"
      vertical_effect_executors       = ["change-executor"]
      deploy_runner                   = "deploy-runner"
    }
  }
  expect_failures = [var.executor_anchors]
}

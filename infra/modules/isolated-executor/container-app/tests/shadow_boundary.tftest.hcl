mock_provider "azurerm" {}

run "shadow_only_internal_app" {
  command = plan

  variables {
    name                         = "ca-fdai-example-executor"
    container_app_environment_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.App/managedEnvironments/cae-example"
    resource_group_name          = "rg-example"
    image                        = "example.azurecr.io/fdai@sha256:example"
    identity_id                  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-example-executor-shadow"
    identity_client_id           = "shadow-client-id"
    state_store_dsn_secret_id    = "https://example.vault.azure.net/secrets/state-store"
    kafka_bootstrap_servers      = "example.servicebus.windows.net:9093"
    runtime_env                  = "dev"
    acr_login_server             = "example.azurecr.io"
  }

  assert {
    condition     = azurerm_container_app.shadow.identity[0].identity_ids == toset([var.identity_id])
    error_message = "the shadow app must attach only its dedicated transport identity"
  }

  assert {
    condition     = length(azurerm_container_app.shadow.ingress) == 0
    error_message = "the isolated Executor must expose no Container Apps ingress"
  }

  assert {
    condition = one([
      for secret in azurerm_container_app.shadow.secret : secret.identity
      if secret.name == "state-store-dsn"
    ]) == var.identity_id
    error_message = "the dedicated shadow identity must resolve the state-store secret"
  }

  assert {
    condition = (
      length(azurerm_container_app.shadow.template[0].container[0].command) == 1 &&
      one(azurerm_container_app.shadow.template[0].container[0].command) == "fdai-isolated-executor"
    )
    error_message = "the app must run the isolated shadow entry point"
  }

  assert {
    condition = {
      for env in azurerm_container_app.shadow.template[0].container[0].env :
      env.name => try(env.value, env.secret_name)
    }["FDAI_ISOLATED_EXECUTOR_DEPLOYED"] == "1"
    error_message = "the deployed-process marker must be explicit"
  }

  assert {
    condition = !contains(
      toset([
        for env in azurerm_container_app.shadow.template[0].container[0].env : env.name
      ]),
      "FDAI_MI_CLIENT_ID",
    )
    error_message = "the shadow app must not receive the privileged executor identity env"
  }

  assert {
    condition = {
      for env in azurerm_container_app.shadow.template[0].container[0].env :
      env.name => env.secret_name if env.secret_name != null
    }["FDAI_STATE_STORE_DSN"] == "state-store-dsn"
    error_message = "durable state must come from the Key Vault-backed secret"
  }

  assert {
    condition = (
      azurerm_container_app.shadow.template[0].container[0].liveness_probe[0].path == "/live" &&
      azurerm_container_app.shadow.template[0].container[0].readiness_probe[0].path == "/ready"
    )
    error_message = "the internal app must expose independent liveness and readiness probes"
  }
}

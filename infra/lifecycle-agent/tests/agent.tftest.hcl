mock_provider "azurerm" {}
mock_provider "azuread" {
  mock_data "azuread_service_principal" {
    defaults = {
      object_id = "00000000-0000-0000-0000-000000000000"
    }
  }
}
mock_provider "kubernetes" {}

variables {
  subscription_id         = "00000000-0000-0000-0000-000000000000"
  tenant_id               = "00000000-0000-0000-0000-000000000000"
  location                = "westus3"
  resource_group_name     = "rg-example-dev-wus3"
  prefix                  = "example"
  tags                    = { environment = "test" }
  kubeconfig_path         = "/private/kubeconfig"
  kubeconfig_context      = "example"
  cluster_oidc_issuer_url = "https://oidc.example.com/"
  hub = {
    url             = "https://hub.example.com"
    api_client_id   = "00000000-0000-0000-0000-000000000000"
    agent_role_id   = "00000000-0000-0000-0000-000000000000"
    signing_key_id  = "hub-example"
    signing_epoch   = 1
    public_key_pem  = "public hub key"
    release_key_pem = "public release key"
    config_key_pem  = "public configuration key"
  }
  installation = {
    id                   = "installation-alpha"
    target_namespace     = "fdai-system"
    fencing_generation   = 1
    local_policy_json    = "{\"schema\":\"fdai.lifecycle-local-policy.v1\"}"
    current_state_json   = "{\"digest\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}"
    poll_interval_seconds = 5
  }
  agent_image = "registry.example.com/fdai-lifecycle-agent@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}

run "prepare_without_starting_agent" {
  command = plan

  assert {
    condition = (
      length(kubernetes_deployment_v1.agent) == 0 &&
      output.deployment.enabled == false &&
      output.deployment.agent_namespace == "fdai-agent-system" &&
      output.deployment.target_namespace == "fdai-system"
    )
    error_message = "Preparation must create bounded prerequisites without starting the Agent."
  }
}

run "enable_single_writer_agent" {
  command = plan
  variables {
    enable_agent = true
  }

  assert {
    condition = (
      length(kubernetes_deployment_v1.agent) == 1 &&
      kubernetes_deployment_v1.agent[0].spec[0].replicas == "1" &&
      kubernetes_deployment_v1.agent[0].spec[0].strategy[0].type == "Recreate" &&
      output.deployment.enabled == true
    )
    error_message = "Enabled deployment must keep one Recreate Agent writer."
  }
}

run "mutable_agent_image_is_rejected" {
  command = plan
  variables {
    agent_image = "registry.example.com/fdai-lifecycle-agent:latest"
  }
  expect_failures = [var.agent_image]
}

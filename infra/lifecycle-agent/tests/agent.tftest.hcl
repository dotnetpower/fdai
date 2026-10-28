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
    id                          = "installation-alpha"
    target_namespace            = "fdai-system"
    fencing_generation          = 1
    local_policy_json           = "{\"schema\":\"fdai.lifecycle-local-policy.v1\"}"
    current_state_json          = "{\"digest\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}"
    native_approval_json        = "{}"
    native_state_json           = "{}"
    installation_public_key_pem = "public installation key"
    poll_interval_seconds       = 5
  }
  agent_image = "registry.example.com/fdai-lifecycle-agent@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}

run "prepare_without_starting_agent" {
  command = plan

  assert {
    condition = (
      length(kubernetes_deployment_v1.agent) == 0 &&
      length(kubernetes_job_v1.initialize) == 0 &&
      output.deployment.enabled == false &&
      output.deployment.agent_namespace == "fdai-agent-system" &&
      output.deployment.target_namespace == "fdai-system" &&
      kubernetes_persistent_volume_claim_v1.state.wait_until_bound == false
    )
    error_message = "Preparation must not wait for a consumer-bound volume before starting the Agent."
  }

  assert {
    condition = (
      length(kubernetes_role_v1.workloads.rule) == 3 &&
      length([for rule in kubernetes_role_v1.workloads.rule : rule if contains(rule.verbs, "list")]) == 1 &&
      length([for rule in kubernetes_role_v1.workloads.rule : rule if contains(rule.verbs, "list") && length(rule.verbs) == 1]) == 1 &&
      !anytrue([for rule in kubernetes_role_v1.workloads.rule : contains(rule.resources, "secrets")])
    )
    error_message = "Enrollment discovery needs only namespace-scoped list on Deployments and CronJobs and never Secrets."
  }
}

run "state_volume_uses_zone_redundant_storage" {
  command = plan

  assert {
    condition = (
      length(kubernetes_storage_class_v1.state) == 1 &&
      kubernetes_storage_class_v1.state[0].parameters.skuName == "StandardSSD_ZRS" &&
      kubernetes_storage_class_v1.state[0].volume_binding_mode == "WaitForFirstConsumer" &&
      kubernetes_persistent_volume_claim_v1.state.spec[0].storage_class_name == "fdai-lifecycle-agent-state"
    )
    error_message = "The Agent state volume must use a zone-redundant disk class by default."
  }
}

run "existing_storage_class_is_not_replaced" {
  command = plan
  variables {
    storage_class_name = "managed-csi-premium"
  }

  assert {
    condition = (
      length(kubernetes_storage_class_v1.state) == 0 &&
      kubernetes_persistent_volume_claim_v1.state.spec[0].storage_class_name == "managed-csi-premium"
    )
    error_message = "An explicit StorageClass must be used as is."
  }
}

run "locally_redundant_disk_sku_is_rejected" {
  command = plan
  variables {
    storage_sku = "Standard_LRS"
  }
  expect_failures = [var.storage_sku]
}

run "enable_single_writer_agent" {
  command = plan
  variables {
    enable_agent = true
  }

  assert {
    condition = (
      length(kubernetes_deployment_v1.agent) == 1 &&
      length(kubernetes_job_v1.initialize) == 1 &&
      kubernetes_job_v1.initialize[0].wait_for_completion == true &&
      can(regex(
        "^[0-9a-f]{64}$",
        kubernetes_job_v1.initialize[0].spec[0].template[0].metadata[0].annotations["fdai.io/input-digest"],
      )) &&
      kubernetes_deployment_v1.agent[0].spec[0].replicas == "1" &&
      kubernetes_deployment_v1.agent[0].spec[0].strategy[0].type == "Recreate" &&
      kubernetes_deployment_v1.agent[0].spec[0].template[0].spec[0].security_context[0].fs_group_change_policy == "OnRootMismatch" &&
      contains(
        kubernetes_job_v1.initialize[0].spec[0].template[0].spec[0].container[0].volume_mount[*].name,
        "private-inputs",
      ) &&
      contains(
        kubernetes_deployment_v1.agent[0].spec[0].template[0].spec[0].container[0].args,
        "/config/private/local-policy.json",
      ) &&
      contains(
        kubernetes_deployment_v1.agent[0].spec[0].template[0].spec[0].container[0].volume_mount[*].sub_path,
        "agent/private/local-policy.json",
      ) &&
      strcontains(
        kubernetes_job_v1.initialize[0].spec[0].template[0].spec[0].container[0].args[0],
        "p.is_dir() and p.rmdir()",
      ) &&
      strcontains(
        kubernetes_job_v1.initialize[0].spec[0].template[0].spec[0].container[0].args[0],
        "state=Path('/state/agent')",
      ) &&
      contains(
        kubernetes_deployment_v1.agent[0].spec[0].template[0].spec[0].container[0].args,
        "/agent-state",
      ) &&
      contains(
        kubernetes_deployment_v1.agent[0].spec[0].template[0].spec[0].container[0].volume_mount[*].sub_path,
        "agent",
      ) &&
      !contains(
        kubernetes_deployment_v1.agent[0].spec[0].template[0].spec[0].container[0].volume_mount[*].name,
        "private-inputs",
      ) &&
      output.deployment.enabled == true
    )
    error_message = "Enabled Agent must consume owner-only private state, not the Secret volume."
  }
}

run "binary_configuration_signature_is_accepted" {
  command = plan
  variables {
    installation = {
      id                 = "installation-alpha"
      target_namespace   = "fdai-system"
      fencing_generation = 1
      local_policy_json  = "{\"schema\":\"fdai.lifecycle-local-policy.v1\"}"
      current_state_json = "{\"digest\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}"
      configuration_artifact = {
        digest           = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        payload          = "{}"
        signature_base64 = "gIGCg4SFhoeIiYqLjI2Oj5CRkpOUlZaXmJmam5ydnp+goaKjpKWmp6ipqqusra6vsLGys7S1tre4ubq7vL2+vw=="
      }
      poll_interval_seconds = 5
    }
  }

  assert {
    condition = (
      kubernetes_secret_v1.private_inputs.binary_data["configuration.sig"] ==
      "gIGCg4SFhoeIiYqLjI2Oj5CRkpOUlZaXmJmam5ydnp+goaKjpKWmp6ipqqusra6vsLGys7S1tre4ubq7vL2+vw=="
    )
    error_message = "Arbitrary binary Ed25519 signatures must remain Base64 through Terraform."
  }
}

run "mutable_agent_image_is_rejected" {
  command = plan
  variables {
    agent_image = "registry.example.com/fdai-lifecycle-agent:latest"
  }
  expect_failures = [var.agent_image]
}

mock_provider "azurerm" {}
mock_provider "kubernetes" {}

variables {
  kubeconfig_path = "/unused/mock-kubeconfig"
  tenant_id       = "00000000-0000-0000-0000-000000000000"
  oidc_issuer_url = "https://example.com/oidc/"
  key_vault_name  = "example"
  workloads = {
    example = {
      component            = "core"
      image                = "example.com/fdai/core@sha256:0000000000000000000000000000000000000000000000000000000000000000"
      identity_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/example"
      identity_client_id   = "00000000-0000-0000-0000-000000000001"
      command              = ["python", "-m", "example"]
      replicas             = 2
      max_replicas         = 3
      cpu                  = "500m"
      memory               = "1Gi"
      port                 = 8010
      readiness_path       = "/ready"
      liveness_path        = "/health"
      environment          = {}
    }
  }
}

run "workload_security_baseline" {
  command = plan

  assert {
    condition = (
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[0].image == var.workloads.example.image &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[0].image_pull_policy == "Always" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[0].security_context[0].read_only_root_filesystem &&
      !kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[0].security_context[0].allow_privilege_escalation
    )
    error_message = "Workloads must preserve the approved digest and run without a writable root or privilege escalation."
  }

  assert {
    condition = (
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[0].volume_mount[0].mount_path == "/tmp" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[0].volume_mount[0].name == "tmp" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].volume[0].name == "tmp" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].volume[0].empty_dir[0].size_limit == "1Gi"
    )
    error_message = "Writable scratch space must remain a bounded temporary volume."
  }
}

run "reject_mutable_image" {
  command = plan

  variables {
    workloads = {
      example = merge(var.workloads.example, { image = "example.com/fdai/core:latest" })
    }
  }

  expect_failures = [var.workloads]
}

run "reject_malformed_digest" {
  command = plan

  variables {
    workloads = {
      example = merge(var.workloads.example, { image = "example.com/fdai/core@sha256:invalid" })
    }
  }

  expect_failures = [var.workloads]
}

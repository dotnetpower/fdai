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
      source_commit        = "0000000000000000000000000000000000000000"
      image                = "example.com/fdai/core@sha256:0000000000000000000000000000000000000000000000000000000000000000"
      identity_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/example"
      identity_client_id   = "00000000-0000-0000-0000-000000000001"
      command              = ["python", "-m", "example"]
      replicas             = 2
      max_replicas         = 3
      cpu                  = "500m"
      memory               = "1Gi"
      port                 = 8010
      service_port         = 80
      readiness_path       = "/ready"
      liveness_path        = "/health"
      fs_group             = 101
      environment          = {}
      sidecars = {
        clamav = {
          image        = "example.com/fdai/clamav@sha256:0000000000000000000000000000000000000000000000000000000000000000"
          cpu          = "500m"
          memory       = "1Gi"
          port         = 3310
          run_as_user  = 100
          run_as_group = 101
          init = {
            name              = "clamav-database"
            command           = ["/bin/sh", "-c"]
            args              = ["cp -a /var/lib/clamav/. /target/"]
            image_pull_policy = "IfNotPresent"
            run_as_user       = 100
            run_as_group      = 101
            writable_path     = "database"
            mount_path        = "/target"
          }
          writable_paths = {
            database = { mount_path = "/var/lib/clamav", size_limit = "1Gi" }
          }
        }
      }
    }
  }
}

run "workload_security_baseline" {
  command = plan

  assert {
    condition = (
      length(kubernetes_role_v1.executor_external_scale) == 0 &&
      length(kubernetes_role_binding_v1.executor_external_scale) == 0
    )
    error_message = "External scale permissions must remain absent without explicit target selection."
  }

  assert {
    condition = (
      kubernetes_deployment_v1.workload["example"].metadata[0].labels["fdai.io/source-commit"] == var.workloads.example.source_commit &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].metadata[0].labels["fdai.io/source-commit"] == var.workloads.example.source_commit &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[0].image == var.workloads.example.image &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[0].image_pull_policy == "Always" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[0].security_context[0].read_only_root_filesystem &&
      !kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[0].security_context[0].allow_privilege_escalation
    )
    error_message = "Workloads must preserve the approved digest and run without a writable root or privilege escalation."
  }

  assert {
    condition = (
      !contains(keys(kubernetes_horizontal_pod_autoscaler_v2.workload["example"].metadata[0].labels), "fdai.io/source-commit") &&
      !contains(keys(kubernetes_pod_disruption_budget_v1.workload["example"].metadata[0].labels), "fdai.io/source-commit") &&
      !contains(keys(kubernetes_network_policy_v1.workload["example"].metadata[0].labels), "fdai.io/source-commit") &&
      !contains(keys(kubernetes_service_v1.workload["example"].metadata[0].labels), "fdai.io/source-commit")
    )
    error_message = "A service revision must change only its Deployment and Pod template labels."
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


  assert {
    condition = (
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[1].name == "clamav" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[1].image == var.workloads.example.sidecars.clamav.image &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[1].readiness_probe[0].tcp_socket[0].port == "3310" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[1].security_context[0].read_only_root_filesystem &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[1].security_context[0].run_as_user == "100" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[1].security_context[0].run_as_group == "101" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].security_context[0].fs_group == "101" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].init_container[0].name == "clamav-database" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].init_container[0].image == var.workloads.example.sidecars.clamav.image &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].init_container[0].image_pull_policy == "IfNotPresent" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].init_container[0].security_context[0].run_as_user == "100" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].init_container[0].security_context[0].run_as_group == "101" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].init_container[0].volume_mount[0].name == "clamav-database" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].init_container[0].volume_mount[0].mount_path == "/target" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].container[1].volume_mount[0].mount_path == "/var/lib/clamav" &&
      kubernetes_deployment_v1.workload["example"].spec[0].template[0].spec[0].volume[1].empty_dir[0].size_limit == "1Gi"
    )
    error_message = "Sidecars must stay digest-pinned, health-checked, read-only, and limited to declared writable volumes."
  }

  assert {
    condition = (
      kubernetes_service_v1.workload["example"].spec[0].port[0].port == 80 &&
      kubernetes_service_v1.workload["example"].spec[0].port[0].target_port == "8010"
    )
    error_message = "A public Service port may differ from its immutable container target port."
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

run "external_scale_exact_name_and_thor_subject" {
  command = plan

  variables {
    executor_external_scale_targets = { "example-shop" = ["order-service"] }
    workloads = {
      isolated-executor = merge(var.workloads.example, {
        component = "isolated-executor"
        environment = {
          FDAI_EXECUTION_VENUE = "deployed"
          FDAI_KUBERNETES_DIRECT_API_JSON = jsonencode({
            allowed_namespaces = ["example-shop"]
          })
        }
      })
    }
  }

  assert {
    condition = (
      length(kubernetes_role_v1.executor_external_scale) == 1 &&
      kubernetes_role_v1.executor_external_scale["example-shop"].metadata[0].namespace == "example-shop" &&
      length(kubernetes_role_v1.executor_external_scale["example-shop"].rule) == 2 &&
      alltrue([
        for rule in kubernetes_role_v1.executor_external_scale["example-shop"].rule :
        toset(rule.api_groups) == toset(["apps"]) &&
        toset(rule.resource_names) == toset(["order-service"]) &&
        (
          (toset(rule.resources) == toset(["deployments"]) && toset(rule.verbs) == toset(["get"])) ||
          (toset(rule.resources) == toset(["deployments/scale"]) && toset(rule.verbs) == toset(["get", "update"]))
        )
      ])
    )
    error_message = "Only named Deployment reads and scale updates may be granted in the selected namespace."
  }

  assert {
    condition = (
      kubernetes_role_binding_v1.executor_external_scale["example-shop"].metadata[0].namespace == "example-shop" &&
      kubernetes_role_binding_v1.executor_external_scale["example-shop"].role_ref[0].kind == "Role" &&
      length(kubernetes_role_binding_v1.executor_external_scale["example-shop"].subject) == 1 &&
      kubernetes_role_binding_v1.executor_external_scale["example-shop"].subject[0].name == "isolated-executor" &&
      kubernetes_role_binding_v1.executor_external_scale["example-shop"].subject[0].namespace == var.namespace
    )
    error_message = "Only Thor's existing runtime ServiceAccount may receive the external Role."
  }
}

run "reject_external_scale_without_allowlist" {
  command = plan

  variables {
    executor_external_scale_targets = { "example-shop" = ["order-service"] }
    workloads = {
      isolated-executor = merge(var.workloads.example, {
        component = "isolated-executor"
        environment = {
          FDAI_EXECUTION_VENUE = "deployed"
          FDAI_KUBERNETES_DIRECT_API_JSON = jsonencode({
            allowed_namespaces = ["other-shop"]
          })
        }
      })
    }
  }

  expect_failures = [kubernetes_role_v1.executor_external_scale]
}

run "reject_external_scale_for_local_runtime" {
  command = plan

  variables {
    executor_external_scale_targets = { "example-shop" = ["order-service"] }
    workloads = {
      isolated-executor = merge(var.workloads.example, {
        component = "isolated-executor"
        environment = {
          FDAI_EXECUTION_VENUE = "local"
          FDAI_KUBERNETES_DIRECT_API_JSON = jsonencode({
            allowed_namespaces = ["example-shop"]
          })
        }
      })
    }
  }

  expect_failures = [kubernetes_role_v1.executor_external_scale]
}

run "reject_empty_external_scale_names" {
  command = plan
  variables {
    executor_external_scale_targets = { "example-shop" = [] }
  }
  expect_failures = [var.executor_external_scale_targets]
}

run "reject_wildcard_external_scale_name" {
  command = plan
  variables {
    executor_external_scale_targets = { "example-shop" = ["*"] }
  }
  expect_failures = [var.executor_external_scale_targets]
}

run "reject_system_external_scale_namespace" {
  command = plan
  variables {
    executor_external_scale_targets = { "kube-system" = ["order-service"] }
  }
  expect_failures = [var.executor_external_scale_targets]
}

run "reject_implicit_default_scale_namespace" {
  command = plan
  variables {
    executor_external_scale_targets = { "default" = ["order-service"] }
  }
  expect_failures = [var.executor_external_scale_targets]
}

run "reject_runtime_as_external_scale_namespace" {
  command = plan
  variables {
    namespace                       = "example-runtime"
    executor_external_scale_targets = { "example-runtime" = ["order-service"] }
  }
  expect_failures = [var.executor_external_scale_targets]
}

mock_provider "azurerm" {}
mock_provider "kubernetes" {}

variables {
  kubeconfig_path = "/unused/mock-kubeconfig"
  tenant_id       = "00000000-0000-0000-0000-000000000000"
  oidc_issuer_url = "https://example.com/oidc/"
  key_vault_name  = "example"
  workloads       = {}
  code_security_worker = {
    source_commit           = "0000000000000000000000000000000000000000"
    image                   = "example.com/fdai/code-security-scanner@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    scanner_job_image       = "example.com/fdai/code-security-scanner@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    scanner_namespace       = "fdai-code-security-scanner"
    identity_resource_id    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/code-security-worker"
    identity_client_id      = "00000000-0000-0000-0000-000000000001"
    database_secret_name    = "code-security-worker-dsn"
    database_host           = "postgres.example.com"
    kafka_bootstrap_servers = "kafka.example.com:9093"
    controller_source_pvc   = "code-security-controller-source"
    controller_cache_pvc    = "code-security-controller-cache"
    scanner_source_pvc      = "code-security-scanner-source"
    scanner_cache_pvc       = "code-security-scanner-cache"
    scanner_cache_subpath   = "snapshots/0000000000000000000000000000000000000000000000000000000000000000/cache"
    runtime_env             = "dev"
    github = {
      app_client_id          = "example-client"
      app_installation_id    = "example-installation"
      app_private_key_secret = "code-security-github-app"
    }
  }
}

run "dedicated_worker_contract" {
  command = plan

  assert {
    condition = (
      output.code_security_worker_name == "code-security-worker" &&
      kubernetes_deployment_v1.code_security_worker[0].spec[0].replicas == "1" &&
      kubernetes_deployment_v1.code_security_worker[0].spec[0].strategy[0].type == "Recreate"
    )
    error_message = "The code-security worker must be one serialized dedicated Deployment."
  }

  assert {
    condition = (
      kubernetes_deployment_v1.code_security_worker[0].spec[0].template[0].spec[0].container[0].image == var.code_security_worker.image &&
      jsonencode(kubernetes_deployment_v1.code_security_worker[0].spec[0].template[0].spec[0].container[0].command) == jsonencode(["/usr/local/bin/fdai-scan-runner"]) &&
      jsonencode(kubernetes_deployment_v1.code_security_worker[0].spec[0].template[0].spec[0].container[0].args) == jsonencode([
        "serve-workers",
        "--state-access",
        "restricted",
        "--scanner-runtime",
        "kata",
        "--scanner-namespace",
        "fdai-code-security-scanner",
        "--scanner-image",
        "example.com/fdai/code-security-scanner@sha256:0000000000000000000000000000000000000000000000000000000000000000",
        "--scanner-source-pvc",
        "code-security-scanner-source",
        "--scanner-source-mount",
        "/work",
        "--scanner-cache-pvc",
        "code-security-scanner-cache",
        "--scanner-cache-subpath",
        "snapshots/0000000000000000000000000000000000000000000000000000000000000000/cache",
        "--cache-dir",
        "/cache",
        "--work-root",
        "/work/controller",
        "--kafka-bootstrap-servers",
        "kafka.example.com:9093",
        "--request-interval-seconds",
        "5",
        "--schedule-interval-seconds",
        "300",
        "--max-requests",
        "20",
        "--max-repositories",
        "5",
      ])
    )
    error_message = "The worker must use the scanner image wrapper with bounded restricted defaults."
  }

  assert {
    condition = (
      kubernetes_deployment_v1.code_security_worker[0].spec[0].template[0].spec[0].container[0].security_context[0].read_only_root_filesystem &&
      !kubernetes_deployment_v1.code_security_worker[0].spec[0].template[0].spec[0].container[0].security_context[0].allow_privilege_escalation &&
      kubernetes_deployment_v1.code_security_worker[0].spec[0].template[0].spec[0].volume[0].persistent_volume_claim[0].claim_name == "code-security-controller-source" &&
      !coalesce(kubernetes_deployment_v1.code_security_worker[0].spec[0].template[0].spec[0].volume[0].persistent_volume_claim[0].read_only, false) &&
      kubernetes_deployment_v1.code_security_worker[0].spec[0].template[0].spec[0].volume[1].persistent_volume_claim[0].claim_name == "code-security-controller-cache" &&
      kubernetes_deployment_v1.code_security_worker[0].spec[0].template[0].spec[0].volume[1].persistent_volume_claim[0].read_only &&
      {
        for item in kubernetes_deployment_v1.code_security_worker[0].spec[0].template[0].spec[0].container[0].env :
        item.name => item.value
        if item.value != null
      }["FDAI_DATABASE_ROLE"] == "fdai_code_security_worker" &&
      {
        for item in kubernetes_deployment_v1.code_security_worker[0].spec[0].template[0].spec[0].container[0].env :
        item.name => item.value
        if item.value != null
      }["FDAI_EXECUTION_VENUE"] == "deployed"
    )
    error_message = "The scanner must retain a restricted container and read-only cache binding."
  }

  assert {
    condition = (
      kubernetes_manifest.code_security_worker_secret_provider[0].manifest.spec.parameters.clientID == var.code_security_worker.identity_client_id &&
      kubernetes_service_account_v1.identity["workload-code-security-worker"].metadata[0].name == "code-security-worker" &&
      azurerm_federated_identity_credential.identity["workload-code-security-worker"].parent_id == var.code_security_worker.identity_resource_id
    )
    error_message = "The worker must retain its own workload identity and secret provider."
  }

  assert {
    condition = (
      kubernetes_namespace_v1.code_security_scanner[0].metadata[0].name == "fdai-code-security-scanner" &&
      kubernetes_namespace_v1.code_security_scanner[0].metadata[0].labels["pod-security.kubernetes.io/enforce"] == "restricted" &&
      jsonencode(kubernetes_network_policy_v1.code_security_scanner_deny_all[0].spec[0].policy_types) == jsonencode(["Ingress", "Egress"]) &&
      length(kubernetes_network_policy_v1.code_security_scanner_deny_all[0].spec[0].ingress) == 0 &&
      length(kubernetes_network_policy_v1.code_security_scanner_deny_all[0].spec[0].egress) == 0 &&
      kubernetes_role_binding_v1.code_security_scanner_controller[0].subject[0].name == "code-security-worker" &&
      kubernetes_role_binding_v1.code_security_scanner_controller[0].subject[0].namespace == "fdai-runtime" &&
      jsonencode(kubernetes_cluster_role_v1.code_security_scanner_observer[0].rule[1].resource_names) == jsonencode(["kata-vm-isolation"])
    )
    error_message = "Kata scanning requires its restricted deny-all namespace and minimum controller RBAC."
  }
}

run "worker_is_unbound_by_default" {
  command = plan
  variables { code_security_worker = null }

  assert {
    condition = (
      output.code_security_worker_name == null &&
      length(kubernetes_deployment_v1.code_security_worker) == 0 &&
      length(kubernetes_manifest.code_security_worker_secret_provider) == 0 &&
      length(kubernetes_namespace_v1.code_security_scanner) == 0 &&
      length(kubernetes_role_v1.code_security_scanner_controller) == 0 &&
      length(kubernetes_cluster_role_v1.code_security_scanner_observer) == 0
    )
    error_message = "An absent worker contract must create no partial workload or secret binding."
  }
}

run "invalid_kata_binding_fails_closed" {
  command = plan
  variables {
    code_security_worker = {
      source_commit           = "0000000000000000000000000000000000000000"
      image                   = "example.com/fdai/code-security-scanner@sha256:0000000000000000000000000000000000000000000000000000000000000000"
      scanner_job_image       = "example.com/fdai/code-security-scanner@sha256:1111111111111111111111111111111111111111111111111111111111111111"
      scanner_namespace       = "fdai-runtime"
      identity_resource_id    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/code-security-worker"
      identity_client_id      = "00000000-0000-0000-0000-000000000001"
      database_secret_name    = "code-security-worker-dsn"
      database_host           = "postgres.example.com"
      kafka_bootstrap_servers = "kafka.example.com:9093"
      controller_source_pvc   = "shared"
      controller_cache_pvc    = "shared"
      scanner_source_pvc      = "shared"
      scanner_cache_pvc       = "shared"
      scanner_cache_subpath   = "cache"
      runtime_env             = "dev"
      github = {
        app_client_id          = "example-client"
        app_installation_id    = "example-installation"
        app_private_key_secret = "code-security-github-app"
      }
    }
  }
  expect_failures = [
    var.code_security_worker,
  ]
}

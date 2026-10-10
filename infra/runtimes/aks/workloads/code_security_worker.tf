locals {
  code_security_worker_enabled = var.code_security_worker != null
  code_security_worker_name    = "code-security-worker"
  code_security_scanner_role   = "fdai-code-security-controller"
  code_security_scanner_cluster_role = (
    local.code_security_worker_enabled
    ? "fdai-scanner-observer-${var.code_security_worker.scanner_namespace}"
    : "fdai-scanner-observer-disabled"
  )
  code_security_worker_labels = merge(var.tags, {
    "app.kubernetes.io/name"       = local.code_security_worker_name
    "app.kubernetes.io/component"  = "code-security-worker"
    "app.kubernetes.io/managed-by" = "terraform"
    "fdai.io/runtime"              = "aks"
  })
  code_security_worker_deployment_labels = merge(local.code_security_worker_labels, {
    "fdai.io/source-commit" = local.code_security_worker_enabled ? var.code_security_worker.source_commit : ""
  })
  code_security_worker_github_app = (
    local.code_security_worker_enabled
    ? var.code_security_worker.github.token_secret == ""
    : false
  )
  code_security_worker_secret_environment = local.code_security_worker_enabled ? merge(
    {
      FDAI_STATE_STORE_DSN = var.code_security_worker.database_secret_name
    },
    local.code_security_worker_github_app ? {
      FDAI_GITHUB_APP_PRIVATE_KEY = var.code_security_worker.github.app_private_key_secret
      } : {
      FDAI_GITOPS_TOKEN = var.code_security_worker.github.token_secret
    },
  ) : {}
}

resource "kubernetes_namespace_v1" "code_security_scanner" {
  count = local.code_security_worker_enabled ? 1 : 0

  metadata {
    name = var.code_security_worker.scanner_namespace
    labels = {
      "app.kubernetes.io/part-of"                  = "fdai"
      "app.kubernetes.io/managed-by"               = "terraform"
      "pod-security.kubernetes.io/enforce"         = "restricted"
      "pod-security.kubernetes.io/enforce-version" = "latest"
    }
  }
}

resource "kubernetes_network_policy_v1" "code_security_scanner_deny_all" {
  count = local.code_security_worker_enabled ? 1 : 0

  metadata {
    name      = "fdai-code-security-deny-all"
    namespace = kubernetes_namespace_v1.code_security_scanner[0].metadata[0].name
    labels    = local.code_security_worker_labels
  }

  spec {
    pod_selector {}
    policy_types = ["Ingress", "Egress"]
  }
}

resource "kubernetes_role_v1" "code_security_scanner_controller" {
  count = local.code_security_worker_enabled ? 1 : 0

  metadata {
    name      = local.code_security_scanner_role
    namespace = kubernetes_namespace_v1.code_security_scanner[0].metadata[0].name
  }

  rule {
    api_groups = ["batch"]
    resources  = ["jobs"]
    verbs      = ["create", "get", "delete"]
  }

  rule {
    api_groups = [""]
    resources  = ["pods"]
    verbs      = ["get", "list"]
  }

  rule {
    api_groups = [""]
    resources  = ["pods/log"]
    verbs      = ["get"]
  }

  rule {
    api_groups = ["networking.k8s.io"]
    resources  = ["networkpolicies"]
    verbs      = ["get", "list"]
  }
}

resource "kubernetes_role_binding_v1" "code_security_scanner_controller" {
  count = local.code_security_worker_enabled ? 1 : 0

  metadata {
    name      = local.code_security_scanner_role
    namespace = kubernetes_namespace_v1.code_security_scanner[0].metadata[0].name
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role_v1.code_security_scanner_controller[0].metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account_v1.identity["workload-code-security-worker"].metadata[0].name
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
  }
}

resource "kubernetes_cluster_role_v1" "code_security_scanner_observer" {
  count = local.code_security_worker_enabled ? 1 : 0

  metadata {
    name = local.code_security_scanner_cluster_role
  }

  rule {
    api_groups     = [""]
    resources      = ["namespaces"]
    resource_names = [var.code_security_worker.scanner_namespace]
    verbs          = ["get"]
  }

  rule {
    api_groups     = ["node.k8s.io"]
    resources      = ["runtimeclasses"]
    resource_names = ["kata-vm-isolation"]
    verbs          = ["get"]
  }
}

resource "kubernetes_cluster_role_binding_v1" "code_security_scanner_observer" {
  count = local.code_security_worker_enabled ? 1 : 0

  metadata {
    name = local.code_security_scanner_cluster_role
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = kubernetes_cluster_role_v1.code_security_scanner_observer[0].metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account_v1.identity["workload-code-security-worker"].metadata[0].name
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
  }
}

resource "kubernetes_manifest" "code_security_worker_secret_provider" {
  count = local.code_security_worker_enabled ? 1 : 0

  manifest = {
    apiVersion = "secrets-store.csi.x-k8s.io/v1"
    kind       = "SecretProviderClass"
    metadata = {
      name      = local.code_security_worker_name
      namespace = var.namespace
    }
    spec = {
      provider = "azure"
      parameters = {
        usePodIdentity = "false"
        clientID       = var.code_security_worker.identity_client_id
        keyvaultName   = var.key_vault_name
        tenantId       = var.tenant_id
        objects = yamlencode({
          array = [
            for object_name in values(local.code_security_worker_secret_environment) :
            yamlencode({ objectName = object_name, objectType = "secret" })
          ]
        })
      }
      secretObjects = [{
        secretName = local.code_security_worker_name
        type       = "Opaque"
        data = [
          for environment_name, object_name in local.code_security_worker_secret_environment : {
            key        = environment_name
            objectName = object_name
          }
        ]
      }]
    }
  }

  depends_on = [kubernetes_namespace_v1.runtime]
}

resource "kubernetes_deployment_v1" "code_security_worker" {
  # checkov:skip=CKV_K8S_43:code_security_worker rejects images without a sha256 digest.
  # checkov:skip=CKV_K8S_14:code_security_worker requires an immutable digest, not a tag.
  count = local.code_security_worker_enabled ? 1 : 0

  metadata {
    name      = local.code_security_worker_name
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
    labels    = local.code_security_worker_deployment_labels
  }

  spec {
    replicas = 1

    selector {
      match_labels = { "app.kubernetes.io/name" = local.code_security_worker_name }
    }

    strategy {
      type = "Recreate"
    }

    template {
      metadata {
        labels = merge(local.code_security_worker_deployment_labels, {
          "azure.workload.identity/use" = "true"
        })
      }

      spec {
        service_account_name             = kubernetes_service_account_v1.identity["workload-code-security-worker"].metadata[0].name
        automount_service_account_token  = true
        termination_grace_period_seconds = 30
        node_selector                    = { "fdai.io/pool" = "runtime" }

        security_context {
          run_as_non_root = true
          run_as_user     = 65532
          run_as_group    = 65532
          fs_group        = 65532
          seccomp_profile { type = "RuntimeDefault" }
        }

        container {
          name              = local.code_security_worker_name
          image             = var.code_security_worker.image
          image_pull_policy = "Always"
          command           = ["/usr/local/bin/fdai-scan-runner"]
          args = [
            "serve-workers",
            "--state-access",
            "restricted",
            "--scanner-runtime",
            "kata",
            "--scanner-namespace",
            var.code_security_worker.scanner_namespace,
            "--scanner-image",
            var.code_security_worker.scanner_job_image,
            "--scanner-source-pvc",
            var.code_security_worker.scanner_source_pvc,
            "--scanner-source-mount",
            "/work",
            "--scanner-cache-pvc",
            var.code_security_worker.scanner_cache_pvc,
            "--scanner-cache-subpath",
            var.code_security_worker.scanner_cache_subpath,
            "--cache-dir",
            "/cache",
            "--work-root",
            "/work/controller",
            "--kafka-bootstrap-servers",
            var.code_security_worker.kafka_bootstrap_servers,
            "--request-interval-seconds",
            tostring(var.code_security_worker.request_interval_seconds),
            "--schedule-interval-seconds",
            tostring(var.code_security_worker.schedule_interval_seconds),
            "--max-requests",
            tostring(var.code_security_worker.max_requests),
            "--max-repositories",
            tostring(var.code_security_worker.max_repositories),
          ]

          security_context {
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            run_as_non_root            = true
            run_as_user                = 65532
            run_as_group               = 65532
            capabilities { drop = ["ALL"] }
          }

          resources {
            requests = {
              cpu    = var.code_security_worker.cpu
              memory = var.code_security_worker.memory
            }
            limits = {
              cpu    = var.code_security_worker.cpu
              memory = var.code_security_worker.memory
            }
          }

          env {
            name  = "POSTGRES_HOST"
            value = var.code_security_worker.database_host
          }
          env {
            name  = "FDAI_DATABASE_ROLE"
            value = var.code_security_worker.database_role
          }
          env {
            name  = "PGOPTIONS"
            value = "-c role=${var.code_security_worker.database_role}"
          }
          env {
            name  = "FDAI_EXECUTION_VENUE"
            value = "deployed"
          }
          env {
            name  = "RUNTIME_ENV"
            value = var.code_security_worker.runtime_env
          }
          env {
            name  = "FDAI_MI_CLIENT_ID"
            value = var.code_security_worker.identity_client_id
          }
          env {
            name  = "FDAI_SCAN_CACHE"
            value = "/cache"
          }
          env {
            name  = "FDAI_KAFKA_BOOTSTRAP_SERVERS"
            value = var.code_security_worker.kafka_bootstrap_servers
          }
          env {
            name  = "HOME"
            value = "/tmp"
          }

          dynamic "env" {
            for_each = local.code_security_worker_github_app ? {
              FDAI_GITHUB_APP_CLIENT_ID       = var.code_security_worker.github.app_client_id
              FDAI_GITHUB_APP_INSTALLATION_ID = var.code_security_worker.github.app_installation_id
            } : {}
            content {
              name  = env.key
              value = env.value
            }
          }

          dynamic "env" {
            for_each = local.code_security_worker_secret_environment
            content {
              name = env.key
              value_from {
                secret_key_ref {
                  name = local.code_security_worker_name
                  key  = env.key
                }
              }
            }
          }

          volume_mount {
            name       = "cache"
            mount_path = "/cache"
            sub_path   = var.code_security_worker.scanner_cache_subpath
            read_only  = true
          }
          volume_mount {
            name       = "source"
            mount_path = "/work"
          }
          volume_mount {
            name       = "tmp"
            mount_path = "/tmp"
          }
          volume_mount {
            name       = "secrets"
            mount_path = "/mnt/secrets-store"
            read_only  = true
          }
        }

        volume {
          name = "source"
          persistent_volume_claim {
            claim_name = var.code_security_worker.controller_source_pvc
          }
        }
        volume {
          name = "cache"
          persistent_volume_claim {
            claim_name = var.code_security_worker.controller_cache_pvc
            read_only  = true
          }
        }
        volume {
          name = "tmp"
          empty_dir {
            size_limit = "1Gi"
          }
        }
        volume {
          name = "secrets"
          csi {
            driver            = "secrets-store.csi.k8s.io"
            read_only         = true
            volume_attributes = { secretProviderClass = local.code_security_worker_name }
          }
        }
      }
    }
  }

  depends_on = [
    kubernetes_manifest.code_security_worker_secret_provider,
    kubernetes_network_policy_v1.code_security_scanner_deny_all,
    kubernetes_role_binding_v1.code_security_scanner_controller,
    kubernetes_cluster_role_binding_v1.code_security_scanner_observer,
  ]
}

resource "kubernetes_network_policy_v1" "code_security_worker" {
  count = local.code_security_worker_enabled ? 1 : 0

  metadata {
    name      = local.code_security_worker_name
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
    labels    = local.code_security_worker_labels
  }

  spec {
    pod_selector {
      match_labels = { "app.kubernetes.io/name" = local.code_security_worker_name }
    }
    policy_types = ["Ingress"]
  }
}

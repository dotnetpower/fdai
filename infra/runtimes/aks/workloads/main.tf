locals {
  workload_labels = {
    for name, workload in var.workloads : name => merge(var.tags, {
      "app.kubernetes.io/name"       = name
      "app.kubernetes.io/component"  = workload.component
      "app.kubernetes.io/managed-by" = "terraform"
      "fdai.io/runtime"              = "aks"
    })
  }
  job_labels = {
    for name, job in var.scheduled_jobs : name => merge(var.tags, {
      "app.kubernetes.io/name"       = name
      "app.kubernetes.io/component"  = job.component
      "app.kubernetes.io/managed-by" = "terraform"
      "fdai.io/runtime"              = "aks"
    })
  }
  identities = merge(
    {
      for name, workload in var.workloads : "workload-${name}" => {
        service_account_name = name
        resource_id          = workload.identity_resource_id
        client_id            = workload.identity_client_id
      }
    },
    {
      for name, job in var.scheduled_jobs : "job-${name}" => {
        service_account_name = "${name}-job"
        resource_id          = job.identity_resource_id
        client_id            = job.identity_client_id
      }
    },
    merge([
      for name, workload in var.workloads : {
        for identity_name, identity in workload.additional_identities :
        "workload-${name}-${identity_name}" => {
          service_account_name = name
          resource_id          = identity.resource_id
          client_id            = identity.client_id
        }
      }
    ]...),
  )
  service_accounts = merge(
    {
      for name, workload in var.workloads : "workload-${name}" => {
        name      = name
        client_id = workload.identity_client_id
      }
    },
    {
      for name, job in var.scheduled_jobs : "job-${name}" => {
        name      = "${name}-job"
        client_id = job.identity_client_id
      }
    },
  )
  inventory_job_enabled = contains(keys(var.scheduled_jobs), "inventory")
  executor_kubernetes_effect_enabled = try(
    contains(
      keys(var.workloads["isolated-executor"].environment),
      "FDAI_KUBERNETES_DIRECT_API_JSON",
    ),
    false,
  )
}

resource "kubernetes_namespace_v1" "runtime" {
  metadata {
    name = var.namespace
    labels = {
      "app.kubernetes.io/part-of"          = "fdai"
      "app.kubernetes.io/managed-by"       = "terraform"
      "pod-security.kubernetes.io/enforce" = "restricted"
    }
  }
}

resource "kubernetes_service_account_v1" "identity" {
  for_each = local.service_accounts

  metadata {
    name      = each.value.name
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
    annotations = {
      "azure.workload.identity/client-id" = each.value.client_id
      "azure.workload.identity/tenant-id" = var.tenant_id
    }
  }
}

resource "kubernetes_cluster_role_v1" "inventory_reader" {
  count = local.inventory_job_enabled ? 1 : 0

  metadata {
    name = "${var.namespace}-inventory-reader"
  }

  rule {
    api_groups = [""]
    resources = [
      "endpoints",
      "limitranges",
      "namespaces",
      "nodes",
      "persistentvolumeclaims",
      "persistentvolumes",
      "pods",
      "resourcequotas",
      "services",
    ]
    verbs = ["get", "list"]
  }

  rule {
    api_groups = [""]
    resources  = ["events"]
    verbs      = ["get", "list", "watch"]
  }

  rule {
    api_groups = ["apps"]
    resources  = ["daemonsets", "deployments", "replicasets", "statefulsets"]
    verbs      = ["get", "list"]
  }

  rule {
    api_groups = ["autoscaling"]
    resources  = ["horizontalpodautoscalers"]
    verbs      = ["get", "list"]
  }

  rule {
    api_groups = ["batch"]
    resources  = ["cronjobs", "jobs"]
    verbs      = ["get", "list"]
  }

  rule {
    api_groups = ["discovery.k8s.io"]
    resources  = ["endpointslices"]
    verbs      = ["get", "list"]
  }

  rule {
    api_groups = ["networking.k8s.io"]
    resources  = ["ingressclasses", "ingresses", "networkpolicies"]
    verbs      = ["get", "list"]
  }

  rule {
    api_groups = ["policy"]
    resources  = ["poddisruptionbudgets"]
    verbs      = ["get", "list"]
  }

  rule {
    api_groups = ["storage.k8s.io"]
    resources  = ["storageclasses"]
    verbs      = ["get", "list"]
  }
}

resource "kubernetes_cluster_role_binding_v1" "inventory_reader" {
  count = local.inventory_job_enabled ? 1 : 0

  metadata {
    name = "${var.namespace}-inventory-reader"
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = kubernetes_cluster_role_v1.inventory_reader[0].metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account_v1.identity["job-inventory"].metadata[0].name
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
  }
}

resource "kubernetes_role_v1" "executor_kubernetes_effect" {
  count = local.executor_kubernetes_effect_enabled ? 1 : 0

  metadata {
    name      = "isolated-executor-kubernetes-effect"
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
  }

  rule {
    api_groups = [""]
    resources  = ["pods"]
    verbs      = ["get", "delete"]
  }

  rule {
    api_groups = ["apps"]
    resources  = ["deployments"]
    verbs      = ["get", "patch"]
  }

  rule {
    api_groups = ["apps"]
    resources  = ["deployments/scale"]
    verbs      = ["get", "update"]
  }
}

resource "kubernetes_role_binding_v1" "executor_kubernetes_effect" {
  count = local.executor_kubernetes_effect_enabled ? 1 : 0

  metadata {
    name      = "isolated-executor-kubernetes-effect"
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role_v1.executor_kubernetes_effect[0].metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account_v1.identity["workload-isolated-executor"].metadata[0].name
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
  }
}

resource "azurerm_federated_identity_credential" "identity" {
  for_each = local.identities

  name                = "aks-${each.key}"
  resource_group_name = element(split("/", each.value.resource_id), 4)
  parent_id           = each.value.resource_id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = var.oidc_issuer_url
  subject             = "system:serviceaccount:${var.namespace}:${each.value.service_account_name}"
}

resource "kubernetes_manifest" "workload_secret_provider" {
  for_each = {
    for name, workload in var.workloads : name => workload
    if length(workload.secret_environment) > 0
  }

  manifest = {
    apiVersion = "secrets-store.csi.x-k8s.io/v1"
    kind       = "SecretProviderClass"
    metadata = {
      name      = each.key
      namespace = var.namespace
    }
    spec = {
      provider = "azure"
      parameters = {
        usePodIdentity = "false"
        clientID       = each.value.identity_client_id
        keyvaultName   = var.key_vault_name
        tenantId       = var.tenant_id
        objects = yamlencode({
          array = [
            for object_name in values(each.value.secret_environment) :
            yamlencode({ objectName = object_name, objectType = "secret" })
          ]
        })
      }
      secretObjects = [{
        secretName = each.key
        type       = "Opaque"
        data = [
          for environment_name, object_name in each.value.secret_environment : {
            key        = environment_name
            objectName = object_name
          }
        ]
      }]
    }
  }

  depends_on = [kubernetes_namespace_v1.runtime]
}

resource "kubernetes_manifest" "job_secret_provider" {
  for_each = {
    for name, job in var.scheduled_jobs : name => job
    if length(job.secret_environment) > 0
  }

  manifest = {
    apiVersion = "secrets-store.csi.x-k8s.io/v1"
    kind       = "SecretProviderClass"
    metadata = {
      name      = "${each.key}-job"
      namespace = var.namespace
    }
    spec = {
      provider = "azure"
      parameters = {
        usePodIdentity = "false"
        clientID       = each.value.identity_client_id
        keyvaultName   = var.key_vault_name
        tenantId       = var.tenant_id
        objects = yamlencode({
          array = [
            for object_name in values(each.value.secret_environment) :
            yamlencode({ objectName = object_name, objectType = "secret" })
          ]
        })
      }
      secretObjects = [{
        secretName = "${each.key}-job"
        type       = "Opaque"
        data = [
          for environment_name, object_name in each.value.secret_environment : {
            key        = environment_name
            objectName = object_name
          }
        ]
      }]
    }
  }

  depends_on = [kubernetes_namespace_v1.runtime]
}

resource "kubernetes_deployment_v1" "workload" {
  # checkov:skip=CKV_K8S_43:var.workloads rejects images without a sha256 digest; Checkov cannot resolve each.value.image.
  # checkov:skip=CKV_K8S_14:var.workloads requires immutable digest references rather than mutable image tags.
  for_each = var.workloads

  metadata {
    name      = each.key
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
    labels    = local.workload_labels[each.key]
  }

  spec {
    replicas = each.value.replicas

    selector {
      match_labels = { "app.kubernetes.io/name" = each.key }
    }

    strategy {
      type = "RollingUpdate"
      rolling_update {
        max_surge       = "1"
        max_unavailable = "0"
      }
    }

    template {
      metadata {
        labels = merge(local.workload_labels[each.key], {
          "azure.workload.identity/use" = "true"
        })
      }

      spec {
        service_account_name             = kubernetes_service_account_v1.identity["workload-${each.key}"].metadata[0].name
        automount_service_account_token  = true
        termination_grace_period_seconds = 30
        node_selector                    = { "fdai.io/pool" = "runtime" }

        security_context {
          run_as_non_root = true
          seccomp_profile { type = "RuntimeDefault" }
        }

        container {
          name              = each.key
          image             = each.value.image
          image_pull_policy = "Always"
          command           = each.value.command
          args              = each.value.args

          security_context {
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            capabilities { drop = ["ALL"] }
          }

          resources {
            requests = { cpu = each.value.cpu, memory = each.value.memory }
            limits   = { cpu = each.value.cpu, memory = each.value.memory }
          }

          port { container_port = each.value.port }

          readiness_probe {
            http_get {
              path = each.value.readiness_path
              port = each.value.port
            }
            initial_delay_seconds = 5
            period_seconds        = 10
            timeout_seconds       = 3
            failure_threshold     = 3
          }

          liveness_probe {
            http_get {
              path = each.value.liveness_path
              port = each.value.port
            }
            initial_delay_seconds = 10
            period_seconds        = 30
            timeout_seconds       = 3
            failure_threshold     = 3
          }

          dynamic "env" {
            for_each = each.value.environment
            content {
              name  = env.key
              value = env.value
            }
          }

          dynamic "env" {
            for_each = each.value.secret_environment
            content {
              name = env.key
              value_from {
                secret_key_ref {
                  name = each.key
                  key  = env.key
                }
              }
            }
          }

          volume_mount {
            name       = "tmp"
            mount_path = "/tmp"
          }

          dynamic "volume_mount" {
            for_each = length(each.value.secret_environment) > 0 ? [1] : []
            content {
              name       = "secrets"
              mount_path = "/mnt/secrets-store"
              read_only  = true
            }
          }
        }

        dynamic "container" {
          for_each = each.value.sidecars
          iterator = sidecar
          content {
            name              = sidecar.key
            image             = sidecar.value.image
            image_pull_policy = "Always"
            command           = sidecar.value.command
            args              = sidecar.value.args

            security_context {
              allow_privilege_escalation = false
              read_only_root_filesystem  = true
              capabilities { drop = ["ALL"] }
            }

            resources {
              requests = { cpu = sidecar.value.cpu, memory = sidecar.value.memory }
              limits   = { cpu = sidecar.value.cpu, memory = sidecar.value.memory }
            }

            port { container_port = sidecar.value.port }

            readiness_probe {
              tcp_socket { port = sidecar.value.port }
              initial_delay_seconds = 5
              period_seconds        = 10
              timeout_seconds       = 3
              failure_threshold     = 3
            }

            liveness_probe {
              tcp_socket { port = sidecar.value.port }
              initial_delay_seconds = 10
              period_seconds        = 30
              timeout_seconds       = 3
              failure_threshold     = 3
            }

            dynamic "volume_mount" {
              for_each = sidecar.value.writable_paths
              content {
                name       = "${sidecar.key}-${volume_mount.key}"
                mount_path = volume_mount.value.mount_path
              }
            }
          }
        }

        volume {
          name = "tmp"
          empty_dir {
            size_limit = "1Gi"
          }
        }

        dynamic "volume" {
          for_each = merge({}, [
            for sidecar_name, sidecar in each.value.sidecars : {
              for volume_name, volume in sidecar.writable_paths :
              "${sidecar_name}-${volume_name}" => volume
            }
          ]...)
          content {
            name = volume.key
            empty_dir {
              size_limit = volume.value.size_limit
            }
          }
        }

        dynamic "volume" {
          for_each = length(each.value.secret_environment) > 0 ? [1] : []
          content {
            name = "secrets"
            csi {
              driver            = "secrets-store.csi.k8s.io"
              read_only         = true
              volume_attributes = { secretProviderClass = each.key }
            }
          }
        }
      }
    }
  }

  depends_on = [kubernetes_manifest.workload_secret_provider]

  lifecycle {
    ignore_changes = [spec[0].replicas]
  }
}

resource "kubernetes_horizontal_pod_autoscaler_v2" "workload" {
  for_each = var.workloads

  metadata {
    name      = each.key
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
    labels    = local.workload_labels[each.key]
  }

  spec {
    min_replicas = each.value.replicas
    max_replicas = each.value.max_replicas

    scale_target_ref {
      api_version = "apps/v1"
      kind        = "Deployment"
      name        = kubernetes_deployment_v1.workload[each.key].metadata[0].name
    }

    metric {
      type = "Resource"
      resource {
        name = "cpu"
        target {
          type                = "Utilization"
          average_utilization = 70
        }
      }
    }
  }
}

resource "kubernetes_pod_disruption_budget_v1" "workload" {
  for_each = var.workloads

  metadata {
    name      = each.key
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
    labels    = local.workload_labels[each.key]
  }

  spec {
    min_available = "1"
    selector {
      match_labels = { "app.kubernetes.io/name" = each.key }
    }
  }
}

resource "kubernetes_network_policy_v1" "workload" {
  for_each = var.workloads

  metadata {
    name      = each.key
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
    labels    = local.workload_labels[each.key]
  }

  spec {
    pod_selector {
      match_labels = { "app.kubernetes.io/name" = each.key }
    }
    policy_types = ["Ingress"]

    ingress {
      dynamic "from" {
        for_each = each.value.external ? [] : [1]
        content {
          namespace_selector {
            match_labels = {
              "kubernetes.io/metadata.name" = var.namespace
            }
          }
        }
      }
      ports {
        port     = tostring(each.value.port)
        protocol = "TCP"
      }
    }
  }
}

resource "kubernetes_service_v1" "workload" {
  for_each = var.workloads

  metadata {
    name      = each.key
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
    labels    = local.workload_labels[each.key]
  }

  spec {
    selector = { "app.kubernetes.io/name" = each.key }
    type     = each.value.external ? "LoadBalancer" : "ClusterIP"
    port {
      port        = each.value.port
      target_port = each.value.port
    }
  }
}

resource "kubernetes_cron_job_v1" "job" {
  for_each = var.scheduled_jobs

  metadata {
    name      = each.key
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
    labels    = local.job_labels[each.key]
  }

  spec {
    concurrency_policy            = "Forbid"
    schedule                      = each.value.schedule
    successful_jobs_history_limit = 3
    failed_jobs_history_limit     = 3

    job_template {
      metadata { labels = local.job_labels[each.key] }
      spec {
        completions                = 1
        parallelism                = 1
        backoff_limit              = each.value.retry_limit
        active_deadline_seconds    = each.value.deadline_seconds
        ttl_seconds_after_finished = 3600

        template {
          metadata {
            labels = merge(local.job_labels[each.key], {
              "azure.workload.identity/use" = "true"
            })
          }
          spec {
            service_account_name            = kubernetes_service_account_v1.identity["job-${each.key}"].metadata[0].name
            automount_service_account_token = true
            restart_policy                  = "Never"
            node_selector                   = { "fdai.io/pool" = "runtime" }

            security_context {
              run_as_non_root = true
              seccomp_profile { type = "RuntimeDefault" }
            }

            container {
              name    = each.key
              image   = each.value.image
              command = each.value.command
              args    = each.value.args

              security_context {
                allow_privilege_escalation = false
                capabilities { drop = ["ALL"] }
              }

              resources {
                requests = { cpu = each.value.cpu, memory = each.value.memory }
                limits   = { cpu = each.value.cpu, memory = each.value.memory }
              }

              dynamic "env" {
                for_each = each.value.environment
                content {
                  name  = env.key
                  value = env.value
                }
              }

              dynamic "env" {
                for_each = each.value.secret_environment
                content {
                  name = env.key
                  value_from {
                    secret_key_ref {
                      name = "${each.key}-job"
                      key  = env.key
                    }
                  }
                }
              }

              dynamic "volume_mount" {
                for_each = length(each.value.secret_environment) > 0 ? [1] : []
                content {
                  name       = "secrets"
                  mount_path = "/mnt/secrets-store"
                  read_only  = true
                }
              }
            }

            dynamic "volume" {
              for_each = length(each.value.secret_environment) > 0 ? [1] : []
              content {
                name = "secrets"
                csi {
                  driver            = "secrets-store.csi.k8s.io"
                  read_only         = true
                  volume_attributes = { secretProviderClass = "${each.key}-job" }
                }
              }
            }
          }
        }
      }
    }
  }

  depends_on = [kubernetes_manifest.job_secret_provider]
}

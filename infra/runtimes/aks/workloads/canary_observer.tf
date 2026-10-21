locals {
  canary_observer_enabled = (
    contains(keys(var.workloads), "core-control-plane") &&
    contains(keys(var.scheduled_jobs), "canary")
  )
  canary_observer_environment = local.canary_observer_enabled ? {
    FDAI_CANARY_OBSERVER_NAMESPACE = var.namespace
    FDAI_CANARY_OBSERVER_CRONJOB   = "canary"
  } : {}
}

resource "kubernetes_role_v1" "canary_observer" {
  count = local.canary_observer_enabled ? 1 : 0

  metadata {
    name      = "core-canary-observer"
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
  }

  rule {
    api_groups     = ["batch"]
    resources      = ["cronjobs"]
    resource_names = ["canary"]
    verbs          = ["get"]
  }

  rule {
    api_groups = ["batch"]
    resources  = ["jobs"]
    verbs      = ["list"]
  }
}

resource "kubernetes_role_binding_v1" "canary_observer" {
  count = local.canary_observer_enabled ? 1 : 0

  metadata {
    name      = "core-canary-observer"
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role_v1.canary_observer[0].metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account_v1.identity["workload-core-control-plane"].metadata[0].name
    namespace = kubernetes_namespace_v1.runtime.metadata[0].name
  }
}

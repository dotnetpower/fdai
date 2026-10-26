locals {
  placeholder_labels = {
    "fdai.io/state-handoff-placeholder" = "true"
  }
  placeholder_image = "registry.invalid/fdai/state-handoff@sha256:0000000000000000000000000000000000000000000000000000000000000000"
}

resource "kubernetes_deployment_v1" "workload" {
  # checkov:skip=CKV_K8S_28:Import-only placeholder; mandatory import plus ignore_changes/prevent_destroy means this container is never created or executed.
  # checkov:skip=CKV_K8S_29:Import-only placeholder; the live Deployment pod security context is retained without Terraform mutation.
  # checkov:skip=CKV_K8S_13:Import-only placeholder; live memory requests are imported and ignored, never replaced by this configuration.
  # checkov:skip=CKV_K8S_12:Import-only placeholder; live memory limits are imported and ignored, never replaced by this configuration.
  # checkov:skip=CKV_K8S_11:Import-only placeholder; live CPU limits are imported and ignored, never replaced by this configuration.
  # checkov:skip=CKV_K8S_30:Import-only placeholder; the live container security context is retained without Terraform mutation.
  # checkov:skip=CKV_K8S_8:Import-only placeholder; live liveness probes are imported and ignored, never replaced by this configuration.
  # checkov:skip=CKV_K8S_10:Import-only placeholder; live CPU requests are imported and ignored, never replaced by this configuration.
  # checkov:skip=CKV_K8S_9:Import-only placeholder; live readiness probes are imported and ignored, never replaced by this configuration.
  for_each = var.deployments

  metadata {
    name      = each.key
    namespace = var.namespace
  }

  spec {
    replicas = 1

    selector {
      match_labels = local.placeholder_labels
    }

    template {
      metadata {
        labels = local.placeholder_labels
      }
      spec {
        container {
          name  = "state-handoff-placeholder"
          image = local.placeholder_image
        }
      }
    }
  }

  lifecycle {
    ignore_changes  = all
    prevent_destroy = true
  }
}

import {
  for_each = var.deployments
  to       = kubernetes_deployment_v1.workload[each.key]
  id       = each.value
}

resource "kubernetes_service_v1" "workload" {
  for_each = var.services

  metadata {
    name      = each.key
    namespace = var.namespace
  }

  spec {
    selector = local.placeholder_labels
    port {
      port        = 65535
      target_port = 65535
    }
  }

  lifecycle {
    ignore_changes  = all
    prevent_destroy = true
  }
}

import {
  for_each = var.services
  to       = kubernetes_service_v1.workload[each.key]
  id       = each.value
}

resource "kubernetes_cron_job_v1" "job" {
  for_each = var.cron_jobs

  metadata {
    name      = each.key
    namespace = var.namespace
  }

  spec {
    schedule = "0 0 31 2 *"
    suspend  = true

    job_template {
      metadata {}
      spec {
        template {
          metadata {}
          spec {
            restart_policy = "Never"
            container {
              name    = "state-handoff-placeholder"
              image   = local.placeholder_image
              command = ["/bin/false"]
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes  = all
    prevent_destroy = true
  }
}

import {
  for_each = var.cron_jobs
  to       = kubernetes_cron_job_v1.job[each.key]
  id       = each.value
}

resource "kubernetes_horizontal_pod_autoscaler_v2" "workload" {
  for_each = var.horizontal_pod_autoscalers

  metadata {
    name      = each.key
    namespace = var.namespace
  }

  spec {
    min_replicas = 1
    max_replicas = 1

    scale_target_ref {
      api_version = "apps/v1"
      kind        = "Deployment"
      name        = each.key
    }

    metric {
      type = "Resource"
      resource {
        name = "cpu"
        target {
          type                = "Utilization"
          average_utilization = 100
        }
      }
    }
  }

  lifecycle {
    ignore_changes  = all
    prevent_destroy = true
  }
}

import {
  for_each = var.horizontal_pod_autoscalers
  to       = kubernetes_horizontal_pod_autoscaler_v2.workload[each.key]
  id       = each.value
}

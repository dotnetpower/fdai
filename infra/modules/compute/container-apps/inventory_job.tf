// Continuous Azure inventory collection. Each tick drains provider changes and
// then scans only when durable scheduling state says reconciliation is due.
// The job uses a dedicated read-only identity, never the executor MI.
resource "azurerm_container_app_job" "inventory" {
  count = var.inventory_cron_expression == "" ? 0 : 1

  name                         = local.core_job_names.inventory
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 1800
  replica_retry_limit          = 2

  identity {
    type         = "UserAssigned"
    identity_ids = [var.inventory_identity_id]
  }

  dynamic "registry" {
    for_each = var.acr_login_server == "" ? toset([]) : toset(["1"])
    content {
      server   = var.acr_login_server
      identity = var.inventory_identity_id
    }
  }

  secret {
    name                = "inventory-dsn"
    identity            = var.inventory_identity_id
    key_vault_secret_id = var.inventory_dsn_secret_id
  }

  schedule_trigger_config {
    cron_expression          = var.inventory_cron_expression
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name    = "inventory"
      image   = var.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "-m", "fdai.delivery.inventory_sync_cli"]

      dynamic "env" {
        for_each = local.core_config_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = var.monitor_workspace_customer_id == "" ? toset([]) : toset(["1"])
        content {
          name  = "FDAI_MONITOR_WORKSPACE_ID"
          value = var.monitor_workspace_customer_id
        }
      }
      dynamic "env" {
        for_each = var.runtime_call_evidence_enabled ? toset(["1"]) : toset([])
        content {
          name  = "FDAI_RUNTIME_CALL_EVIDENCE_ENABLED"
          value = "1"
        }
      }

      env {
        name        = "FDAI_INVENTORY_DSN"
        secret_name = "inventory-dsn"
      }
      env {
        name  = "FDAI_INVENTORY_SCOPES"
        value = var.azure_subscription_id
      }
      env {
        name  = "FDAI_INVENTORY_SOURCES"
        value = var.inventory_sources
      }
      env {
        name  = "FDAI_INVENTORY_FRESHNESS_SECONDS"
        value = tostring(var.inventory_freshness_seconds)
      }
      env {
        name  = "FDAI_INVENTORY_RECONCILIATION_INTERVAL_SECONDS"
        value = tostring(var.inventory_reconciliation_interval_seconds)
      }
      env {
        name  = "FDAI_INVENTORY_CHANGE_MIN_INTERVAL_SECONDS"
        value = tostring(var.inventory_change_min_interval_seconds)
      }
      env {
        name  = "FDAI_INVENTORY_PROGRESS_DEADLINE_SECONDS"
        value = tostring(var.inventory_progress_deadline_seconds)
      }
      env {
        name  = "FDAI_INVENTORY_ATTEMPT_DEADLINE_SECONDS"
        value = tostring(var.inventory_attempt_deadline_seconds)
      }
      env {
        name  = "FDAI_INVENTORY_ARG_REQUESTS_PER_SECOND"
        value = tostring(var.inventory_arg_requests_per_second)
      }
      env {
        name  = "FDAI_INVENTORY_RECOVERY_DELTA"
        value = var.infrastructure_subnet_id == null ? "0" : "1"
      }
      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = var.inventory_identity_client_id
      }
      dynamic "env" {
        for_each = var.inventory_kubernetes_subscription_discovery_enabled ? toset(["1"]) : toset([])
        content {
          name  = "FDAI_KUBERNETES_SUBSCRIPTION_DISCOVERY"
          value = "1"
        }
      }
      dynamic "env" {
        for_each = var.inventory_kubernetes_api_server == "" ? toset([]) : toset(["1"])
        content {
          name  = "FDAI_KUBERNETES_API_SERVER"
          value = var.inventory_kubernetes_api_server
        }
      }
      dynamic "env" {
        for_each = nonsensitive(var.inventory_kubernetes_cluster_bindings_json == "") ? toset([]) : toset(["1"])
        content {
          name  = "FDAI_KUBERNETES_CLUSTER_BINDINGS_JSON"
          value = var.inventory_kubernetes_cluster_bindings_json
        }
      }
      dynamic "env" {
        for_each = var.inventory_kubernetes_api_server == "" ? toset([]) : toset(["1"])
        content {
          name  = "FDAI_KUBERNETES_CLUSTER_REF"
          value = var.inventory_kubernetes_cluster_ref
        }
      }
      dynamic "env" {
        for_each = var.inventory_kubernetes_api_server == "" ? toset([]) : toset(["1"])
        content {
          name  = "FDAI_KUBERNETES_AUTH_MODE"
          value = "workload-identity"
        }
      }
      dynamic "env" {
        for_each = var.inventory_kubernetes_api_server == "" ? toset([]) : toset(["1"])
        content {
          name  = "FDAI_KUBERNETES_CA_PEM"
          value = var.inventory_kubernetes_ca_pem
        }
      }
      dynamic "env" {
        for_each = var.inventory_kubernetes_api_server == "" ? toset([]) : toset(["1"])
        content {
          name  = "FDAI_KUBERNETES_AUDIENCE"
          value = var.inventory_kubernetes_audience
        }
      }
    }
  }

  tags = var.tags

  lifecycle {
    precondition {
      condition = (
        var.inventory_kubernetes_subscription_discovery_enabled ?
        alltrue([
          var.inventory_kubernetes_cluster_bindings_json == "",
          var.inventory_kubernetes_api_server == "",
          var.inventory_kubernetes_cluster_ref == "",
          var.inventory_kubernetes_ca_pem == "",
          var.inventory_kubernetes_audience == "",
        ]) : var.inventory_kubernetes_cluster_bindings_json != "" ?
        alltrue([
          var.inventory_kubernetes_api_server == "",
          var.inventory_kubernetes_cluster_ref == "",
          var.inventory_kubernetes_ca_pem == "",
          var.inventory_kubernetes_audience == "",
        ]) :
        (
          alltrue([
            var.inventory_kubernetes_api_server == "",
            var.inventory_kubernetes_cluster_ref == "",
            var.inventory_kubernetes_ca_pem == "",
          ]) ||
          alltrue([
            var.inventory_kubernetes_api_server != "",
            var.inventory_kubernetes_cluster_ref != "",
            var.inventory_kubernetes_ca_pem != "",
            var.inventory_kubernetes_audience != "",
          ])
        )
      )
      error_message = "AKS subscription discovery, fleet JSON, and legacy bindings are mutually exclusive; legacy API server, cluster ref, CA PEM, and audience must be configured together."
    }
  }
}

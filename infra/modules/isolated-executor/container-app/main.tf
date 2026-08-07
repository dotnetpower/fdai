resource "azurerm_container_app" "shadow" {
  name                         = var.name
  container_app_environment_id = var.container_app_environment_id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = concat([var.identity_id], var.extra_identity_ids)
  }

  dynamic "registry" {
    for_each = var.acr_login_server == "" ? toset([]) : toset(["1"])
    content {
      server   = var.acr_login_server
      identity = var.identity_id
    }
  }

  secret {
    name                = "state-store-dsn"
    identity            = var.identity_id
    key_vault_secret_id = var.state_store_dsn_secret_id
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name    = "isolated-executor-shadow"
      image   = var.image
      cpu     = var.cpu
      memory  = var.memory
      command = ["fdai-isolated-executor"]

      env {
        name  = "RUNTIME_ENV"
        value = var.runtime_env
      }
      env {
        name  = "FDAI_ISOLATED_EXECUTOR_DEPLOYED"
        value = "1"
      }
      env {
        name  = "FDAI_ISOLATED_EXECUTOR_MI_CLIENT_ID"
        value = var.identity_client_id
      }
      dynamic "env" {
        for_each = var.authority_cutover ? toset(["1"]) : toset([])
        content {
          name  = "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER"
          value = "1"
        }
      }
      dynamic "env" {
        for_each = var.authority_cutover ? toset(["1"]) : toset([])
        content {
          name  = "FDAI_DEV_OPERATIONS_GATEWAY_URL"
          value = var.dev_operations_gateway_url
        }
      }
      dynamic "env" {
        for_each = var.authority_cutover ? toset(["1"]) : toset([])
        content {
          name  = "FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE"
          value = var.dev_operations_gateway_audience
        }
      }
      dynamic "env" {
        for_each = {
          for name, client_id in {
            FDAI_CHANGE_MI_CLIENT_ID     = var.change_identity_client_id
            FDAI_RESILIENCE_MI_CLIENT_ID = var.resilience_identity_client_id
            FDAI_FINOPS_MI_CLIENT_ID     = var.finops_identity_client_id
          } : name => client_id if client_id != ""
        }
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name  = "KAFKA_BOOTSTRAP_SERVERS"
        value = var.kafka_bootstrap_servers
      }
      env {
        name  = "KAFKA_TOPIC_DLQ_SUFFIX"
        value = var.dlq_suffix
      }
      env {
        name  = "FDAI_EXECUTOR_COMMAND_TOPIC"
        value = var.command_topic
      }
      env {
        name  = "FDAI_EXECUTOR_RECEIPT_TOPIC"
        value = var.receipt_topic
      }
      env {
        name  = "FDAI_ISOLATED_EXECUTOR_HEALTH_PORT"
        value = tostring(var.health_port)
      }
      env {
        name        = "FDAI_STATE_STORE_DSN"
        secret_name = "state-store-dsn"
      }
      env {
        name        = "FDAI_RESOURCE_LOCK_DSN"
        secret_name = "state-store-dsn"
      }

      startup_probe {
        transport               = "HTTP"
        port                    = var.health_port
        path                    = "/ready"
        interval_seconds        = 5
        timeout                 = 2
        failure_count_threshold = 30
      }

      liveness_probe {
        transport               = "HTTP"
        port                    = var.health_port
        path                    = "/live"
        initial_delay           = 5
        interval_seconds        = 30
        timeout                 = 5
        failure_count_threshold = 3
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = var.health_port
        path                    = "/ready"
        initial_delay           = 1
        interval_seconds        = 10
        timeout                 = 3
        failure_count_threshold = 3
        success_count_threshold = 1
      }
    }
  }

  tags = merge(var.tags, {
    "azd-service-name" = "isolated-executor"
    "fdai:mode"        = "shadow"
  })
}

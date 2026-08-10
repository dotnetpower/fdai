resource "azurerm_container_app" "service" {
  name                         = var.name
  container_app_environment_id = var.platform.container_app_environment_id
  resource_group_name          = var.platform.resource_group_name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = var.identity_ids
  }

  dynamic "registry" {
    for_each = var.platform.acr_login_server == "" ? [] : [var.platform.acr_login_server]
    content {
      server   = registry.value
      identity = var.registry_identity_id
    }
  }

  dynamic "secret" {
    for_each = { for item in nonsensitive(var.secrets) : item.name => item }
    content {
      name                = secret.value.name
      identity            = secret.value.identity
      key_vault_secret_id = secret.value.key_vault_secret_id
    }
  }

  dynamic "ingress" {
    for_each = var.ingress == null ? [] : [var.ingress]
    content {
      external_enabled           = ingress.value.external_enabled
      allow_insecure_connections = false
      target_port                = ingress.value.target_port
      transport                  = ingress.value.transport

      traffic_weight {
        latest_revision = true
        percentage      = 100
      }
    }
  }

  template {
    revision_suffix = "p${formatdate("YYYYMMDDhhmmss", plantimestamp())}"
    min_replicas    = var.scaling.min_replicas
    max_replicas    = var.scaling.max_replicas

    container {
      name    = var.component
      image   = var.image
      cpu     = var.scaling.cpu
      memory  = var.scaling.memory
      command = var.command
      args    = var.args

      dynamic "startup_probe" {
        for_each = var.health.startup_path == null ? [] : [var.health.startup_path]
        content {
          transport               = "HTTP"
          port                    = var.health.port
          path                    = startup_probe.value
          interval_seconds        = 5
          timeout                 = var.health.timeout_seconds
          failure_count_threshold = var.health.startup_failure_count
        }
      }

      liveness_probe {
        transport               = var.health.liveness_path == null ? "TCP" : "HTTP"
        port                    = var.health.port
        path                    = var.health.liveness_path
        interval_seconds        = var.health.interval_seconds
        timeout                 = var.health.timeout_seconds
        failure_count_threshold = var.health.failure_count_threshold
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = var.health.port
        path                    = var.health.readiness_path
        interval_seconds        = var.health.interval_seconds
        timeout                 = var.health.timeout_seconds
        failure_count_threshold = var.health.failure_count_threshold
      }

      dynamic "env" {
        for_each = { for item in var.environment : item.name => item }
        content {
          name        = env.value.name
          value       = env.value.value
          secret_name = env.value.secret_name
        }
      }
    }

    dynamic "container" {
      for_each = { for sidecar in var.sidecars : sidecar.name => sidecar }
      content {
        name    = container.value.name
        image   = container.value.image
        cpu     = container.value.cpu
        memory  = container.value.memory
        command = container.value.command
        args    = container.value.args

        dynamic "startup_probe" {
          for_each = container.value.startup_probe == null ? [] : [container.value.startup_probe]
          content {
            transport               = startup_probe.value.transport
            port                    = startup_probe.value.port
            path                    = startup_probe.value.path
            interval_seconds        = startup_probe.value.interval_seconds
            timeout                 = startup_probe.value.timeout_seconds
            failure_count_threshold = startup_probe.value.failure_count_threshold
          }
        }

        dynamic "liveness_probe" {
          for_each = container.value.liveness_probe == null ? [] : [container.value.liveness_probe]
          content {
            transport               = liveness_probe.value.transport
            port                    = liveness_probe.value.port
            path                    = liveness_probe.value.path
            interval_seconds        = liveness_probe.value.interval_seconds
            timeout                 = liveness_probe.value.timeout_seconds
            failure_count_threshold = liveness_probe.value.failure_count_threshold
          }
        }

        dynamic "readiness_probe" {
          for_each = container.value.readiness_probe == null ? [] : [container.value.readiness_probe]
          content {
            transport               = readiness_probe.value.transport
            port                    = readiness_probe.value.port
            path                    = readiness_probe.value.path
            interval_seconds        = readiness_probe.value.interval_seconds
            timeout                 = readiness_probe.value.timeout_seconds
            failure_count_threshold = readiness_probe.value.failure_count_threshold
          }
        }
      }
    }
  }

  tags = merge(var.tags, {
    "fdai:component"         = var.component
    "fdai:rollback-strategy" = var.rollback_strategy
  })

  lifecycle {
    precondition {
      condition     = length(var.identity_ids) > 0 && alltrue([for id in var.identity_ids : id != ""])
      error_message = "At least one non-empty workload identity resource id is required."
    }
    precondition {
      condition = (
        var.health.liveness_path == null || startswith(var.health.liveness_path, "/")
      ) && startswith(var.health.readiness_path, "/")
      error_message = "Configured HTTP health paths must be absolute."
    }
    precondition {
      condition     = var.health.liveness_path == null || var.health.liveness_path != var.health.readiness_path
      error_message = "HTTP liveness and readiness paths must be distinct."
    }
  }
}

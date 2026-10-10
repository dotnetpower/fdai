locals {
  github_app = var.github.token_secret_id == ""
  github_secrets = local.github_app ? [{
    name                = "github-app-private-key"
    identity            = var.identity.resource_id
    key_vault_secret_id = var.github.app_private_key_secret_id
    }] : [{
    name                = "github-token"
    identity            = var.identity.resource_id
    key_vault_secret_id = var.github.token_secret_id
  }]
}

resource "azurerm_container_app" "worker" {
  name                         = var.name
  container_app_environment_id = var.platform.container_app_environment_id
  resource_group_name          = var.platform.resource_group_name
  revision_mode                = "Single"
  max_inactive_revisions       = 2
  workload_profile_name        = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity.resource_id]
  }

  dynamic "registry" {
    for_each = var.platform.acr_login_server == "" ? [] : [var.platform.acr_login_server]
    content {
      server   = registry.value
      identity = var.identity.resource_id
    }
  }

  secret {
    name                = "database-dsn"
    identity            = var.identity.resource_id
    key_vault_secret_id = var.database.dsn_secret_id
  }

  dynamic "secret" {
    for_each = { for item in nonsensitive(local.github_secrets) : item.name => item }
    content {
      name                = secret.value.name
      identity            = secret.value.identity
      key_vault_secret_id = secret.value.key_vault_secret_id
    }
  }

  template {
    revision_suffix = "p${formatdate("YYYYMMDDhhmmss", plantimestamp())}"
    min_replicas    = 1
    max_replicas    = 1

    volume {
      name         = "cache"
      storage_name = var.cache.storage_name
      storage_type = "AzureFile"
    }

    volume {
      name         = "work"
      storage_type = "EmptyDir"
    }

    container {
      name    = "code-security-worker"
      image   = var.image
      cpu     = var.resources.cpu
      memory  = var.resources.memory
      command = ["/usr/local/bin/fdai-scan-runner"]
      args = [
        "serve-workers",
        "--state-access",
        "restricted",
        "--work-root",
        "/work",
        "--kafka-bootstrap-servers",
        var.platform.kafka_bootstrap_servers,
        "--request-interval-seconds",
        tostring(var.worker.request_interval_seconds),
        "--schedule-interval-seconds",
        tostring(var.worker.schedule_interval_seconds),
        "--max-requests",
        tostring(var.worker.max_requests),
        "--max-repositories",
        tostring(var.worker.max_repositories),
      ]

      env {
        name        = "FDAI_STATE_STORE_DSN"
        secret_name = "database-dsn"
      }
      env {
        name  = "POSTGRES_HOST"
        value = var.database.host
      }
      env {
        name  = "FDAI_DATABASE_ROLE"
        value = var.database.role
      }
      env {
        name  = "PGOPTIONS"
        value = "-c role=${var.database.role}"
      }
      env {
        name  = "FDAI_EXECUTION_VENUE"
        value = "deployed"
      }
      env {
        name  = "RUNTIME_ENV"
        value = var.runtime_env
      }
      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = var.identity.client_id
      }
      env {
        name  = "FDAI_SCAN_CACHE"
        value = var.cache.path
      }
      env {
        name  = "FDAI_KAFKA_BOOTSTRAP_SERVERS"
        value = var.platform.kafka_bootstrap_servers
      }
      env {
        name  = "HOME"
        value = "/tmp"
      }

      dynamic "env" {
        for_each = local.github_app ? {
          FDAI_GITHUB_APP_CLIENT_ID       = var.github.app_client_id
          FDAI_GITHUB_APP_INSTALLATION_ID = var.github.app_installation_id
        } : {}
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name        = local.github_app ? "FDAI_GITHUB_APP_PRIVATE_KEY" : "FDAI_GITOPS_TOKEN"
        secret_name = local.github_app ? "github-app-private-key" : "github-token"
      }

      volume_mounts {
        name = "cache"
        path = "/cache"
      }

      volume_mounts {
        name = "work"
        path = "/work"
      }
    }
  }

  tags = merge(var.tags, {
    "fdai:component"         = "code-security-worker"
    "fdai:database-role"     = var.database.role
    "fdai:execution-venue"   = "deployed"
    "fdai:serialized-worker" = "true"
  })

  lifecycle {
    precondition {
      condition     = var.database.role == "fdai_code_security_worker"
      error_message = "The worker must use the restricted code-security database role."
    }
    precondition {
      condition     = can(regex("@sha256:[0-9a-f]{64}$", var.image))
      error_message = "The scanner image must be pinned by sha256 digest."
    }
  }
}

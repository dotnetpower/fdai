# FDAI operator console read API - Azure Container App (+ migration job).
#
# Serves the read-only console API (`fdai.delivery.read_api.prod:app`) with
# external ingress so the layer-3 console SPA (Azure Static Web App) can call
# it cross-origin. The SPA is read-only; this API enforces Entra JWT auth +
# RBAC group resolution (see `src/fdai/delivery/read_api/prod.py`).
#
# The API is stateless: it projects audit / KPI / HIL-queue / ontology / views
# from the persisted Postgres state store. The read identity pulls the image,
# resolves the DSN, and reads Azure state. A separate command identity owns
# Event Hubs send/receive for proposals, HIL decisions, and live projections.
#
# A one-off manual-trigger Container Apps Job runs `alembic upgrade head`
# against the same state store using the same image (alembic is bundled into
# the runtime image). The deploy workflow starts it after apply.

resource "azurerm_container_app" "read_api" {
  name                         = var.name
  container_app_environment_id = var.container_app_environment_id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [var.read_api_identity_id, var.command_api_identity_id]
  }

  dynamic "registry" {
    for_each = var.acr_login_server == "" ? toset([]) : toset(["1"])
    content {
      server   = var.acr_login_server
      identity = var.read_api_identity_id
    }
  }

  # Postgres DSN (read-only projection) sourced from the same Key Vault secret
  # the core app uses. The executor MI already holds Key Vault Secrets User.
  secret {
    name                = "dsn"
    identity            = var.read_api_identity_id
    key_vault_secret_id = var.state_store_dsn_secret_id
  }

  dynamic "secret" {
    for_each = nonsensitive(var.chatops_webhook_secret_id) == "" ? toset([]) : toset(["1"])
    content {
      name                = "chatops-webhook-secret"
      identity            = var.read_api_identity_id
      key_vault_secret_id = var.chatops_webhook_secret_id
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = "readapi"
      image  = var.image
      cpu    = var.cpu
      memory = var.memory

      # The runtime image ENTRYPOINT is `python -m fdai` (the headless core).
      # Override it to run the ASGI server. `app` is a factory, so `--factory`
      # is required.
      command = ["uvicorn"]
      args = [
        "fdai.delivery.read_api.prod:app",
        "--factory",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
      ]

      env {
        name        = "FDAI_DATABASE_URL"
        secret_name = "dsn"
      }
      dynamic "env" {
        for_each = nonsensitive(var.chatops_webhook_secret_id) == "" ? toset([]) : toset(["1"])
        content {
          name        = "FDAI_CHATOPS_WEBHOOK_SECRET"
          secret_name = "chatops-webhook-secret"
        }
      }
      env {
        name  = "FDAI_ENTRA_TENANT_ID"
        value = var.entra_tenant_id
      }
      env {
        name  = "FDAI_API_AUDIENCE"
        value = var.api_audience
      }
      env {
        name  = "FDAI_RBAC_READERS_GROUP_ID"
        value = var.rbac_readers_group_id
      }
      env {
        name  = "FDAI_RBAC_CONTRIBUTORS_GROUP_ID"
        value = var.rbac_contributors_group_id
      }
      env {
        name  = "FDAI_RBAC_APPROVERS_GROUP_ID"
        value = var.rbac_approvers_group_id
      }
      env {
        name  = "FDAI_RBAC_OWNERS_GROUP_ID"
        value = var.rbac_owners_group_id
      }
      env {
        name  = "FDAI_RBAC_BREAK_GLASS_GROUP_ID"
        value = var.rbac_break_glass_group_id
      }
      env {
        name  = "FDAI_READ_API_CORS_ALLOW_ORIGINS"
        value = var.cors_allow_origins
      }
      dynamic "env" {
        for_each = var.iam_directory_provider == "" ? [] : [var.iam_directory_provider]
        content {
          name  = "FDAI_IAM_DIRECTORY_PROVIDER"
          value = env.value
        }
      }
      dynamic "env" {
        for_each = var.python_task_author_endpoint == "" ? [] : [var.python_task_author_endpoint]
        content {
          name  = "FDAI_PYTHON_TASK_AUTHOR_ENDPOINT"
          value = env.value
        }
      }
      dynamic "env" {
        for_each = var.kafka_bootstrap_servers == "" ? [] : [var.kafka_bootstrap_servers]
        content {
          name  = "FDAI_KAFKA_BOOTSTRAP_SERVERS"
          value = env.value
        }
      }
      dynamic "env" {
        for_each = var.kafka_topic_events == "" ? [] : [var.kafka_topic_events]
        content {
          name  = "KAFKA_TOPIC_EVENTS"
          value = env.value
        }
      }
      env {
        name  = "AZURE_SUBSCRIPTION_ID"
        value = var.azure_subscription_id
      }
      env {
        name  = "AZURE_RESOURCE_GROUP"
        value = var.azure_resource_group
      }
      env {
        name  = "FDAI_EXECUTOR_PRINCIPAL_ID"
        value = var.executor_principal_id
      }
      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = var.read_api_identity_client_id
      }
      dynamic "env" {
        for_each = var.monitor_workspace_customer_id == "" ? [] : [var.monitor_workspace_customer_id]
        content {
          name  = "FDAI_MONITOR_WORKSPACE_ID"
          value = env.value
        }
      }
      env {
        name  = "FDAI_COMMAND_MI_CLIENT_ID"
        value = var.command_api_identity_client_id
      }
      dynamic "env" {
        for_each = var.resolved_models_path == "" ? [] : [var.resolved_models_path]
        content {
          name  = "LLM_RESOLVED_MODELS_PATH"
          value = env.value
        }
      }
      env {
        name  = "FDAI_NARRATOR_PROBE_INTERVAL_SECONDS"
        value = tostring(var.narrator_probe_interval_seconds)
      }
      dynamic "env" {
        for_each = var.web_search_enabled ? [1] : []
        content {
          name  = "FDAI_WEB_SEARCH_ENABLED"
          value = "true"
        }
      }
      dynamic "env" {
        for_each = var.web_search_enabled ? [1] : []
        content {
          name  = "FDAI_WEB_SEARCH_ALLOWED_DOMAINS"
          value = join(",", var.web_search_allowed_domains)
        }
      }
      dynamic "env" {
        for_each = var.web_search_enabled ? [1] : []
        content {
          name  = "FDAI_WEB_SEARCH_MAX_RESULTS"
          value = tostring(var.web_search_max_results)
        }
      }
      dynamic "env" {
        for_each = var.web_search_enabled ? [1] : []
        content {
          name  = "FDAI_WEB_SEARCH_BUDGET_MS"
          value = tostring(var.web_search_budget_ms)
        }
      }
      dynamic "env" {
        for_each = var.web_search_enabled ? [1] : []
        content {
          name  = "FDAI_WEB_SEARCH_PROBE_INTERVAL_SECONDS"
          value = tostring(var.web_search_probe_interval_seconds)
        }
      }
      env {
        name  = "FDAI_EXECUTOR_EVENT_ROLE_DEFINITION_ID"
        value = var.executor_event_role_definition_id
      }
      env {
        name  = "FDAI_EXECUTOR_SECRET_ROLE_DEFINITION_ID"
        value = var.executor_secret_role_definition_id
      }
      dynamic "env" {
        for_each = var.python_task_author_deployment == "" ? [] : [var.python_task_author_deployment]
        content {
          name  = "FDAI_PYTHON_TASK_AUTHOR_DEPLOYMENT"
          value = env.value
        }
      }
      env {
        name  = "FDAI_INVENTORY_FRESHNESS_SECONDS"
        value = tostring(var.inventory_freshness_seconds)
      }
    }
  }

  tags = var.tags
}

# One-off schema migration job (manual trigger). Runs `alembic upgrade head`
# against the state store using the bundled alembic revisions. The deploy
# workflow starts this after apply; it is idempotent (no-op when head is
# already applied).
resource "azurerm_container_app_job" "migrate" {
  name                         = var.migrate_job_name
  container_app_environment_id = var.container_app_environment_id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 600
  replica_retry_limit          = 1

  identity {
    type         = "UserAssigned"
    identity_ids = [var.read_api_identity_id]
  }

  dynamic "registry" {
    for_each = var.acr_login_server == "" ? toset([]) : toset(["1"])
    content {
      server   = var.acr_login_server
      identity = var.read_api_identity_id
    }
  }

  secret {
    name                = "dsn"
    identity            = var.read_api_identity_id
    key_vault_secret_id = var.state_store_dsn_secret_id
  }

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name    = "migrate"
      image   = var.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["alembic"]
      args    = ["upgrade", "head"]

      env {
        name        = "FDAI_DATABASE_URL"
        secret_name = "dsn"
      }
    }
  }

  tags = var.tags
}

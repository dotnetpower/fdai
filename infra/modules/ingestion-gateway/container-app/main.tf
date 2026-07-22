resource "azurerm_container_app" "ingestion" {
  name                         = var.name
  container_app_environment_id = var.container_app_environment_id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  dynamic "registry" {
    for_each = var.acr_login_server == "" ? [] : [1]
    content {
      server   = var.acr_login_server
      identity = var.identity_id
    }
  }

  secret {
    name                = "database-dsn"
    identity            = var.identity_id
    key_vault_secret_id = var.database_dsn_secret_id
  }

  dynamic "secret" {
    for_each = var.stewardship_governance_enabled ? [1] : []
    content {
      name                = "gitops-token"
      identity            = var.identity_id
      key_vault_secret_id = var.gitops_token_secret_id
    }
  }

  dynamic "secret" {
    for_each = var.stewardship_governance_enabled ? [1] : []
    content {
      name                = "github-webhook-secret"
      identity            = var.identity_id
      key_vault_secret_id = var.github_webhook_secret_id
    }
  }

  dynamic "secret" {
    for_each = var.stewardship_governance_enabled ? [1] : []
    content {
      name                = "chatops-webhook-url"
      identity            = var.identity_id
      key_vault_secret_id = var.chatops_webhook_url_secret_id
    }
  }

  ingress {
    external_enabled           = true
    allow_insecure_connections = false
    target_port                = 8000
    transport                  = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = "ingestion"
      image  = var.image
      cpu    = var.gateway_cpu
      memory = var.gateway_memory

      command = ["uvicorn"]
      args = [
        "fdai.delivery.ingestion_gateway.prod:app",
        "--factory",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
      ]

      env {
        name        = "FDAI_DATABASE_URL"
        secret_name = "database-dsn"
      }
      dynamic "env" {
        for_each = var.stewardship_governance_enabled ? [1] : []
        content {
          name  = "FDAI_STEWARDSHIP_GOVERNANCE_ENABLED"
          value = "1"
        }
      }
      dynamic "env" {
        for_each = var.stewardship_governance_enabled ? [1] : []
        content {
          name        = "FDAI_GITOPS_TOKEN"
          secret_name = "gitops-token"
        }
      }
      dynamic "env" {
        for_each = var.stewardship_governance_enabled ? [1] : []
        content {
          name        = "FDAI_GITHUB_WEBHOOK_SECRET"
          secret_name = "github-webhook-secret"
        }
      }
      dynamic "env" {
        for_each = var.stewardship_governance_enabled ? [1] : []
        content {
          name        = "FDAI_CHATOPS_WEBHOOK_URL"
          secret_name = "chatops-webhook-url"
        }
      }
      dynamic "env" {
        for_each = var.stewardship_governance_enabled ? [1] : []
        content {
          name  = "FDAI_GITOPS_OWNER"
          value = var.gitops_owner
        }
      }
      dynamic "env" {
        for_each = var.stewardship_governance_enabled ? [1] : []
        content {
          name  = "FDAI_GITOPS_REPO"
          value = var.gitops_repo
        }
      }
      dynamic "env" {
        for_each = var.stewardship_governance_enabled ? [1] : []
        content {
          name  = "FDAI_STEWARDSHIP_REQUIRE_BINDINGS"
          value = "1"
        }
      }
      dynamic "env" {
        for_each = var.stewardship_governance_enabled ? [1] : []
        content {
          name  = "FDAI_MAINTAINERS"
          value = var.stewardship_maintainers
        }
      }
      dynamic "env" {
        for_each = var.stewardship_governance_enabled ? var.stewardship_agent_bindings : {}
        content {
          name  = "FDAI_STEWARD_${upper(env.key)}"
          value = env.value
        }
      }
      env {
        name  = "RUNTIME_ENV"
        value = var.runtime_env
      }
      env {
        name  = "FDAI_MI_CLIENT_ID"
        value = var.identity_client_id
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
        name  = "FDAI_INGESTION_CORS_ALLOW_ORIGINS"
        value = var.cors_allow_origins
      }
      env {
        name  = "FDAI_ADLS_ACCOUNT_NAME"
        value = var.adls_account_name
      }
      env {
        name  = "FDAI_ADLS_ACCOUNT_URL"
        value = var.adls_account_url
      }
      env {
        name  = "FDAI_ADLS_SOURCE_FILE_SYSTEM"
        value = var.adls_source_file_system
      }
      env {
        name  = "FDAI_ADLS_DERIVED_FILE_SYSTEM"
        value = var.adls_derived_file_system
      }
      env {
        name  = "FDAI_EMBEDDING_ENDPOINT"
        value = var.embedding_endpoint
      }
      env {
        name  = "FDAI_EMBEDDING_DEPLOYMENT"
        value = var.embedding_deployment
      }
      env {
        name  = "FDAI_EMBEDDING_DIM"
        value = tostring(var.embedding_dim)
      }
      env {
        name  = "FDAI_KAFKA_BOOTSTRAP_SERVERS"
        value = var.kafka_bootstrap_servers
      }
      env {
        name  = "FDAI_DOCUMENT_EVENT_TOPIC"
        value = var.document_event_topic
      }
      env {
        name  = "FDAI_CLAMAV_HOST"
        value = "127.0.0.1"
      }
      env {
        name  = "FDAI_CLAMAV_PORT"
        value = "3310"
      }
      env {
        name  = "FDAI_DOCUMENT_MAX_FILE_SIZE"
        value = tostring(var.max_file_size_bytes)
      }
      env {
        name  = "FDAI_DOCUMENT_MAX_BATCH_COUNT"
        value = tostring(var.max_batch_count)
      }
      env {
        name  = "FDAI_DOCUMENT_CHUNK_MAX_CHARS"
        value = tostring(var.chunk_max_chars)
      }
      env {
        name  = "FDAI_DOCUMENT_CHUNK_OVERLAP"
        value = tostring(var.chunk_overlap)
      }
      env {
        name  = "FDAI_DOCUMENT_INDEXING_STAGE_TIMEOUT_SECONDS"
        value = tostring(var.indexing_stage_timeout_seconds)
      }
      env {
        name  = "FDAI_DOCUMENT_POLICY_VERSION"
        value = var.policy_version
      }
      env {
        name  = "FDAI_DOCUMENT_COLLECTIONS"
        value = var.document_collections
      }
    }

    container {
      name   = "clamav"
      image  = var.clamav_image
      cpu    = var.clamav_cpu
      memory = var.clamav_memory
    }
  }

  tags = var.tags
}

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
    identity_ids = [var.identity_id]
  }

  dynamic "registry" {
    for_each = var.acr_login_server == "" ? [] : [1]
    content {
      server   = var.acr_login_server
      identity = var.identity_id
    }
  }

  secret {
    name                = "database-dsn"
    identity            = var.identity_id
    key_vault_secret_id = var.database_dsn_secret_id
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
        secret_name = "database-dsn"
      }
    }
  }

  tags = var.tags
}

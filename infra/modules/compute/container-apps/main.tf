resource "azurerm_container_app_environment" "primary" {
  name                       = var.env_name
  location                   = var.location
  resource_group_name        = var.resource_group_name
  log_analytics_workspace_id = var.log_workspace_id
  # VNet integration for private-networking tenants: when a delegated infra
  # subnet is supplied the environment joins the VNet, so the app's Key Vault
  # references resolve the KV private endpoint. Null keeps the public (no-VNet)
  # environment used on an unrestricted tenant.
  infrastructure_subnet_id = var.infrastructure_subnet_id
  tags                     = var.tags
}

# ---------------------------------------------------------------------------
# Shared env-var map for every container / job running the fdai image.
#
# The image's entry point calls `default_container_from_env()` which
# refuses to boot when any required (non-secret) config env var is unset
# (see `EnvVarConfigProvider._ENV_VAR_MAP`). We reuse the same map on the
# core app AND the OOB / rule-watcher / dr-drill jobs so a scheduled
# replica does not crash-loop on `ConfigError` while the primary revision
# runs fine.
# ---------------------------------------------------------------------------
locals {
  core_config_env = {
    AZURE_TENANT_ID         = var.azure_tenant_id
    AZURE_SUBSCRIPTION_ID   = var.azure_subscription_id
    AZURE_RESOURCE_GROUP    = var.azure_resource_group
    AZURE_REGION            = var.azure_region
    KAFKA_BOOTSTRAP_SERVERS = var.kafka_bootstrap_servers
    KAFKA_TOPIC_EVENTS      = var.kafka_topic_events
    POSTGRES_HOST           = var.postgres_host
    POSTGRES_DATABASE       = var.postgres_database
    RUNTIME_ENV             = var.runtime_env
    AUTONOMY_MODE_DEFAULT   = var.autonomy_mode_default
  }
}

# Unified core app. Sidecars for trust-router / executor / audit-writer land as
# additional `container {}` blocks (localhost IPC) - see deploy-and-onboard.md
# § Compute Shape. Day-zero manifest keeps the single container as a placeholder.
resource "azurerm_container_app" "core" {
  name                         = var.core_app_name
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = concat([var.executor_identity_id], var.extra_identity_ids)
  }

  # -------------------------------------------------------------------------
  # ACR registry auth via user-assigned MI.
  #
  # Set `acr_login_server` (e.g. "crfdaidev.azurecr.io") when the image
  # comes from a private ACR; Container Apps then uses the executor MI
  # (already granted `AcrPull` at the root module) instead of admin
  # credentials. Empty string means the image is public (MCR / Docker
  # Hub) and no auth is needed - the upstream default day-zero image is
  # `mcr.microsoft.com/azure-cli:latest`, which pulls anonymously.
  # -------------------------------------------------------------------------
  dynamic "registry" {
    for_each = var.acr_login_server == "" ? toset([]) : toset(["1"])
    content {
      server   = var.acr_login_server
      identity = var.executor_identity_id
    }
  }

  # -------------------------------------------------------------------------
  # Secret rotation semantics
  # -------------------------------------------------------------------------
  # `revision_mode = "Single"` means every apply that changes a `secret {}`
  # or `env {}` block rolls a new active revision; the previous one is
  # deactivated once the new one reports healthy. Rotating a Key Vault
  # secret alone (without changing the Container App template) does NOT
  # push the new value to running replicas - a template touch (e.g. bumping
  # a `tags` field or re-applying) is what forces the platform to re-read
  # the KV reference. This matches the platform's documented behaviour and
  # is intentional: audit and rollback are anchored on Container App
  # revisions, not on out-of-band KV changes.
  # -------------------------------------------------------------------------

  # -------------------------------------------------------------------------
  # Key Vault-backed secrets for the three Postgres seams. Each block is
  # created only when the corresponding secret id is supplied - keeps the
  # day-zero (no persistence) manifest valid without conditional variables.
  # -------------------------------------------------------------------------
  dynamic "secret" {
    for_each = var.state_store_dsn_secret_id == "" ? toset([]) : toset(["1"])
    content {
      name                = "state-store-dsn"
      identity            = var.executor_identity_id
      key_vault_secret_id = var.state_store_dsn_secret_id
    }
  }

  dynamic "secret" {
    for_each = var.operator_memory_dsn_secret_id == "" ? toset([]) : toset(["1"])
    content {
      name                = "operator-memory-dsn"
      identity            = var.executor_identity_id
      key_vault_secret_id = var.operator_memory_dsn_secret_id
    }
  }

  dynamic "secret" {
    for_each = var.pattern_library_dsn_secret_id == "" ? toset([]) : toset(["1"])
    content {
      name                = "pattern-library-dsn"
      identity            = var.executor_identity_id
      key_vault_secret_id = var.pattern_library_dsn_secret_id
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = "core"
      image  = var.image
      cpu    = var.core_cpu
      memory = var.core_memory

      # ---------------------------------------------------------------------
      # Required (non-secret) config env vars consumed by
      # `EnvVarConfigProvider` in `src/fdai/shared/config/provider.py`.
      # Missing any of these makes `default_container_from_env()` fail with
      # a `ConfigError` before the P1 control loop starts.
      # ---------------------------------------------------------------------
      dynamic "env" {
        for_each = local.core_config_env
        content {
          name  = env.key
          value = env.value
        }
      }

      # `python -m fdai` starts the Kafka consumer only when
      # FDAI_START_CONSUMER is truthy. Without this env the Container
      # App boots cleanly but never subscribes to the event bus - a
      # silent no-op deploy that only the KPI dashboard would surface.
      # The OOB / DR-drill / rule-watcher jobs run their own CLI entry
      # points, so this flag is scoped to the core app only.
      env {
        name  = "FDAI_START_CONSUMER"
        value = "1"
      }

      dynamic "env" {
        for_each = var.state_store_dsn_secret_id == "" ? toset([]) : toset(["1"])
        content {
          name        = "FDAI_STATE_STORE_DSN"
          secret_name = "state-store-dsn"
        }
      }

      dynamic "env" {
        for_each = var.operator_memory_dsn_secret_id == "" ? toset([]) : toset(["1"])
        content {
          name        = "FDAI_OPERATOR_MEMORY_DSN"
          secret_name = "operator-memory-dsn"
        }
      }

      dynamic "env" {
        for_each = var.pattern_library_dsn_secret_id == "" ? toset([]) : toset(["1"])
        content {
          name        = "FDAI_T1_PATTERN_LIBRARY_DSN"
          secret_name = "pattern-library-dsn"
        }
      }
    }
  }

  tags = var.tags
}

# Out-of-band scheduled probes (cost anomalies, change detection sweep, etc.).
resource "azurerm_container_app_job" "oob" {
  name                         = var.oob_job_name
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  replica_timeout_in_seconds   = 300
  replica_retry_limit          = 3

  identity {
    type         = "UserAssigned"
    identity_ids = concat([var.executor_identity_id], var.extra_identity_ids)
  }

  schedule_trigger_config {
    cron_expression          = "0 * * * *"
    replica_completion_count = 1
    parallelism              = 1
  }

  template {
    container {
      name   = "oob"
      image  = var.image
      cpu    = var.oob_cpu
      memory = var.oob_memory

      # Same required config env vars as the core app - the OOB job runs
      # the same image and would crash-loop on `ConfigError` without them.
      dynamic "env" {
        for_each = local.core_config_env
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  tags = var.tags
}


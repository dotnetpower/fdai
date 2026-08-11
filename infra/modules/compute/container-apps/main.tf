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

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
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
    AZURE_TENANT_ID                    = var.azure_tenant_id
    AZURE_SUBSCRIPTION_ID              = var.azure_subscription_id
    AZURE_RESOURCE_GROUP               = var.azure_resource_group
    AZURE_REGION                       = var.azure_region
    KAFKA_BOOTSTRAP_SERVERS            = var.kafka_bootstrap_servers
    KAFKA_TOPIC_EVENTS                 = var.kafka_topic_events
    POSTGRES_HOST                      = var.postgres_host
    POSTGRES_DATABASE                  = var.postgres_database
    RUNTIME_ENV                        = var.runtime_env
    AUTONOMY_MODE_DEFAULT              = var.autonomy_mode_default
    FDAI_STARTUP_KAFKA_SETTLE_SECONDS  = tostring(var.startup_kafka_settle_seconds)
    FDAI_STARTUP_PROBE_TIMEOUT_SECONDS = tostring(var.startup_probe_timeout_seconds)
    FDAI_STARTUP_PHASE_TIMEOUT_SECONDS = tostring(var.startup_phase_timeout_seconds)
  }

  # Optional env-vars: attached only when their upstream input is
  # non-empty so a fork opting out (leaving the default "") emits no
  # env entry at all. Merged into the containers below via
  # ``merge(local.core_config_env, local.optional_config_env)``.
  optional_config_env = merge(
    var.monitor_workspace_customer_id == "" ? {} : {
      # Read by ``__main__._finalize_llm_bindings`` -> ``wire_azure_container``
      # to auto-bind ``AzureMonitorLogsMetricProvider`` in place of the
      # upstream ``NoopMetricProvider``. See
      # src/fdai/composition/wire_azure.py.
      FDAI_MONITOR_WORKSPACE_ID = var.monitor_workspace_customer_id
    },
    var.case_history_container_url == "" ? {} : {
      FDAI_CASE_HISTORY_CONTAINER_URL  = var.case_history_container_url
      FDAI_CASE_HISTORY_MI_CLIENT_ID   = var.case_history_identity_client_id
      FDAI_CASE_HISTORY_RETENTION_DAYS = tostring(var.case_history_retention_days)
      FDAI_CASE_HISTORY_DELETION_DAYS  = tostring(var.case_history_deletion_days)
    },
    var.prometheus_endpoint == "" ? {} : {
      # Read by the same helper to bind ``PrometheusMetricProvider`` as
      # the primary route (Prom-first, AML-fallback via
      # ``RoutedMetricProvider``). AKS Managed Prometheus over AAD
      # requires the audience below; self-hosted Prom leaves it empty.
      FDAI_PROMETHEUS_ENDPOINT = var.prometheus_endpoint
    },
    var.prometheus_audience == "" ? {} : {
      FDAI_PROMETHEUS_AUDIENCE = var.prometheus_audience
    },
    var.forecast_targets_json == "" ? {} : {
      FDAI_FORECAST_TARGETS_JSON = var.forecast_targets_json
    },
    var.vm_task_enabled ? {
      FDAI_VM_TASK_ENABLED     = "1"
      FDAI_VM_TASK_RUN_AS_USER = var.vm_task_run_as_user
      FDAI_VM_TASK_ROOT        = var.vm_task_root
    } : {},
    var.vm_task_enforce ? {
      FDAI_VM_TASK_ENFORCE = "1"
    } : {},
    var.email_endpoint == "" ? {} : {
      FDAI_EMAIL_ENDPOINT                 = var.email_endpoint
      FDAI_EMAIL_SENDER_ADDRESS           = var.email_sender_address
      FDAI_EMAIL_RECIPIENT_ADDRESSES_JSON = var.email_recipient_addresses_json
      FDAI_NOTIFICATION_MI_CLIENT_ID      = var.notification_identity_client_id
    },
    var.console_base_url == "" ? {} : {
      FDAI_CONSOLE_BASE_URL = var.console_base_url
    },
    var.dev_operations_gateway_url == "" ? {} : {
      FDAI_DEV_OPERATIONS_GATEWAY_URL      = var.dev_operations_gateway_url
      FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE = var.dev_operations_gateway_audience
    },
    var.operational_kafka_bootstrap_servers == "" ? {} : {
      FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS = var.operational_kafka_bootstrap_servers
    },
    var.semantic_turn_request_topic == "" || var.semantic_turn_projection_topic == "" ? {} : {
      FDAI_SEMANTIC_TURN_REQUEST_TOPIC    = var.semantic_turn_request_topic
      FDAI_SEMANTIC_TURN_PROJECTION_TOPIC = var.semantic_turn_projection_topic
    },
    var.isolated_executor_authority_cutover ? {
      FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER = "1"
    } : {},
  )
}

# Bounded compatibility placeholder for a future OOB probe entry point.
# Dedicated inventory, scheduler, analyzer, forecast, watcher, and canary Jobs
# own the implemented scheduled work. Keep this Job inert so the runtime image's
# long-running core entry point is never launched under a five-minute Job budget.
resource "azurerm_container_app_job" "oob" {
  name                         = var.oob_job_name
  container_app_environment_id = azurerm_container_app_environment.primary.id
  resource_group_name          = var.resource_group_name
  location                     = var.location
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 300
  replica_retry_limit          = 3

  identity {
    type         = "UserAssigned"
    identity_ids = concat([var.executor_identity_id], var.extra_identity_ids)
  }

  dynamic "registry" {
    for_each = var.acr_login_server == "" ? toset([]) : toset(["1"])
    content {
      server   = var.acr_login_server
      identity = var.executor_identity_id
    }
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
      command = [
        "/bin/echo",
        "oob_job_reserved",
      ]

      # Same required config env vars as the core app - the OOB job runs
      # the same image and would crash-loop on `ConfigError` without them.
      # Optional adapter-wiring env vars are threaded through with the
      # same merge so the OOB job sees the same live-vs-noop bindings.
      dynamic "env" {
        for_each = merge(local.core_config_env, local.optional_config_env)
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  tags = var.tags
}

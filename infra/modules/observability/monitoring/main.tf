# Monitoring module - action group + metric alerts + diagnostic settings for
# the control-plane resources. Opt-in (root `enable_monitoring`); a day-zero
# deploy stays alert-free until an operator wires an alert destination.
#
# All alerts ship muted-by-severity friendly: they fire to the action group
# (email + optional webhook) and never take an autonomous action - they are a
# human signal, consistent with the risk-gated-autonomy principle.
#
# Design: docs/roadmap/rules-and-detection/observability-and-detection.md + deploy-and-onboard.md.

locals {
  # Metric alert specs, data-driven so adding one is a single map entry. Each
  # targets a resource id passed from the root and uses documented Azure
  # Monitor metric names for that resource type.
  alerts = merge(
    var.postgres_id == "" ? {} : {
      pg_cpu = {
        scope       = var.postgres_id
        namespace   = "Microsoft.DBforPostgreSQL/flexibleServers"
        metric      = "cpu_percent"
        aggregation = "Average"
        operator    = "GreaterThan"
        threshold   = var.postgres_cpu_threshold
        severity    = 2
        description = "Postgres CPU high"
      }
      pg_storage = {
        scope       = var.postgres_id
        namespace   = "Microsoft.DBforPostgreSQL/flexibleServers"
        metric      = "storage_percent"
        aggregation = "Average"
        operator    = "GreaterThan"
        threshold   = 85
        severity    = 1
        description = "Postgres storage near full"
      }
      pg_memory = {
        scope       = var.postgres_id
        namespace   = "Microsoft.DBforPostgreSQL/flexibleServers"
        metric      = "memory_percent"
        aggregation = "Average"
        operator    = "GreaterThan"
        threshold   = 90
        severity    = 2
        description = "Postgres memory high"
      }
      pg_conn = {
        scope       = var.postgres_id
        namespace   = "Microsoft.DBforPostgreSQL/flexibleServers"
        metric      = "active_connections"
        aggregation = "Average"
        operator    = "GreaterThan"
        threshold   = var.postgres_connection_threshold
        severity    = 3
        description = "Postgres connection count high"
      }
    },
    var.key_vault_id == "" ? {} : {
      kv_availability = {
        scope       = var.key_vault_id
        namespace   = "Microsoft.KeyVault/vaults"
        metric      = "Availability"
        aggregation = "Average"
        operator    = "LessThan"
        threshold   = 99
        severity    = 1
        description = "Key Vault availability degraded"
      }
      kv_saturation = {
        scope       = var.key_vault_id
        namespace   = "Microsoft.KeyVault/vaults"
        metric      = "SaturationShoebox"
        aggregation = "Average"
        operator    = "GreaterThan"
        threshold   = 75
        severity    = 2
        description = "Key Vault approaching its transaction cap"
      }
    },
    var.event_hub_namespace_id == "" ? {} : {
      eh_throttled = {
        scope       = var.event_hub_namespace_id
        namespace   = "Microsoft.EventHub/namespaces"
        metric      = "ThrottledRequests"
        aggregation = "Total"
        operator    = "GreaterThan"
        threshold   = 0
        severity    = 2
        description = "Event Hubs throttling (raise throughput units)"
      }
      eh_errors = {
        scope       = var.event_hub_namespace_id
        namespace   = "Microsoft.EventHub/namespaces"
        metric      = "ServerErrors"
        aggregation = "Total"
        operator    = "GreaterThan"
        threshold   = 0
        severity    = 2
        description = "Event Hubs server errors"
      }
    },
    var.container_app_id == "" ? {} : {
      ca_restarts = {
        scope       = var.container_app_id
        namespace   = "Microsoft.App/containerApps"
        metric      = "RestartCount"
        aggregation = "Maximum"
        operator    = "GreaterThan"
        threshold   = var.container_app_restart_threshold
        severity    = 2
        description = "Container App restart-looping"
      }
    },
  )

  # Diagnostic-setting targets: stream platform logs + metrics to Log Analytics.
  diag_targets = { for k, v in {
    kv       = var.key_vault_id
    postgres = var.postgres_id
    eventhub = var.event_hub_namespace_id
  } : k => v if v != "" }
}

resource "azurerm_monitor_action_group" "primary" {
  name                = var.action_group_name
  resource_group_name = var.resource_group_name
  short_name          = var.action_group_short_name

  dynamic "email_receiver" {
    for_each = var.alert_email == "" ? [] : [var.alert_email]
    content {
      name                    = "primary-email"
      email_address           = email_receiver.value
      use_common_alert_schema = true
    }
  }

  dynamic "webhook_receiver" {
    for_each = var.alert_webhook_url == "" ? [] : [var.alert_webhook_url]
    content {
      name                    = "primary-webhook"
      service_uri             = webhook_receiver.value
      use_common_alert_schema = true
    }
  }

  tags = var.tags
}

resource "azurerm_monitor_metric_alert" "this" {
  for_each = local.alerts

  name                = "alert-${var.workload}-${each.key}"
  resource_group_name = var.resource_group_name
  scopes              = [each.value.scope]
  description         = each.value.description
  severity            = each.value.severity
  frequency           = "PT5M"
  window_size         = "PT15M"
  auto_mitigate       = true

  criteria {
    metric_namespace = each.value.namespace
    metric_name      = each.value.metric
    aggregation      = each.value.aggregation
    operator         = each.value.operator
    threshold        = each.value.threshold
  }

  action {
    action_group_id = azurerm_monitor_action_group.primary.id
  }

  tags = var.tags
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "consumer_lag" {
  name                    = "alert-${var.workload}-event-bus-consumer-lag"
  resource_group_name     = var.resource_group_name
  location                = var.location
  evaluation_frequency    = "PT5M"
  window_duration         = "PT15M"
  scopes                  = [var.log_analytics_workspace_id]
  severity                = 2
  description             = "Event Bus ingress consumer partition lag exceeds its configured bound"
  display_name            = "Event Bus ingress consumer lag"
  enabled                 = true
  auto_mitigation_enabled = true

  criteria {
    query                   = <<-KQL
      ContainerAppConsoleLogs_CL
      | extend log = parse_json(Log_s)
      | where tostring(log.message) == "event_bus_consumer_progress"
      | where tostring(log.topic) == "aw.change.events"
      | summarize consumer_lag=max(tolong(log.consumer_lag)) by tostring(log.consumer_group), toint(log.partition)
      | where consumer_lag > ${var.event_bus_consumer_lag_threshold}
    KQL
    time_aggregation_method = "Count"
    threshold               = 0
    operator                = "GreaterThan"

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.primary.id]
  }

  tags = var.tags
}

resource "azurerm_monitor_diagnostic_setting" "this" {
  for_each = local.diag_targets

  name                       = "diag-${each.key}"
  target_resource_id         = each.value
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_metric {
    category = "AllMetrics"
  }
}

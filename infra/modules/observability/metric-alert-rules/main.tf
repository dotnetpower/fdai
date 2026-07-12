// Reusable Metric Alert Rule module (opt-in) - one instance per resource /
// metric a fork wants alerted on. Wires the standard "push" detection path:
//
//     azurerm_monitor_metric_alert (this resource)
//       -> azurerm_monitor_action_group (webhook receiver)
//       -> POST to FDAI's azure_monitor_webhook route
//       -> normalize_common_alert_schema()
//       -> Event on the ingest topic (~30-90 s end-to-end)
//
// Kept small and parametrized so a fork instantiates it per (resource,
// metric) pair in its own composition tree:
//
//     module "aks_cpu_alert" {
//       source              = "../../modules/observability/metric-alert-rules"
//       name                = "alert-aks-cpu-over-80"
//       resource_group_name = var.resource_group_name
//       scopes              = [module.aks.id]
//       description         = "AKS node CPU sustained above 80 percent"
//       severity            = 2
//       metric_namespace    = "Microsoft.ContainerService/managedClusters"
//       metric_name         = "node_cpu_usage_percentage"
//       aggregation         = "Average"
//       operator            = "GreaterThan"
//       threshold           = 80
//       window_size         = "PT5M"
//       evaluation_frequency = "PT1M"
//       action_group_ids    = [module.alert_action_group.id]
//       tags                = local.tags
//     }
//
// The Action Group itself is created ONCE per fork (webhook receiver
// pointing at the FDAI ingress) and reused across every alert rule -
// see the sibling `action-group` module for a starter.
//
// Upstream ships zero alert rules. A generic deploy stays on the pull
// path (analyzer_tick_cli + Metrics API + Logs KQL). This module lets
// a fork add push-based alerts one at a time without editing core.

variable "name" {
  description = "CAF-shaped alert rule name (e.g. alert-<workload>-<metric>-<threshold>)."
  type        = string
  validation {
    condition     = length(var.name) > 0 && length(var.name) <= 260
    error_message = "name must be non-empty and <= 260 chars (Azure Monitor limit)."
  }
}

variable "resource_group_name" {
  description = "Resource group hosting the alert rule."
  type        = string
}

variable "scopes" {
  description = "ARM ids of the resources this alert monitors. Typically one target per rule; a batch across resources requires them to share metric_namespace."
  type        = list(string)
  validation {
    condition     = length(var.scopes) >= 1
    error_message = "scopes must contain at least one ARM id."
  }
}

variable "description" {
  description = "Human-readable rule description. Emitted verbatim in the alert payload; keep it English, secret-free, and customer-agnostic per L0 rules."
  type        = string
  default     = ""
}

variable "severity" {
  description = "Alert severity 0..4 (0=critical, 4=verbose). The normalizer maps 0->critical, 1->high, 2->medium, 3-4->low."
  type        = number
  default     = 2
  validation {
    condition     = var.severity >= 0 && var.severity <= 4
    error_message = "severity must be between 0 and 4."
  }
}

variable "metric_namespace" {
  description = "Azure Monitor metric namespace (e.g. 'Microsoft.DBforMySQL/flexibleServers')."
  type        = string
}

variable "metric_name" {
  description = "Native platform metric name (e.g. 'cpu_percent', 'node_cpu_usage_percentage', 'HealthyHostCount'). Case-sensitive."
  type        = string
}

variable "aggregation" {
  description = "Server-side aggregation the rule computes per window bin. One of Average / Maximum / Minimum / Total / Count."
  type        = string
  default     = "Average"
  validation {
    condition = contains(
      ["Average", "Maximum", "Minimum", "Total", "Count"],
      var.aggregation
    )
    error_message = "aggregation must be one of Average, Maximum, Minimum, Total, Count."
  }
}

variable "operator" {
  description = "Threshold comparator. One of GreaterThan / GreaterThanOrEqual / LessThan / LessThanOrEqual / Equals / NotEquals."
  type        = string
  default     = "GreaterThan"
  validation {
    condition = contains(
      [
        "GreaterThan",
        "GreaterThanOrEqual",
        "LessThan",
        "LessThanOrEqual",
        "Equals",
        "NotEquals",
      ],
      var.operator,
    )
    error_message = "operator must be one of GreaterThan / GreaterThanOrEqual / LessThan / LessThanOrEqual / Equals / NotEquals."
  }
}

variable "threshold" {
  description = "Numeric threshold the rule compares against."
  type        = number
}

variable "window_size" {
  description = "ISO 8601 duration of each evaluation window (e.g. PT5M)."
  type        = string
  default     = "PT5M"
  validation {
    condition     = can(regex("^PT[0-9]+[MH]$", var.window_size))
    error_message = "window_size must be an ISO 8601 minute or hour duration (e.g. PT5M, PT1H)."
  }
}

variable "evaluation_frequency" {
  description = "How often Azure Monitor evaluates the rule (ISO 8601 duration)."
  type        = string
  default     = "PT1M"
  validation {
    condition     = can(regex("^PT[0-9]+[MH]$", var.evaluation_frequency))
    error_message = "evaluation_frequency must be an ISO 8601 minute or hour duration."
  }
}

variable "action_group_ids" {
  description = "ARM ids of the action groups notified when the rule fires."
  type        = list(string)
  validation {
    condition     = length(var.action_group_ids) >= 1
    error_message = "action_group_ids must contain at least one action group (usually the FDAI webhook receiver)."
  }
}

variable "enabled" {
  description = "Whether the alert rule is enabled. Upstream default true so a fork toggling this off is an explicit disable, not a silent gap."
  type        = bool
  default     = true
}

variable "auto_mitigate" {
  description = "Whether Azure Monitor auto-marks the alert as Resolved when the condition clears. Keep true so the normalizer sees a matching azure.metric_alert.resolved event and the pipeline can close the correlated incident."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags applied to the rule. Merge with the fork's fdai:* set."
  type        = map(string)
  default     = {}
}

resource "azurerm_monitor_metric_alert" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  scopes              = var.scopes
  description         = var.description
  severity            = var.severity
  enabled             = var.enabled
  auto_mitigate       = var.auto_mitigate
  window_size         = var.window_size
  frequency           = var.evaluation_frequency
  tags                = var.tags

  criteria {
    metric_namespace = var.metric_namespace
    metric_name      = var.metric_name
    aggregation      = var.aggregation
    operator         = var.operator
    threshold        = var.threshold
  }

  dynamic "action" {
    for_each = toset(var.action_group_ids)
    content {
      action_group_id = action.value
    }
  }
}

output "id" {
  description = "ARM id of the alert rule."
  value       = azurerm_monitor_metric_alert.this.id
}

output "name" {
  description = "Alert rule name (echo of var.name for module chaining)."
  value       = azurerm_monitor_metric_alert.this.name
}

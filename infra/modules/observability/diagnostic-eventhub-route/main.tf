// Reusable Diagnostic Setting -> Event Hub route (opt-in) - streams a
// resource's AllMetrics + AllLogs categories to an Event Hub in
// near-real-time (~15-60 s). The Kafka-compatible endpoint on the
// Event Hubs namespace lets the existing FDAI Kafka consumer pick each
// batch up; each record then flows through
// `fdai.delivery.azure.monitor_diagnostic.normalize_diagnostic_records`
// and enters the trust router like any other event.
//
// Boundary with the Metric Alert Rule module (sibling):
//
// - Metric Alert: cheap, per-firing. Rule + threshold live in Azure.
//   Latency ~30-90 s (rule window + delivery). Best when a small set
//   of known-good alerts drives autonomy.
// - Diagnostic stream (this): fastest, one Diagnostic Setting per
//   resource covers every metric it emits. Latency ~15-60 s. Best
//   when the fork wants centralized threshold authority inside FDAI
//   and low latency for many metrics per resource.
//
// A fork MAY wire both - the two normalizers happily coexist, and the
// trust router deduplicates by idempotency key.
//
// Example:
//
//     module "aks_diagnostic_stream" {
//       source              = "../../modules/observability/diagnostic-eventhub-route"
//       name                = "diag-aks-eh"
//       target_resource_id  = module.aks.id
//       event_hub_authorization_rule_id = azurerm_eventhub_namespace_authorization_rule.diag.id
//       event_hub_name      = azurerm_eventhub.diag_all.name
//       metric_categories   = ["AllMetrics"]
//       log_categories      = []
//     }

variable "name" {
  description = "Diagnostic setting name attached to the target resource. CAF-shaped: diag-<workload>-<target>."
  type        = string
  validation {
    condition     = length(var.name) > 0 && length(var.name) <= 260
    error_message = "name must be non-empty and <= 260 chars."
  }
}

variable "target_resource_id" {
  description = "ARM id of the resource whose diagnostic setting is attached (AKS cluster, App Gateway, MySQL Flexible Server, ...)."
  type        = string
}

variable "event_hub_authorization_rule_id" {
  description = "Authorization rule ARM id on the Event Hubs NAMESPACE (not the hub) that grants Send. Reuse one namespace-level rule across every diagnostic route to avoid a per-target rule explosion."
  type        = string
}

variable "event_hub_name" {
  description = "Event Hub (within the namespace) the diagnostic setting streams to. The Kafka consumer subscribes to the same hub via the Kafka endpoint on :9093."
  type        = string
}

variable "metric_categories" {
  description = "Metric categories to route. 'AllMetrics' captures every native platform metric for the target resource type; leave empty to disable the metric stream."
  type        = list(string)
  default     = ["AllMetrics"]
}

variable "log_categories" {
  description = "Log categories to route. Empty by default so the fork opts in per category (categories vary by resource type; use `az monitor diagnostic-settings categories list` to enumerate for the target)."
  type        = list(string)
  default     = []
}

resource "azurerm_monitor_diagnostic_setting" "this" {
  name                           = var.name
  target_resource_id             = var.target_resource_id
  eventhub_authorization_rule_id = var.event_hub_authorization_rule_id
  eventhub_name                  = var.event_hub_name

  dynamic "metric" {
    for_each = toset(var.metric_categories)
    content {
      category = metric.value
    }
  }

  dynamic "enabled_log" {
    for_each = toset(var.log_categories)
    content {
      category = enabled_log.value
    }
  }
}

output "id" {
  description = "ARM id of the diagnostic setting."
  value       = azurerm_monitor_diagnostic_setting.this.id
}

output "service" {
  description = "Operator service deployment outputs."
  value = {
    id                   = module.operator_service.id
    name                 = module.operator_service.name
    fqdn                 = module.operator_service.fqdn
    latest_revision_name = module.operator_service.latest_revision_name
    channel_edge         = module.operator_service.channel_edge
  }
}
output "channel_edge_health_contract" {
  description = "Standalone channel-edge health contract when enabled."
  value       = var.channel_edge.enabled ? var.channel_edge.health : null
}
output "health_contract" {
  description = "Health contract used by post-deploy verification."
  value       = var.health
}

output "rollback_contract" {
  description = "Rollback contract used by protected deployment orchestration."
  value       = var.rollback
}

output "event_topics" {
  description = "Event topics bound to this service revision."
  value       = var.event_topics
}

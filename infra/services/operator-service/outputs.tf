output "service" {
  description = "Operator service deployment outputs."
  value = {
    id                   = module.operator_service.id
    name                 = module.operator_service.name
    fqdn                 = module.operator_service.fqdn
    latest_revision_name = module.operator_service.latest_revision_name
  }
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

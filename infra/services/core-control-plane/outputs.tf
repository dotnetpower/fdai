output "service" {
  description = "Core service deployment outputs."
  value = {
    id                   = module.core_control_plane.id
    name                 = module.core_control_plane.name
    latest_revision_name = module.core_control_plane.latest_revision_name
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

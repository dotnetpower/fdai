output "service" {
  description = "Isolated Executor deployment outputs."
  value = {
    id                   = module.isolated_executor.id
    name                 = module.isolated_executor.name
    latest_revision_name = module.isolated_executor.latest_revision_name
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

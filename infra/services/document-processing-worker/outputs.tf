output "service" {
  description = "Document processing worker deployment outputs."
  value = {
    id                   = module.document_processing_worker.id
    name                 = module.document_processing_worker.name
    latest_revision_name = module.document_processing_worker.latest_revision_name
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

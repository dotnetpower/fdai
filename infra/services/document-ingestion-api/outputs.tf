output "service" {
  description = "Document ingestion API deployment outputs."
  value = {
    id                   = module.document_ingestion_api.id
    name                 = module.document_ingestion_api.name
    fqdn                 = module.document_ingestion_api.fqdn
    latest_revision_name = module.document_ingestion_api.latest_revision_name
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

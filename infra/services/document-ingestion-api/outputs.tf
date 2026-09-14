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
output "channel_intake" {
  description = "Internal channel attachment intake deployment outputs when enabled."
  value       = module.document_ingestion_api.channel_intake
}
output "channel_intake_health_contract" {
  description = "Internal channel attachment intake health contract when enabled."
  value       = var.channel_intake.health
}
output "rollback_contract" {
  description = "Rollback contract used by protected deployment orchestration."
  value       = var.rollback
}
output "event_topics" {
  description = "Event topics bound to this service revision."
  value       = var.event_topics
}

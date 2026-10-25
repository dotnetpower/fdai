output "installation_binding" {
  sensitive = true
  value = {
    ingestion_identity_client_id           = module.identity["ingestion"].client_id
    ingestion_worker_identity_client_id    = module.identity["worker"].client_id
    ingestion_migration_identity_client_id = module.identity["migration"].client_id
    notification_identity_client_id        = module.identity["notification"].client_id
    document_storage_account               = module.document_storage.name
    document_storage_dfs_endpoint          = module.document_storage.primary_dfs_endpoint
    document_source_file_system            = module.document_storage.source_file_system
    document_derived_file_system           = module.document_storage.derived_file_system
    document_intelligence_endpoint         = module.document_intelligence.endpoint
    communication_service_id               = azurerm_communication_service.notifications.id
    email_sender_domain                    = azurerm_email_communication_service_domain.notifications.from_sender_domain
  }
}

output "evidence" {
  value = {
    identity_principal_ids = {
      for key, identity in module.identity : key => identity.principal_id
    }
    document_storage_id            = module.document_storage.id
    document_intelligence_id       = module.document_intelligence.resource_id
    document_blob_private_endpoint = module.document_blob_private_endpoint.private_endpoint_id
    document_dfs_private_endpoint  = module.document_dfs_private_endpoint.private_endpoint_id
    document_intelligence_endpoint = module.document_intelligence_private_endpoint.private_endpoint_id
    communication_service_id       = azurerm_communication_service.notifications.id
    email_communication_service_id = azurerm_email_communication_service.notifications.id
    email_domain_id                = azurerm_email_communication_service_domain.notifications.id
    workload_container_app_count   = 0
    workload_container_job_count   = 0
  }
}

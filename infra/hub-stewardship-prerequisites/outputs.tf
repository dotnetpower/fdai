output "installation_binding" {
  sensitive = true
  value = {
    ingestion_identity_client_id             = module.identity["ingestion"].client_id
    ingestion_identity_resource_id           = module.identity["ingestion"].resource_id
    ingestion_worker_identity_client_id      = module.identity["worker"].client_id
    ingestion_worker_identity_resource_id    = module.identity["worker"].resource_id
    ingestion_migration_identity_client_id   = module.identity["migration"].client_id
    ingestion_migration_identity_resource_id = module.identity["migration"].resource_id
    notification_identity_client_id          = module.identity["notification"].client_id
    notification_identity_resource_id        = module.identity["notification"].resource_id
    operator_identity_client_id              = module.identity["operator_api"].client_id
    operator_identity_resource_id            = module.identity["operator_api"].resource_id
    command_identity_client_id               = module.identity["command"].client_id
    command_identity_resource_id             = module.identity["command"].resource_id
    document_storage_account                 = module.document_storage.name
    document_storage_dfs_endpoint            = module.document_storage.primary_dfs_endpoint
    document_source_file_system              = module.document_storage.source_file_system
    document_derived_file_system             = module.document_storage.derived_file_system
    document_intelligence_endpoint           = module.document_intelligence.endpoint
    communication_service_id                 = azurerm_communication_service.notifications.id
    email_sender_domain                      = azurerm_email_communication_service_domain.notifications.from_sender_domain
  }
}

output "topology_generation" {
  sensitive = true
  value = {
    identity_bindings = {
      document-ingestion-api = {
        client_id   = module.identity["ingestion"].client_id
        resource_id = module.identity["ingestion"].resource_id
      }
      document-processing-worker = {
        client_id   = module.identity["worker"].client_id
        resource_id = module.identity["worker"].resource_id
      }
      operator-service = {
        client_id   = module.identity["operator_api"].client_id
        resource_id = module.identity["operator_api"].resource_id
        additional_identities = {
          command = {
            client_id   = module.identity["command"].client_id
            resource_id = module.identity["command"].resource_id
          }
        }
      }
    }
    migration_identity_binding = {
      service_account = "fdai-schema-migration"
      client_id       = module.identity["migration"].client_id
      resource_id     = module.identity["migration"].resource_id
    }
    config_map_data = var.config_map_data
    secret_bindings = var.secret_bindings
  }
}

output "retained_ownership" {
  sensitive = true
  value = {
    format    = "fdai.hub-stewardship-prerequisite-ownership.v1"
    namespace = var.namespace
    azure = {
      user_assigned_identities = {
        for key, identity in module.identity : key => identity.resource_id
      }
      federated_identity_credentials = {
        for key, credential in azurerm_federated_identity_credential.workload :
        key => {
          id      = credential.id
          subject = credential.subject
        }
      }
    }
    kubernetes = {
      service_accounts        = sort(keys(kubernetes_service_account_v1.prerequisite))
      config_maps             = sort(keys(kubernetes_config_map_v1.runtime_environment))
      secret_provider_classes = sort(keys(kubernetes_manifest.secret_provider))
      secrets                 = sort(keys(kubernetes_secret_v1.runtime))
    }
    lifecycle_agent_managed_kinds = [
      "CronJob",
      "Deployment",
      "HorizontalPodAutoscaler",
      "Service",
    ]
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
    kubernetes_prerequisite_counts = {
      service_accounts        = length(kubernetes_service_account_v1.prerequisite)
      config_maps             = length(kubernetes_config_map_v1.runtime_environment)
      secret_provider_classes = length(kubernetes_manifest.secret_provider)
      secrets                 = length(kubernetes_secret_v1.runtime)
    }
    workload_deployment_count                = 0
    workload_service_count                   = 0
    workload_horizontal_pod_autoscaler_count = 0
    workload_cron_job_count                  = 0
    workload_container_app_count             = 0
    workload_container_job_count             = 0
  }
}

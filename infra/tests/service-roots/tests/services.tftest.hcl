mock_provider "azurerm" {}

run "core_control_plane_plan" {
  command = plan
  module { source = "../../services/core-control-plane" }
  variables {
    name = "ca-fdai-core"
    platform = {
      resource_group_name          = "rg-example"
      container_app_environment_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.App/managedEnvironments/cae-example"
      acr_login_server             = "registry.example.com"
      kafka_bootstrap_servers      = "kafka.example.com:9093"
    }
    image        = "registry.example.com/fdai@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    identity     = { resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-core", client_id = "core-client" }
    event_topics = { events = "object.event", executor_command = "object.executor-command", executor_receipt = "object.executor-receipt" }
    database     = { dsn_secret_id = "https://example.vault.azure.net/secrets/core-dsn", role = "fdai_core" }
    rollback     = { strategy = "previous-revision", previous_image = "registry.example.com/fdai@sha256:1111111111111111111111111111111111111111111111111111111111111111" }
    runtime_env  = "dev"
  }
  assert {
    condition     = output.service.name == "ca-fdai-core"
    error_message = "Core root must preserve its service name."
  }
  assert {
    condition     = output.rollback_contract.strategy == "previous-revision"
    error_message = "Core root must expose its rollback contract."
  }
}

run "operator_service_plan" {
  command = plan
  module { source = "../../services/operator-service" }
  variables {
    name = "ca-fdai-operator"
    platform = {
      resource_group_name          = "rg-example"
      container_app_environment_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.App/managedEnvironments/cae-example"
      acr_login_server             = "registry.example.com"
      kafka_bootstrap_servers      = "kafka.example.com:9093"
    }
    image = "registry.example.com/operator@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    identity = {
      runtime_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-operator"
      runtime_client_id   = "operator-client"
      command_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-command"
      command_client_id   = "command-client"
    }
    event_topics       = { events = "object.event" }
    database           = { dsn_secret_id = "https://example.vault.azure.net/secrets/operator-dsn", role = "fdai_operator" }
    rollback           = { strategy = "previous-revision", previous_image = "registry.example.com/operator@sha256:1111111111111111111111111111111111111111111111111111111111111111" }
    runtime_env        = "dev"
    auth               = { tenant_id = "example-tenant", api_audience = "api://fdai-example" }
    cors_allow_origins = "https://console.example.com"
  }
  assert {
    condition     = output.service.name == "ca-fdai-operator"
    error_message = "Operator root must preserve its service name."
  }
}

run "document_ingestion_api_plan" {
  command = plan
  module { source = "../../services/document-ingestion-api" }
  variables {
    name = "ca-fdai-ingestion"
    platform = {
      resource_group_name          = "rg-example"
      container_app_environment_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.App/managedEnvironments/cae-example"
      acr_login_server             = "registry.example.com"
      kafka_bootstrap_servers      = "kafka.example.com:9093"
    }
    image              = "registry.example.com/ingestion@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    identity           = { resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-ingestion", client_id = "ingestion-client" }
    event_topics       = { pipeline_stages = "aw.pipeline.stages" }
    database           = { dsn_secret_id = "https://example.vault.azure.net/secrets/ingestion-dsn", role = "fdai_ingestion_api" }
    document_store     = { account_name = "storageexample", account_url = "https://storage.example.com", source_file_system = "documents" }
    rollback           = { strategy = "previous-revision", previous_image = "registry.example.com/ingestion@sha256:1111111111111111111111111111111111111111111111111111111111111111" }
    runtime_env        = "dev"
    auth               = { tenant_id = "example-tenant", api_audience = "api://fdai-example" }
    cors_allow_origins = "https://console.example.com"
  }
  assert {
    condition     = output.service.name == "ca-fdai-ingestion"
    error_message = "Ingestion API root must preserve its service name."
  }
}

run "document_processing_worker_plan" {
  command = plan
  module { source = "../../services/document-processing-worker" }
  variables {
    name = "ca-fdai-document-worker"
    platform = {
      resource_group_name          = "rg-example"
      container_app_environment_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.App/managedEnvironments/cae-example"
      acr_login_server             = "registry.example.com"
      kafka_bootstrap_servers      = "kafka.example.com:9093"
    }
    image          = "registry.example.com/document-worker@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    identity       = { resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-document-worker", client_id = "document-worker-client" }
    event_topics   = { pipeline_stages = "aw.pipeline.stages", pantheon_objects = "aw.pantheon.objects" }
    database       = { dsn_secret_id = "https://example.vault.azure.net/secrets/document-worker-dsn", role = "fdai_ingestion_worker" }
    document_store = { account_name = "storageexample", account_url = "https://storage.example.com", source_file_system = "documents", derived_file_system = "derived" }
    rollback       = { strategy = "previous-revision", previous_image = "registry.example.com/document-worker@sha256:1111111111111111111111111111111111111111111111111111111111111111" }
    runtime_env    = "dev"
  }
  assert {
    condition     = output.service.name == "ca-fdai-document-worker"
    error_message = "Document worker root must preserve its service name."
  }
}

run "isolated_executor_plan" {
  command = plan
  module { source = "../../services/isolated-executor" }
  variables {
    name = "ca-fdai-executor"
    platform = {
      resource_group_name          = "rg-example"
      container_app_environment_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.App/managedEnvironments/cae-example"
      acr_login_server             = "registry.example.com"
      kafka_bootstrap_servers      = "kafka.example.com:9093"
    }
    image        = "registry.example.com/executor@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    identity     = { transport_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-executor", transport_client_id = "executor-client" }
    event_topics = { command = "object.executor-command", receipt = "object.executor-receipt", dlq_suffix = ".dlq" }
    database     = { dsn_secret_id = "https://example.vault.azure.net/secrets/executor-dsn", role = "fdai_executor" }
    rollback     = { strategy = "previous-revision", previous_image = "registry.example.com/executor@sha256:1111111111111111111111111111111111111111111111111111111111111111", authority_fallback = "core-in-process-shadow" }
    runtime_env  = "dev"
    authority    = { cutover = false, dev_operations_gateway_url = "", dev_operations_gateway_audience = "" }
  }
  assert {
    condition     = output.service.name == "ca-fdai-executor"
    error_message = "Executor root must preserve its service name."
  }
  assert {
    condition     = output.rollback_contract.authority_fallback == "core-in-process-shadow"
    error_message = "Executor root must expose its authority fallback."
  }
}

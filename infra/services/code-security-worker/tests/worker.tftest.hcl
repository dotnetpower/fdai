mock_provider "azurerm" {}

variables {
  name = "ca-fdai-code-security-worker"
  platform = {
    resource_group_name          = "rg-example"
    container_app_environment_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.App/managedEnvironments/cae-example"
    acr_login_server             = "registry.example.com"
    kafka_bootstrap_servers      = "kafka.example.com:9093"
  }
  image    = "registry.example.com/code-security-scanner@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  identity = { resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-code-security-worker", client_id = "code-security-worker-client" }
  database = {
    dsn_secret_id = "https://example.vault.azure.net/secrets/code-security-worker-dsn"
    host          = "postgres.example.com"
    role          = "fdai_code_security_worker"
  }
  github = {
    app_client_id             = "example-client"
    app_installation_id       = "example-installation"
    app_private_key_secret_id = "https://example.vault.azure.net/secrets/code-security-github-app"
  }
  cache       = { storage_name = "code-security-cache" }
  runtime_env = "dev"
  worker = {
    request_interval_seconds  = 5
    schedule_interval_seconds = 300
    max_requests              = 20
    max_repositories          = 5
  }
  resources = { cpu = 2, memory = "4Gi" }
  tags      = {}
}

run "dedicated_worker_contract" {
  command = plan

  assert {
    condition = (
      output.service.name == "ca-fdai-code-security-worker" &&
      output.database_role == "fdai_code_security_worker" &&
      output.worker_contract.request_interval_seconds == 5 &&
      output.worker_contract.schedule_interval_seconds == 300 &&
      output.worker_contract.max_requests == 20 &&
      output.worker_contract.max_repositories == 5
    )
    error_message = "Code-security worker root must preserve restricted serialized defaults."
  }
}

run "container_app_contract" {
  command = plan
  module { source = "./modules/code-security-worker" }

  assert {
    condition = (
      azurerm_container_app.worker.template[0].min_replicas == 1 &&
      azurerm_container_app.worker.template[0].max_replicas == 1 &&
      jsonencode(azurerm_container_app.worker.template[0].container[0].command) == jsonencode(["/usr/local/bin/fdai-scan-runner"]) &&
      jsonencode(azurerm_container_app.worker.template[0].container[0].args) == jsonencode([
        "serve-workers",
        "--state-access",
        "restricted",
        "--work-root",
        "/work",
        "--kafka-bootstrap-servers",
        "kafka.example.com:9093",
        "--request-interval-seconds",
        "5",
        "--schedule-interval-seconds",
        "300",
        "--max-requests",
        "20",
        "--max-repositories",
        "5",
      ]) &&
      {
        for item in azurerm_container_app.worker.template[0].container[0].env :
        item.name => item.value
        if item.value != null
      }["FDAI_DATABASE_ROLE"] == "fdai_code_security_worker" &&
      {
        for item in azurerm_container_app.worker.template[0].container[0].env :
        item.name => item.value
        if item.value != null
      }["FDAI_EXECUTION_VENUE"] == "deployed" &&
      azurerm_container_app.worker.template[0].volume[0].storage_name == "code-security-cache"
    )
    error_message = "The Container App must be one serialized scanner-image worker in restricted mode."
  }
}

run "missing_scanner_image_fails_closed" {
  command = plan
  variables { image = "" }
  expect_failures = [
    var.image,
  ]
}

run "broad_database_role_fails_closed" {
  command = plan
  variables {
    database = {
      dsn_secret_id = "https://example.vault.azure.net/secrets/code-security-worker-dsn"
      host          = "postgres.example.com"
      role          = "fdai_core"
    }
  }
  expect_failures = [
    var.database,
  ]
}

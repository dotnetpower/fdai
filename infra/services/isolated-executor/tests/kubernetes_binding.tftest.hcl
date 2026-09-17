mock_provider "azurerm" {}

variables {
  name  = "example-executor"
  image = "registry.example.com/executor@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  platform = {
    resource_group_name          = "example"
    container_app_environment_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.App/managedEnvironments/example"
    acr_login_server             = "registry.example.com"
    kafka_bootstrap_servers      = "broker.example.com:9093"
  }
  identity = {
    transport_resource_id  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/transport"
    transport_client_id    = "00000000-0000-0000-0000-000000000001"
    change_resource_id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/change"
    change_client_id       = "00000000-0000-0000-0000-000000000002"
    resilience_resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/resilience"
    resilience_client_id   = "00000000-0000-0000-0000-000000000003"
    finops_resource_id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/finops"
    finops_client_id       = "00000000-0000-0000-0000-000000000004"
  }
  event_topics = { command = "example-command", receipt = "example-receipt", dlq_suffix = "-dlq" }
  database = {
    dsn_secret_id = "https://vault.example.com/secrets/executor"
    host          = "database.example.com"
    role          = "fdai_executor"
  }
  rollback = {
    strategy           = "previous-revision"
    previous_image     = "registry.example.com/executor@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    authority_fallback = "core-in-process"
  }
  runtime_env = "dev"
  authority = {
    cutover                         = true
    dev_operations_gateway_url      = "https://gateway.example.com"
    dev_operations_gateway_audience = "api://gateway-example"
  }
}

run "default_binding_remains_disabled" {
  command = plan
  assert {
    condition     = var.kubernetes_direct_api == null
    error_message = "Kubernetes integration must remain opt-in."
  }
}

run "explicit_public_ca_binding" {
  command = plan
  variables {
    kubernetes_direct_api = {
      api_server         = "https://kubernetes.example.com"
      cluster_ref        = "cluster:example"
      audience           = "api://kubernetes-example"
      ca_pem             = "-----BEGIN CERTIFICATE-----\nEXAMPLE\n-----END CERTIFICATE-----"
      allowed_namespaces = ["example-store"]
    }
  }
  assert {
    condition     = output.service.name == "example-executor"
    error_message = "The binding must reuse the existing executor service."
  }
}

run "reject_unverified_transport" {
  command = plan
  variables {
    kubernetes_direct_api = {
      api_server         = "http://kubernetes.example.com"
      cluster_ref        = "cluster:example"
      audience           = "api://kubernetes-example"
      ca_pem             = "-----BEGIN CERTIFICATE-----\nEXAMPLE\n-----END CERTIFICATE-----"
      allowed_namespaces = ["example-store"]
    }
  }
  expect_failures = [var.kubernetes_direct_api]
}

run "reject_wildcard_scope" {
  command = plan
  variables {
    kubernetes_direct_api = {
      api_server         = "https://kubernetes.example.com"
      cluster_ref        = "cluster:example"
      audience           = "api://kubernetes-example"
      ca_pem             = "-----BEGIN CERTIFICATE-----\nEXAMPLE\n-----END CERTIFICATE-----"
      allowed_namespaces = ["*"]
    }
  }
  expect_failures = [var.kubernetes_direct_api]
}

run "reject_private_key_material" {
  command = plan
  variables {
    kubernetes_direct_api = {
      api_server         = "https://kubernetes.example.com"
      cluster_ref        = "cluster:example"
      audience           = "api://kubernetes-example"
      ca_pem             = "-----BEGIN CERTIFICATE-----\nPRIVATE KEY\n-----END CERTIFICATE-----"
      allowed_namespaces = ["example-store"]
    }
  }
  expect_failures = [var.kubernetes_direct_api]
}

run "reject_implicit_authority_cutover" {
  command = plan
  override_module {
    target  = module.isolated_executor
    outputs = { id = "example", name = "example-executor", latest_revision_name = "example-revision" }
  }
  variables {
    authority = {
      cutover                         = false
      dev_operations_gateway_url      = "https://gateway.example.com"
      dev_operations_gateway_audience = "api://gateway-example"
    }
    kubernetes_direct_api = {
      api_server         = "https://kubernetes.example.com"
      cluster_ref        = "cluster:example"
      audience           = "api://kubernetes-example"
      ca_pem             = "-----BEGIN CERTIFICATE-----\nEXAMPLE\n-----END CERTIFICATE-----"
      allowed_namespaces = ["example-store"]
    }
  }
  expect_failures = [var.kubernetes_direct_api]
}

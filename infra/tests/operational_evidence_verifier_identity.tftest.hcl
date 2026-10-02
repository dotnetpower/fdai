mock_provider "azurerm" {}
mock_provider "archive" {}

override_data {
  target = data.azurerm_client_config.current
  values = {
    subscription_id = "00000000-0000-0000-0000-000000000000"
    tenant_id       = "00000000-0000-0000-0000-000000000000"
    object_id       = "00000000-0000-0000-0000-000000000001"
  }
}

variables {
  deploy_runner_principal_id = "00000000-0000-0000-0000-000000000001"
  tenant_id                  = "00000000-0000-0000-0000-000000000000"
  region                     = "koreacentral"
  core_image                 = "mcr.microsoft.com/example/fdai@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  postgres_admin_login       = "fdaiadmin"
  postgres_admin_password    = "terraform-test-placeholder-value"
}

run "verifier_identity_disabled_by_default" {
  command = plan
  assert {
    condition     = output.operational_evidence_verifier_identity == null
    error_message = "The verifier identity must stay opt-in by default."
  }
}

run "verifier_identity_is_dedicated_when_enabled" {
  command = plan
  variables {
    enable_operational_evidence_verifier = true
  }
  assert {
    condition = (
      output.operational_evidence_verifier_identity != null &&
      length(azurerm_role_assignment.operational_evidence_verifier_acr_pull) == 1 &&
      azurerm_role_assignment.operational_evidence_verifier_acr_pull[0].role_definition_name == "AcrPull" &&
      length(azurerm_role_assignment.operational_evidence_verifier_monitoring_reader) == 1 &&
      azurerm_role_assignment.operational_evidence_verifier_monitoring_reader[0].role_definition_name == "Monitoring Reader"
    )
    error_message = "The verifier identity may receive only reviewed image-pull and observation-read access in the root module."
  }
}

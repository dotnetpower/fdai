# Root contracts only: bootstrap's legacy child-owned provider cannot be replaced
# by a root mock, so override its outputs. This does not test the real dependency
# graph or child input wiring. Check those with validate/graph and source review;
# bootstrap.tftest.hcl separately exercises bootstrap as the mocked test root.
# Run after provider installation: terraform -chdir=infra/genesis-foundation test -filter=tests/foundation.tftest.hcl
mock_provider "azapi" {}
mock_provider "azurerm" {}

override_module {
  target = module.bootstrap
  outputs = {
    ops_resource_group_name    = "rg-example-ops-krc"
    ops_vnet_id                = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc/providers/Microsoft.Network/virtualNetworks/vnet-example-ops-krc"
    ops_vnet_name              = "vnet-example-ops-krc"
    state_storage_account_name = "stexamplegenesis"
    state_container_name       = "tfstate"
    runner_vm_name             = "vm-example-runner-krc"
    runner_principal_id        = "00000000-0000-0000-0000-000000000002"
    deploy_runner_identity_id  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-example-deploy-krc"
    deploy_runner_client_id    = "00000000-0000-0000-0000-000000000001"
    deploy_runner_principal_id = "00000000-0000-0000-0000-000000000002"
    backend_config_hint        = "synthetic-handoff-only"
    deploy_runner_role_manifest = {
      app_contributor = {
        role_definition_name = "Contributor"
        scope                = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-dev-krc"
      }
      app_user_access_administrator = {
        role_definition_name = "User Access Administrator"
        scope                = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-dev-krc"
      }
      ops_network_contributor = {
        role_definition_name = "Network Contributor"
        scope                = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc"
      }
      state_blob_data_contributor = {
        role_definition_name = "Storage Blob Data Contributor"
        scope                = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-ops-krc/providers/Microsoft.Storage/storageAccounts/stexamplegenesis"
      }
      subscription_eventgrid_contributor = {
        role_definition_name = "EventGrid Contributor"
        scope                = "/subscriptions/00000000-0000-0000-0000-000000000000"
      }
    }
  }
}

variables {
  subscription_id            = "00000000-0000-0000-0000-000000000000"
  tenant_id                  = "00000000-0000-0000-0000-000000000000"
  workload                   = "example"
  env                        = "dev"
  region                     = "koreacentral"
  region_short               = "krc"
  state_storage_account_name = "stexamplegenesis"
  ops_address_space          = "10.70.0.0/24"
  runner_subnet_prefix       = "10.70.0.0/26"
  pe_subnet_prefix           = "10.70.0.64/26"
  runner_ssh_public_key      = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHA6I7nugiew177uO389Zhg2zliPDuRZdNRwT2lKu3To terraform-plan-evaluation-only"
  runner_source_image_id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-images/providers/Microsoft.Compute/galleries/example_gallery/images/runner/versions/1.2.3"
  source_commit              = "0000000000000000000000000000000000000000"
  run_digest                 = "0000000000000000000000000000000000000000000000000000000000000000"
  foundation_context_digest  = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}

run "foundation_contracts_with_bootstrap_outputs" {
  command = plan

  assert {
    condition = (
      azapi_resource.app_resource_group.type == "Microsoft.Resources/resourceGroups@2022-09-01" &&
      azapi_resource.app_resource_group.parent_id == "/subscriptions/${var.subscription_id}" &&
      output.app_resource_group_name == "rg-example-dev-krc" &&
      module.bootstrap.ops_resource_group_name == "rg-example-ops-krc" &&
      azapi_resource.state.parent_id == "/subscriptions/${var.subscription_id}/resourceGroups/${module.bootstrap.ops_resource_group_name}" &&
      azapi_resource.state.name == var.state_storage_account_name
    )
    error_message = "Foundation must name the app RG and stable account, using the bootstrap ops RG output for the account parent."
  }

  assert {
    condition = (
      azapi_resource.app_resource_group.tags["fdai:foundation-context"] == var.foundation_context_digest &&
      output.foundation_context_digest == var.foundation_context_digest &&
      output.private_handoff.app_resource_group.foundation_context_digest == var.foundation_context_digest &&
      !contains(keys(azapi_resource.state.tags), "fdai:foundation-context") &&
      !contains(keys(local.provenance_tags), "fdai:foundation-context")
    )
    error_message = "The explicit foundation context must bind only the app RG and its reference-only handoff, without changing bootstrap ops ownership."
  }

  assert {
    condition = (
      azapi_resource.state.type == "Microsoft.Storage/storageAccounts@2023-05-01" &&
      azapi_resource.state.body.kind == "StorageV2" &&
      azapi_resource.state.body.sku.name == "Standard_LRS" &&
      azapi_resource.state.body.properties.minimumTlsVersion == "TLS1_2" &&
      azapi_resource.state.body.properties.supportsHttpsTrafficOnly &&
      azapi_resource.state.body.properties.publicNetworkAccess == "Disabled" &&
      !azapi_resource.state.body.properties.allowBlobPublicAccess &&
      !azapi_resource.state.body.properties.allowSharedKeyAccess &&
      !azapi_resource.state.body.properties.allowCrossTenantReplication &&
      azapi_resource.state.body.properties.defaultToOAuthAuthentication &&
      !azapi_resource.state.body.properties.isLocalUserEnabled &&
      !azapi_resource.state.body.properties.isSftpEnabled
    )
    error_message = "The ARM-managed state account must remain private, TLS-only, keyless, and protected from anonymous or cross-tenant replication access."
  }

  assert {
    condition = (
      azapi_resource.state.body.properties.networkAcls.defaultAction == "Deny" &&
      azapi_resource.state.body.properties.networkAcls.bypass == "None" &&
      length(azapi_resource.state.body.properties.networkAcls.ipRules) == 0 &&
      length(azapi_resource.state.body.properties.networkAcls.virtualNetworkRules) == 0 &&
      !var.enable_public_egress
    )
    error_message = "Default foundation must not add public egress, trusted-service bypasses, or public storage firewall exceptions."
  }

  assert {
    condition = (
      azapi_update_resource.state_blob_service.type == "Microsoft.Storage/storageAccounts/blobServices@2023-05-01" &&
      azapi_update_resource.state_blob_service.body.properties.isVersioningEnabled &&
      azapi_update_resource.state_blob_service.body.properties.deleteRetentionPolicy.enabled &&
      azapi_update_resource.state_blob_service.body.properties.deleteRetentionPolicy.days == 30 &&
      azapi_update_resource.state_blob_service.body.properties.containerDeleteRetentionPolicy.enabled &&
      azapi_update_resource.state_blob_service.body.properties.containerDeleteRetentionPolicy.days == 30
    )
    error_message = "Blob versioning and both retention policies must be configured through the ARM child resource."
  }

  assert {
    condition = (
      output.private_handoff.runner.bootstrap_mode == "offline" &&
      output.private_handoff.runner.source_image_id == var.runner_source_image_id &&
      output.private_handoff.state.account_name == var.state_storage_account_name &&
      output.private_handoff.state.use_azuread_auth &&
      output.private_handoff.runner.role_manifest == module.bootstrap.deploy_runner_role_manifest &&
      azapi_resource.state.tags["fdai:source-commit"] == var.source_commit &&
      azapi_resource.app_resource_group.tags["fdai:run-digest"] == var.run_digest
    )
    error_message = "Handoff must preserve the pinned image, keyless state, supplied role manifest, and source/run provenance without claiming readiness."
  }

  assert {
    condition = (
      output.private_handoff.ops.resource_group_name == module.bootstrap.ops_resource_group_name &&
      output.private_handoff.ops.vnet_id == module.bootstrap.ops_vnet_id &&
      output.private_handoff.ops.vnet_name == module.bootstrap.ops_vnet_name &&
      output.private_handoff.state.container_name == module.bootstrap.state_container_name &&
      output.private_handoff.runner.vm_name == module.bootstrap.runner_vm_name &&
      output.private_handoff.runner.identity_id == module.bootstrap.deploy_runner_identity_id &&
      output.private_handoff.runner.client_id == module.bootstrap.deploy_runner_client_id &&
      output.private_handoff.runner.principal_id == module.bootstrap.deploy_runner_principal_id
    )
    error_message = "Private handoff references must bind to bootstrap outputs, without mixing identity client and principal identifiers."
  }
}

run "custom_retention" {
  command = plan

  variables {
    state_retention_days = 7
  }

  assert {
    condition = (
      azapi_update_resource.state_blob_service.body.properties.deleteRetentionPolicy.days == 7 &&
      azapi_update_resource.state_blob_service.body.properties.containerDeleteRetentionPolicy.days == 7
    )
    error_message = "The selected retention must reach both ARM policies."
  }
}

run "reject_zero_retention" {
  command = plan

  variables {
    state_retention_days = 0
  }

  expect_failures = [var.state_retention_days]
}

run "reject_fractional_retention" {
  command = plan

  variables {
    state_retention_days = 1.5
  }

  expect_failures = [var.state_retention_days]
}

run "reject_unstable_account_name" {
  command = plan

  variables {
    state_storage_account_name = "not-an-account"
  }

  expect_failures = [var.state_storage_account_name]
}

run "reject_malformed_foundation_context" {
  command = plan

  variables {
    foundation_context_digest = "not-a-digest"
  }

  expect_failures = [var.foundation_context_digest]
}

run "reject_uppercase_foundation_context" {
  command = plan

  variables {
    foundation_context_digest = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  }

  expect_failures = [var.foundation_context_digest]
}

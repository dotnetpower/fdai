# Config contract: the development operations gateway stays out of every
# environment that is not dev.
#
# deploy-and-onboard.md lists the gateway as "dev and private-networking only".
# Its function app sets public_network_access_enabled unconditionally, because
# a developer has to reach it, so that constraint is what keeps a public inbound
# endpoint out of a closed network.
#
# The constraint is enforced by a lifecycle precondition on the function app,
# which blocks the plan outright. Nothing exercised it, so a refactor could have
# dropped or weakened it silently. These runs assert the refusal itself rather
# than the source text.
#
# The non-dev cases use "staging" and the day-zero empty environment rather than
# "prod", because a prod plan trips every other production gate and would bury
# this one under unrelated failures.
#
# The precondition's private-networking clause is not covered here, and cannot
# be: with private networking off, the gateway's private endpoints index an
# empty module.network and the plan dies before the precondition is evaluated.
# That combination is still refused, just by a message that explains nothing.
# Terraform cannot express "expect a failure from a module", so asserting it
# would mean asserting text from an error string.
#
# `mock_provider` supplies synthetic provider responses, so `terraform test`
# runs the real plan graph with no Azure subscription, no credentials, and no
# network. Every identifier below is synthetic.
#
# Run: terraform -chdir=infra test

mock_provider "azurerm" {}
mock_provider "archive" {}

variables {
  region                  = "koreacentral"
  tenant_id               = "00000000-0000-0000-0000-000000000000"
  postgres_admin_login    = "fdaiadmin"
  postgres_admin_password = "terraform-test-placeholder-value"
  core_image              = "mcr.microsoft.com/example/fdai@sha256:0000000000000000000000000000000000000000000000000000000000000000"
}

run "the_gateway_is_absent_by_default" {
  command = plan

  assert {
    condition     = length(azurerm_function_app_flex_consumption.dev_gateway) == 0
    error_message = "a default plan MUST NOT provision a public development gateway"
  }

  assert {
    condition     = length(azurerm_linux_virtual_machine_scale_set.ohl_evidence) == 0
    error_message = "a default plan MUST NOT provision the OHL scale-out evidence target"
  }

  assert {
    condition     = length(module.network) == 0
    error_message = "a default plan MUST NOT provision the evidence target network"
  }

  assert {
    condition = (
      length(module.ohl_evidence_identity) == 0 &&
      length(azurerm_role_assignment.ohl_evidence_acr_pull) == 0 &&
      length(azurerm_role_assignment.ohl_evidence_eventhubs_sender) == 0 &&
      module.compute.ohl_evidence_proposal_job_name == ""
    )
    error_message = "a default plan MUST NOT provision the OHL proposal identity, roles, or Job"
  }
}

run "a_day_zero_plan_refuses_the_gateway" {
  command = plan

  variables {
    env                           = ""
    enable_private_networking     = true
    enable_dev_operations_gateway = true
  }

  expect_failures = [azurerm_function_app_flex_consumption.dev_gateway]
}

run "a_staging_plan_refuses_the_gateway" {
  command = plan

  variables {
    env                           = "staging"
    enable_private_networking     = true
    enable_dev_operations_gateway = true
  }

  expect_failures = [azurerm_function_app_flex_consumption.dev_gateway]
}

run "a_dev_plan_with_private_networking_is_accepted" {
  command = plan

  variables {
    env                           = "dev"
    enable_private_networking     = true
    enable_dev_operations_gateway = true
  }

  assert {
    condition     = length(azurerm_function_app_flex_consumption.dev_gateway) == 1
    error_message = "dev with private networking is the supported combination and MUST plan the gateway"
  }
}

run "an_evidence_target_without_the_gateway_is_refused" {
  command = plan

  variables {
    env                                           = "dev"
    enable_private_networking                     = true
    enable_ohl_scale_out_evidence_target          = true
    ohl_scale_out_evidence_campaign_id            = "campaign-20260813"
    ohl_scale_out_evidence_image_version          = "22.04.202608060"
    ohl_scale_out_evidence_initiator_principal_id = "00000000-0000-0000-0000-000000000001"
    ohl_scale_out_evidence_ssh_public_key         = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIN+lIc914WryAKmYlkcUeKqix2ViKCDsdEKjIKimTFud"
  }

  expect_failures = [azurerm_linux_virtual_machine_scale_set.ohl_evidence[0]]
}

run "a_dev_evidence_target_is_bounded_to_the_app_rg" {
  command = plan

  variables {
    env                                           = "dev"
    enable_private_networking                     = true
    enable_dev_operations_gateway                 = true
    enable_ohl_scale_out_evidence_target          = true
    ohl_scale_out_evidence_campaign_id            = "campaign-20260813"
    ohl_scale_out_evidence_image_version          = "22.04.202608060"
    ohl_scale_out_evidence_initiator_principal_id = "00000000-0000-0000-0000-000000000001"
    ohl_scale_out_evidence_ssh_public_key         = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIN+lIc914WryAKmYlkcUeKqix2ViKCDsdEKjIKimTFud"
  }

  assert {
    condition     = length(azurerm_linux_virtual_machine_scale_set.ohl_evidence) == 1
    error_message = "an explicit dev evidence plan MUST provision exactly one dedicated VMSS"
  }

  assert {
    condition     = azurerm_linux_virtual_machine_scale_set.ohl_evidence[0].resource_group_name == module.resource_group.name
    error_message = "the evidence VMSS MUST stay in the existing application resource group"
  }

  assert {
    condition     = azurerm_role_assignment.dev_gateway_executor_vm[0].role_definition_name == "Virtual Machine Contributor"
    error_message = "the gateway executor MUST reach the evidence VMSS only through its existing app-RG VM role"
  }

  assert {
    condition = (
      length(module.ohl_evidence_identity) == 1 &&
      length(azurerm_role_assignment.ohl_evidence_acr_pull) == 1 &&
      azurerm_role_assignment.ohl_evidence_acr_pull[0].role_definition_name == "AcrPull" &&
      length(azurerm_role_assignment.ohl_evidence_eventhubs_sender) == 1 &&
      azurerm_role_assignment.ohl_evidence_eventhubs_sender[0].role_definition_name == "Azure Event Hubs Data Sender" &&
      module.compute.ohl_evidence_proposal_job_name != ""
    )
    error_message = "the OHL proposal Job MUST use one dedicated identity with only pull and topic-send roles"
  }

  assert {
    condition = (
      azurerm_linux_virtual_machine_scale_set.ohl_evidence[0].instances == 1 &&
      azurerm_linux_virtual_machine_scale_set.ohl_evidence[0].sku == "Standard_B1s" &&
      azurerm_linux_virtual_machine_scale_set.ohl_evidence[0].overprovision == false &&
      azurerm_linux_virtual_machine_scale_set.ohl_evidence[0].source_image_reference[0].version == "22.04.202608060"
    )
    error_message = "the evidence VMSS MUST use the bounded one-instance model and an exact image version"
  }

  assert {
    condition = (
      azurerm_linux_virtual_machine_scale_set.ohl_evidence[0].tags["fdai:managed"] == "true" &&
      azurerm_linux_virtual_machine_scale_set.ohl_evidence[0].tags["fdai:env"] == "dev" &&
      azurerm_linux_virtual_machine_scale_set.ohl_evidence[0].tags["fdai:component"] == "ohl-scale-out-evidence"
    )
    error_message = "the evidence VMSS MUST carry the authoritative ownership, environment, and component tags"
  }

  assert {
    condition = (
      module.network[0].evidence_target_subnet_name == "snet-ohl-evidence" &&
      module.network[0].evidence_target_subnet_prefix == "10.60.4.32/27" &&
      length(azurerm_linux_virtual_machine_scale_set.ohl_evidence[0].network_interface[0].ip_configuration[0].public_ip_address) == 0
    )
    error_message = "the evidence VMSS MUST use an isolated private subnet without a public IP"
  }
}

run "authority_cutover_requires_both_runtime_boundaries" {
  command = plan

  variables {
    enable_isolated_executor_authority_cutover = true
  }

  expect_failures = [terraform_data.isolated_executor_authority_cutover_contract]
}

run "authority_cutover_moves_the_gateway_caller_and_vertical_identities" {
  command = plan

  variables {
    env                                        = "dev"
    enable_private_networking                  = true
    enable_dev_operations_gateway              = true
    enable_isolated_executor                   = true
    enable_isolated_executor_authority_cutover = true
  }

  assert {
    condition     = length(local.core_vertical_identity_ids) == 0
    error_message = "Core must not retain any vertical execution identity after cutover"
  }

  assert {
    condition     = length(local.isolated_executor_vertical_identity_ids) == 3
    error_message = "the isolated Executor must receive all three vertical execution identities"
  }

  assert {
    condition     = length(module.compute.vertical_identity_client_ids) == 3
    error_message = "Core must retain the three env keys as empty non-authoritative compatibility values"
  }
}

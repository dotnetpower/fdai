mock_provider "azapi" {
  override_resource {
    target = azapi_resource.template
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-image-krc-2e17f214622f/providers/Microsoft.VirtualMachineImages/imageTemplates/it-example-runner-krc-2e17f214622f"
    }
  }
  override_data {
    target = data.azapi_resource.runner_image
    values = {
      output = {
        id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-image-krc-2e17f214622f/providers/Microsoft.Compute/images/img-runner-example-dev-krc-2e17f214622f"
        location = "koreacentral"
        properties = {
          provisioningState = "Succeeded"
          storageProfile = {
            osDisk = {
              osType = "Linux"
            }
          }
        }
        tags = {
          "fdai:source-commit"    = "0000000000000000000000000000000000000000"
          "fdai:toolchain-digest" = "2e17f214622f0459c1c104c5d0caf970ea2ea940fea71a092d6da1320370dcb1"
        }
      }
    }
  }
}
mock_provider "azurerm" {
  override_resource {
    target = azurerm_resource_group.image
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-image-krc-2e17f214622f"
    }
  }
  override_resource {
    target = azurerm_resource_group.staging
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-build-krc-2e17f214622f"
    }
  }
  override_resource {
    target = azurerm_user_assigned_identity.builder
    values = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-example-runner-image-krc-2e17f214622f/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-example-runner-build-krc-2e17f214622f"
      principal_id = "00000000-0000-0000-0000-000000000001"
    }
  }
}

variables {
  subscription_id                   = "00000000-0000-0000-0000-000000000000"
  tenant_id                         = "00000000-0000-0000-0000-000000000000"
  workload                          = "example"
  env                               = "dev"
  region                            = "koreacentral"
  region_short                      = "krc"
  source_commit                     = "0000000000000000000000000000000000000000"
  run_digest                        = "0000000000000000000000000000000000000000000000000000000000000000"
  source_image_version              = "24.04.202608270"
  azure_cli_version                 = "2.88.0"
  azure_cli_package_version         = "2.88.0-1~noble"
  microsoft_package_key_fingerprint = "BC528686B50D79E339D3721CEB3E94ADBE1229CF"
  terraform_version                 = "1.9.8"
  terraform_binary_sha256           = "7386e89a97d0f24024955acc79ccf693b75b97f7c6383cb9d966e7d59aa5b223"
  terraform_sha256                  = "186e0145f5e5f2eb97cbd785bc78f21bae4ef15119349f6ad4fa535b83b10df8"
  opa_version                       = "0.68.0"
  opa_sha256                        = "dfd5081fc6f930dfeaf2a225e31e616fc227dc0c7b43019b73d6f8fb8a1de1aa"
  github_runner_version             = "2.337.0"
  github_runner_sha256              = "0000000000000000000000000000000000000000000000000000000000000001"
}

run "exact_image_builder_contract" {
  command = apply

  assert {
    condition = (
      azapi_resource.template.type == "Microsoft.VirtualMachineImages/imageTemplates@2024-02-01" &&
      azapi_resource.template.body.properties.source.type == "PlatformImage" &&
      azapi_resource.template.body.properties.source.publisher == "Canonical" &&
      azapi_resource.template.body.properties.source.offer == "ubuntu-24_04-lts" &&
      azapi_resource.template.body.properties.source.sku == "server" &&
      azapi_resource.template.body.properties.source.version == var.source_image_version &&
      azapi_resource.template.body.properties.autoRun.state == "Disabled"
    )
    error_message = "Runner image build must use only the exact Canonical source and explicit run action."
  }

  assert {
    condition = (
      azapi_resource_action.build.action == "run" &&
      azapi_resource_action.build.method == "POST" &&
      azapi_resource_action.build.when == "apply" &&
      azapi_resource.template.body.properties.errorHandling.onCustomizerError == "cleanup" &&
      azapi_resource.template.body.properties.errorHandling.onValidationError == "cleanup" &&
      !azapi_resource.template.body.properties.validate.continueDistributeOnFailure
    )
    error_message = "Image build must fail closed and clean temporary resources on customization or validation failure."
  }

  assert {
    condition = (
      length(azapi_resource.template.body.properties.customize) == 1 &&
      length(azapi_resource.template.body.properties.validate.inVMValidations) == 1 &&
      strcontains(file("${path.module}/enroll-runner.sh"), "ACTIONS_RUNNER_INPUT_TOKEN") &&
      strcontains(local.customizer, "/usr/local/sbin/fdai-attest-runner") &&
      strcontains(local.customizer, "/usr/local/sbin/fdai-migrate-foundation-state") &&
      strcontains(local.customizer, var.terraform_binary_sha256) &&
      !strcontains(file("${path.module}/enroll-runner.sh"), "--token") &&
      local.toolchain_digest == "2e17f214622f0459c1c104c5d0caf970ea2ea940fea71a092d6da1320370dcb1" &&
      azapi_resource.template.body.properties.distribute[0].type == "ManagedImage" &&
      azapi_resource.template.body.properties.distribute[0].imageId == local.image_id &&
      azapi_resource.template.body.properties.distribute[0].artifactTags["fdai:toolchain-digest"] == local.toolchain_digest &&
      output.runner_image.runner_registered == false &&
      output.runner_image.subscription_ready == false
    )
    error_message = "Only an exact validated managed image may be distributed, without runner registration or readiness claims."
  }

  assert {
    condition = (
      azurerm_role_assignment.builder_image_contributor.scope == azurerm_resource_group.image.id &&
      azurerm_role_assignment.builder_staging_contributor.scope == azurerm_resource_group.staging.id &&
      azapi_resource.template.body.properties.stagingResourceGroup == azurerm_resource_group.staging.id &&
      azapi_resource.template.body.properties.vmProfile.userAssignedIdentities == [azurerm_user_assigned_identity.builder.id]
    )
    error_message = "The image builder identity must remain limited to its exact image and staging groups."
  }
}

run "reject_mutable_source_image" {
  command = plan

  variables {
    source_image_version = "latest"
  }

  expect_failures = [var.source_image_version]
}

run "reject_malformed_tool_digest" {
  command = plan

  variables {
    terraform_sha256 = "not-a-digest"
  }

  expect_failures = [var.terraform_sha256]
}

run "reject_malformed_terraform_binary_digest" {
  command = plan

  variables {
    terraform_binary_sha256 = "not-a-digest"
  }

  expect_failures = [var.terraform_binary_sha256]
}

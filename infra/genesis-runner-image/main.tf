locals {
  toolchain_manifest = {
    schema_version                    = "fdai.genesis-runner-image.v1"
    source_commit                     = var.source_commit
    source_image_version              = var.source_image_version
    azure_cli_version                 = var.azure_cli_version
    azure_cli_package_version         = var.azure_cli_package_version
    microsoft_package_key_fingerprint = var.microsoft_package_key_fingerprint
    terraform_version                 = var.terraform_version
    terraform_binary_sha256           = var.terraform_binary_sha256
    terraform_sha256                  = var.terraform_sha256
    opa_version                       = var.opa_version
    opa_sha256                        = var.opa_sha256
    github_runner_version             = var.github_runner_version
    github_runner_sha256              = var.github_runner_sha256
  }
  toolchain_digest = sha256(jsonencode(local.toolchain_manifest))
  digest_prefix    = substr(local.toolchain_digest, 0, 12)
  suffix           = "${var.workload}-${var.env}-${var.region_short}-${local.digest_prefix}"
  image_name       = "img-runner-${local.suffix}"
  image_id         = "${azurerm_resource_group.image.id}/providers/Microsoft.Compute/images/${local.image_name}"
  customizer = templatefile("${path.module}/customize-runner-image.sh.tftpl", {
    azure_cli_version                 = var.azure_cli_version
    azure_cli_package_version         = var.azure_cli_package_version
    microsoft_package_key_fingerprint = var.microsoft_package_key_fingerprint
    terraform_version                 = var.terraform_version
    terraform_binary_sha256           = var.terraform_binary_sha256
    terraform_sha256                  = var.terraform_sha256
    opa_version                       = var.opa_version
    opa_sha256                        = var.opa_sha256
    github_runner_version             = var.github_runner_version
    github_runner_sha256              = var.github_runner_sha256
    source_commit                     = var.source_commit
    source_image_version              = var.source_image_version
    toolchain_digest                  = local.toolchain_digest
    enrollment_script                 = base64encode(file("${path.module}/enroll-runner.sh"))
    attestation_script                = base64encode(file("${path.module}/attest-runner.sh"))
    state_migration_script            = base64encode(file("${path.module}/migrate-foundation-state.py"))
  })
  tags = {
    "fdai:managed"          = "true"
    "fdai:workload"         = var.workload
    "fdai:env"              = var.env
    "fdai:layer"            = "genesis-runner-image"
    "fdai:managed-by"       = "terraform"
    "fdai:vertical"         = "shared"
    "fdai:source-commit"    = var.source_commit
    "fdai:run-digest"       = var.run_digest
    "fdai:toolchain-digest" = local.toolchain_digest
  }
}

resource "azurerm_resource_group" "image" {
  name     = "rg-${var.workload}-runner-image-${var.region_short}-${local.digest_prefix}"
  location = var.region
  tags     = local.tags
}

resource "azurerm_resource_group" "staging" {
  name     = "rg-${var.workload}-runner-build-${var.region_short}-${local.digest_prefix}"
  location = var.region
  tags     = local.tags
}

resource "azurerm_user_assigned_identity" "builder" {
  name                = "id-${var.workload}-runner-build-${var.region_short}-${local.digest_prefix}"
  location            = var.region
  resource_group_name = azurerm_resource_group.image.name
  tags                = local.tags
}

resource "azurerm_role_assignment" "builder_image_contributor" {
  scope                = azurerm_resource_group.image.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.builder.principal_id
}

resource "azurerm_role_assignment" "builder_staging_contributor" {
  scope                = azurerm_resource_group.staging.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.builder.principal_id
}

resource "azapi_resource" "template" {
  type      = "Microsoft.VirtualMachineImages/imageTemplates@2024-02-01"
  name      = "it-${var.workload}-runner-${var.region_short}-${local.digest_prefix}"
  parent_id = azurerm_resource_group.image.id
  location  = var.region
  tags      = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.builder.id]
  }

  body = {
    properties = {
      autoRun = {
        state = "Disabled"
      }
      buildTimeoutInMinutes = 90
      source = {
        type      = "PlatformImage"
        publisher = "Canonical"
        offer     = "ubuntu-24_04-lts"
        sku       = "server"
        version   = var.source_image_version
      }
      customize = [
        {
          type = "Shell"
          name = "install-exact-runner-toolchain"
          inline = [
            "printf '%s' '${base64encode(local.customizer)}' | base64 -d >/tmp/fdai-runner-image.sh",
            "chmod 0700 /tmp/fdai-runner-image.sh",
            "/tmp/fdai-runner-image.sh",
            "rm -f /tmp/fdai-runner-image.sh",
          ]
        }
      ]
      validate = {
        continueDistributeOnFailure = false
        sourceValidationOnly        = false
        inVMValidations = [
          {
            type = "Shell"
            name = "verify-exact-runner-toolchain"
            inline = [
              "test \"$(az version --query '\"azure-cli\"' --output tsv)\" = '${var.azure_cli_version}'",
              "test \"$(terraform version -json | jq -r .terraform_version)\" = '${var.terraform_version}'",
              "opa version | grep -F 'Version: ${var.opa_version}' >/dev/null",
              "printf '%s  %s\n' '${var.github_runner_sha256}' '/opt/fdai/runner/actions-runner-linux-x64-${var.github_runner_version}.tar.gz' | sha256sum -c -",
              "test \"$(jq -r .toolchain_digest /etc/fdai-runner-image.json)\" = '${local.toolchain_digest}'",
              "test -x /usr/local/sbin/fdai-enroll-runner",
              "test -x /usr/local/sbin/fdai-attest-runner",
              "test -x /usr/local/sbin/fdai-migrate-foundation-state",
              "test ! -e /root/.azure && test ! -e /root/.config/gh && test ! -e /root/.docker && test ! -e /root/.git-credentials",
            ]
          }
        ]
      }
      distribute = [
        {
          type          = "ManagedImage"
          runOutputName = "runner-${local.digest_prefix}"
          imageId       = local.image_id
          location      = var.region
          artifactTags  = local.tags
        }
      ]
      errorHandling = {
        onCustomizerError = "cleanup"
        onValidationError = "cleanup"
      }
      managedResourceTags = local.tags
      optimize = {
        vmBoot = {
          state = "Enabled"
        }
      }
      stagingResourceGroup = azurerm_resource_group.staging.id
      vmProfile = {
        vmSize                 = var.build_vm_size
        osDiskSizeGB           = 64
        userAssignedIdentities = [azurerm_user_assigned_identity.builder.id]
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.builder_image_contributor,
    azurerm_role_assignment.builder_staging_contributor,
  ]
}

resource "azapi_resource_action" "build" {
  type        = "Microsoft.VirtualMachineImages/imageTemplates@2024-02-01"
  resource_id = azapi_resource.template.id
  action      = "run"
  method      = "POST"
  when        = "apply"

  timeouts {
    create = "2h"
  }
}

data "azapi_resource" "runner_image" {
  type                   = "Microsoft.Compute/images@2024-03-01"
  name                   = local.image_name
  parent_id              = azurerm_resource_group.image.id
  response_export_values = ["id", "location", "properties.provisioningState", "properties.storageProfile.osDisk.osType", "tags"]

  depends_on = [azapi_resource_action.build]

  lifecycle {
    postcondition {
      condition = (
        lower(self.output.id) == lower(local.image_id) &&
        lower(self.output.location) == lower(var.region) &&
        self.output.properties.provisioningState == "Succeeded" &&
        self.output.properties.storageProfile.osDisk.osType == "Linux" &&
        self.output.tags["fdai:source-commit"] == var.source_commit &&
        self.output.tags["fdai:toolchain-digest"] == local.toolchain_digest
      )
      error_message = "The built runner image failed exact identity, location, Linux, provisioning, or provenance readback."
    }
  }
}

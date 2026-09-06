locals {
  suffix                = "${var.workload}-${var.env}-${var.region_short}"
  runner_bootstrap_mode = "offline"
  provenance_tags = {
    "fdai:source-commit"  = var.source_commit
    "fdai:run-digest"     = var.run_digest
    "fdai:terraform-root" = "infra/genesis-foundation"
  }
  tags = merge({
    "fdai:managed"    = "true"
    "fdai:workload"   = var.workload
    "fdai:env"        = var.env
    "fdai:layer"      = "genesis-foundation"
    "fdai:managed-by" = "terraform"
    "fdai:vertical"   = "shared"
  }, local.provenance_tags)
}

# The platform must reference this group, not create or adopt a second owner.
resource "azapi_resource" "app_resource_group" {
  type      = "Microsoft.Resources/resourceGroups@2022-09-01"
  name      = "rg-${local.suffix}"
  parent_id = "/subscriptions/${var.subscription_id}"
  location  = var.region
  tags = merge(local.tags, {
    "fdai:foundation-context" = var.foundation_context_digest
  })
  body = {}
}

# This narrow output depends only on bootstrap's ops RG. A dependency on the
# whole bootstrap module would cycle through its state-account reference and PE.
resource "azapi_resource" "state" {
  type      = "Microsoft.Storage/storageAccounts@2023-05-01"
  name      = var.state_storage_account_name
  parent_id = "/subscriptions/${var.subscription_id}/resourceGroups/${module.bootstrap.ops_resource_group_name}"
  location  = var.region
  tags      = local.tags

  body = {
    kind = "StorageV2"
    sku = {
      name = "Standard_LRS"
    }
    properties = {
      accessTier                   = "Hot"
      minimumTlsVersion            = "TLS1_2"
      supportsHttpsTrafficOnly     = true
      publicNetworkAccess          = "Disabled"
      allowBlobPublicAccess        = false
      allowSharedKeyAccess         = false
      allowCrossTenantReplication  = false
      defaultToOAuthAuthentication = true
      isHnsEnabled                 = false
      isLocalUserEnabled           = false
      isSftpEnabled                = false
      networkAcls = {
        bypass              = "None"
        defaultAction       = "Deny"
        ipRules             = []
        virtualNetworkRules = []
      }
      encryption = {
        keySource = "Microsoft.Storage"
        services = {
          blob = {
            enabled = true
            keyType = "Account"
          }
          file = {
            enabled = true
            keyType = "Account"
          }
        }
      }
    }
  }
}

# ARM creates the default blob service with its account. Manage its properties
# through the child update API, not a second create/import or a data-plane call.
resource "azapi_update_resource" "state_blob_service" {
  type        = "Microsoft.Storage/storageAccounts/blobServices@2023-05-01"
  resource_id = "${azapi_resource.state.id}/blobServices/default"

  body = {
    properties = {
      isVersioningEnabled = true
      deleteRetentionPolicy = {
        enabled = true
        days    = var.state_retention_days
      }
      containerDeleteRetentionPolicy = {
        enabled = true
        days    = var.state_retention_days
      }
    }
  }
}

# Preserve bootstrap's resources, private endpoint/DNS, ephemeral image contract,
# and exact deploy-UAMI role manifest. No module-wide depends_on or provider
# override: the legacy child provider receives the same explicit target.
module "bootstrap" {
  source = "../bootstrap"

  genesis_provider_context = {
    subscription_id = var.subscription_id
    tenant_id       = var.tenant_id
  }
  genesis_state_account_id = azapi_resource.state.id

  workload                     = var.workload
  env                          = var.env
  region                       = var.region
  region_short                 = var.region_short
  app_resource_group_name      = azapi_resource.app_resource_group.name
  state_storage_account_name   = azapi_resource.state.name
  ops_address_space            = var.ops_address_space
  runner_subnet_prefix         = var.runner_subnet_prefix
  pe_subnet_prefix             = var.pe_subnet_prefix
  enable_public_egress         = var.enable_public_egress
  runner_bootstrap_mode        = local.runner_bootstrap_mode
  runner_source_image_id       = var.runner_source_image_id
  runner_ssh_public_key        = var.runner_ssh_public_key
  runner_vm_size               = var.runner_vm_size
  create_runner_vm             = true
  enable_deploy_identity_roles = true
  additional_tags              = local.provenance_tags
}

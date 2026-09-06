# Bootstrap (ops / hub) layer - stands up the durable pieces the app deploy
# needs on a policy-locked "private-everything" tenant:
#
#   1. Terraform remote-state storage (+ blob private endpoint + private DNS)
#      so state lives in a backend the VNet-resident runner can reach.
#   2. An ops VNet (hub) + runner subnet that survives app rebuilds.
#   3. A self-hosted deploy runner VM (no public IP) that is the only host
#      with line-of-sight to the app's private endpoints (Key Vault, storage).
#
# This layer starts with LOCAL state. Standalone account lookup can include
# account keys, so protect that state as secret-bearing. Genesis skips that
# lookup. The app config (../) uses the account as its azurerm remote backend.
#
# Design: docs/roadmap/deployment/deploy-and-onboard.md (private-networking + runner).

terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.14"
    }
  }
}

provider "azurerm" {
  subscription_id                 = var.genesis_provider_context == null ? null : var.genesis_provider_context.subscription_id
  tenant_id                       = var.genesis_provider_context == null ? null : var.genesis_provider_context.tenant_id
  resource_provider_registrations = var.genesis_provider_context == null ? null : "none"

  # Tenant policy forbids shared-key auth on storage; use AAD for every
  # data-plane call so the provider never falls back to account keys.
  storage_use_azuread = true
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}

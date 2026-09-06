# Local, control-plane-only foundation. The installer must isolate this root's
# state in its private run directory; this root never migrates a backend.
# Design: docs/roadmap/deployment/subscription-genesis-{provisioning,assurance}.md.
terraform {
  required_version = ">= 1.9"

  required_providers {
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.0"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.14"
    }
  }
}

# Registration is an explicit prerequisite, never an incidental plan mutation.
provider "azapi" {
  subscription_id            = var.subscription_id
  tenant_id                  = var.tenant_id
  skip_provider_registration = true
  enable_preflight           = false
}

provider "azurerm" {
  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  resource_provider_registrations = "none"
  storage_use_azuread             = true
  features {}
}

# bootstrap owns a legacy child provider. The composition passes the same target
# through its opt-in genesis context instead of relying on provider inheritance.
